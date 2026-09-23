# --- BREKEM STUDIO path shim (injected) ---
import os as _os, sys as _sys, glob as _glob
_HOME  = _os.environ.get("BREKEM_HOME")  or _os.path.dirname(_os.path.abspath(__file__))
_WORK  = _os.environ.get("BREKEM_WORK")  or _os.path.join(_HOME, "_work")
_STEMS = _os.environ.get("BREKEM_STEMS") or _os.path.join(_HOME, "_stems")
_REFSD = _os.environ.get("BREKEM_REFS")  or _os.path.join(_HOME, "refs")
_PYEXE = _os.environ.get("BREKEM_PY")    or _sys.executable
for _d in (_WORK, _STEMS, _REFSD):
    try: _os.makedirs(_d, exist_ok=True)
    except Exception: pass
def _reflist():
    fs = sorted(_glob.glob(_os.path.join(_REFSD, "*.wav")) + _glob.glob(_os.path.join(_REFSD, "*.flac")))
    return fs
def _refdict():
    return {_os.path.splitext(_os.path.basename(f))[0]: f for f in _reflist()}
# --- end shim ---
"""V2 chain para UN tema arbitrario del catalogo.
Uso:  python track_v2.py "<master_name.wav>"  "<carpeta salida>"
Aplica: voz pro + transient shaper + dyn-EQ + saturacion cinta + widen>9k
        + curva 3-refs + bbmatch + MATCHERING x3 refs promediado.
Genera MASTER / INSTRUMENTAL / ACAPELLA / APPLE en la carpeta, + comparativa vs 3 refs.
"""
import os, sys, warnings, numpy as np, soundfile as sf, scipy.signal as sig
warnings.filterwarnings("ignore")

SP = _HOME
import acap_pro as AP
from acap_pro import (SR, load, rms, run, ebur, bands_arr, deepfilter, vbus, glue, polish,
                      bbmatch, kweight, WORK, STEMS,
                      debreath_at, deplosive_gated, dereverb, eq_sub, plate, loud_to)
import re, matchering as mg
try:
    mg.log(info_handler=lambda *a, **k: None, warning_handler=lambda *a, **k: None)
except Exception:
    pass

MF = os.path.join(_WORK, "_out")
NAME = sys.argv[1]
OUT  = sys.argv[2]
PFX  = sys.argv[3] if len(sys.argv) > 3 else ""     # prefijo de nombre de archivo (ej "cojelo - ")
SHELF_DB = float(sys.argv[4]) if len(sys.argv) > 4 else 1.5   # override low-shelf de graves
AIR_DB   = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0    # override high-shelf de aire (neg = recorta brillo)
NARROW   = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0    # target corr para estrechar el master (0 = off)
PRES_DB  = float(sys.argv[7]) if len(sys.argv) > 7 else 0.0    # peak 3.5 kHz Q0.7 en el master (neg = baja presencia)
WIDEN    = float(sys.argv[8]) if len(sys.argv) > 8 else 0.0    # factor M/S del side en el master (>1 ensancha, 0 = off)
os.makedirs(OUT, exist_ok=True)
TAG  = re.sub(r"\s*master\.wav$", "", NAME).replace(" ", "_")[:60]
VC   = os.path.join(STEMS, TAG, "vocals.flac")
IC   = os.path.join(STEMS, TAG, "no_vocals.flac")
LOG  = os.path.join(SP, "track_v2.log")
def L(m):
    open(LOG, "a", encoding="utf-8").write(str(m) + "\n"); print(m, flush=True)

REFS = _refdict()
def corr_of(p):
    z = load(p); a, b = z[:, 0], z[:, 1]
    return float(np.sum(a*b)/(np.sqrt(np.sum(a**2)*np.sum(b**2))+1e-12))

def libmaster(pin, pout):
    if os.path.exists(pout): os.remove(pout)
    run([_PYEXE, os.path.join(_HOME, "libmaster.py"), pin, pout])
    return pout if os.path.exists(pout) else pin

def mix_punch(x, amount=2.0):
    m = x.mean(1)
    fa = np.exp(-1.0/(0.002*SR)); sa = np.exp(-1.0/(0.050*SR))
    ef = np.sqrt(sig.lfilter([1-fa], [1, -fa], m**2)+1e-12)
    es = np.sqrt(sig.lfilter([1-sa], [1, -sa], m**2)+1e-12)
    d = 20*np.log10(ef+1e-9)-20*np.log10(es+1e-9)
    g = 1.0+np.clip(d, 0, 6.0)*(amount/6.0)/6.0*2.0
    g = np.clip(g, 1.0, 10**(amount/20))
    a = np.exp(-1.0/(0.004*SR)); g = sig.lfilter([1-a], [1, -a], g)
    return x*g[:, None]

def slow_expand(x, ratio, lo=-4.0, hi=1.5):
    mono = x.mean(1); w = int(1.0*SR); hop = int(0.25*SR); kw = kweight(mono); n = len(mono)
    env = np.array([10*np.log10(np.mean(kw[i:i+w]**2)+1e-12) for i in range(0, max(1, n-w), hop)])
    if len(env) < 8: return x
    centre = np.percentile(env, 60)
    g = np.clip((env-centre)*(ratio-1.0), lo, hi)
    fs_env = SR/hop
    g = sig.sosfiltfilt(sig.butter(2, 0.15/(fs_env/2), btype="low", output="sos"), g)
    tsamp = np.arange(n); tenv = np.arange(len(g))*hop + w//2
    return x*(10**(np.interp(tsamp, tenv, g)/20.0))[:, None]

def mono_narrow(y, target=0.80):
    for CT in (0.72, 0.78, 0.83, 0.88, 0.93, 0.97):
        Lc, Rc = y[:, 0], y[:, 1]
        c0 = float(np.sum(Lc*Rc)/(np.sqrt(np.sum(Lc**2)*np.sum(Rc**2))+1e-12))
        if c0 >= target: return y
        k = float(np.clip(np.sqrt(((1-CT)*(1+c0))/((1+CT)*(1-c0)+1e-12)), 0.12, 1.0))
        mid = (Lc+Rc)*0.5; side = (Lc-Rc)*0.5*k
        y = np.stack([mid+side, mid-side], 1)
    return y

def transient_shape(x, band_hi=170.0, boost_db=3.5):
    lowsos = sig.butter(3, band_hi/(SR/2), btype="low", output="sos")
    low = sig.sosfilt(lowsos, x, axis=0)
    m = np.abs(low).mean(1)
    fa = np.exp(-1.0/(0.003*SR)); sa = np.exp(-1.0/(0.060*SR))
    ef = np.sqrt(sig.lfilter([1-fa], [1, -fa], m**2)+1e-12)
    es = np.sqrt(sig.lfilter([1-sa], [1, -sa], m**2)+1e-12)
    d = 20*np.log10(ef+1e-9)-20*np.log10(es+1e-9)
    g = 1.0 + np.clip(d, 0, 8.0)/8.0*(10**(boost_db/20)-1.0)
    a = np.exp(-1.0/(0.004*SR)); g = sig.lfilter([1-a], [1, -a], g)
    return x + low*(g[:, None]-1.0)

def dyn_eq(x):
    def duck(sig_in, lo, hi, thr_pct, ratio, atk, rel, red_max):
        sc = sig.sosfilt(sig.butter(4, [lo/(SR/2), hi/(SR/2)], btype="band", output="sos"), sig_in.mean(1))
        k = int(0.010*SR); e = np.sqrt(np.convolve(sc**2, np.ones(k)/k, mode="same"))
        edb = 20*np.log10(e+1e-9); thr = np.percentile(edb, thr_pct)
        over = np.maximum(edb-thr, 0.0); gr = -np.minimum(over*(1-1/ratio), red_max)
        aA = np.exp(-1.0/(atk*SR)); aR = np.exp(-1.0/(rel*SR))
        out = np.zeros_like(gr); prev = 0.0
        for i, v in enumerate(gr):
            c = aA if v < prev else aR; prev = c*prev+(1-c)*v; out[i] = prev
        band = sig.sosfilt(sig.butter(2, [lo/(SR/2), hi/(SR/2)], btype="band", output="sos"), sig_in, axis=0)
        return sig_in + band*(10**(out/20)[:, None]-1.0)
    x = duck(x, 55, 110, 82, 3.0, 0.006, 0.14, 3.0)
    x = duck(x, 2800, 4500, 88, 2.5, 0.004, 0.10, 2.5)
    return x

def tape_sat(x, drive=0.9, even=0.10, wet=0.16):
    d = x*drive
    shaped = np.tanh(d + even*d*d) / np.tanh(1.0+even)
    y = (1-wet)*x + wet*shaped
    ri = rms(x); ro = rms(y)
    return y*(ri/ro) if ro > 0 else y

def widen_highs(x, f=9000.0, amount=1.30):
    hp = sig.butter(2, f/(SR/2), btype="high", output="sos")
    mid = (x[:, 0]+x[:, 1])*0.5; side = (x[:, 0]-x[:, 1])*0.5
    side_hi = sig.sosfilt(hp, side); side_lo = side - side_hi
    side2 = side_lo + side_hi*amount
    return np.stack([mid+side2, mid-side2], 1)

def matchering_avg(premaster_wav, tag):
    outs = []
    for nm, rp in REFS.items():
        op = os.path.join(WORK, f"{tag}_mg_{nm}.wav")
        try:
            mg.process(target=premaster_wav, reference=rp, results=[mg.pcm24(op)])
            if os.path.exists(op): outs.append(load(op))
        except Exception as e:
            L(f"    matchering {nm} FALLO: {e}")
        finally:
            try: os.remove(op)
            except Exception: pass
    if not outs:
        return load(premaster_wav)
    m = min(len(a) for a in outs)
    L(f"    matchering: averaged {len(outs)}/{len(REFS)} refs")
    return np.mean([a[:m] for a in outs], axis=0)

# ================== VOCAL PRO ==================
L(f"=== track_v2: {NAME}  (tag={TAG}) ===")
if not (os.path.exists(VC) and os.path.exists(IC)):
    L("NO STEMS -> abort"); sys.exit(1)
voc = load(VC); n = len(voc); r0 = rms(voc)
voc = deepfilter(voc, n)
voc, nb  = debreath_at(voc, n, at_db=-9.0)
voc, npl = deplosive_gated(voc, n)
voc = dereverb(voc)
voc = eq_sub(voc)
voc = vbus(voc)
VOX = voc.copy()
L(f"vocal pro: breath={nb} plos={npl}")

def w(tmp, arr): sf.write(tmp, arr.astype(np.float32), SR, subtype="PCM_24"); return tmp

from acap_pro import bq_shelf   # shelf de graves fijo post-matchering
from acap_pro import bq_peak    # peak de presencia opcional (argv[7])

# 1) MASTER
oM = os.path.join(OUT, PFX + "MASTER.wav")
inst = transient_shape(load(IC))
vmix = VOX*(r0/rms(VOX))*10**(1.0/20)
vmix = 0.6*plate(vmix) + 0.4*vmix
mm = min(len(vmix), len(inst)); mix = glue(vmix[:mm] + inst[:mm])
mix = polish(mix); mix = dyn_eq(mix); mix = tape_sat(mix, wet=0.16); mix = widen_highs(mix, 9000, 1.30)
pk = np.max(np.abs(mix)); mix = mix*(0.99/pk) if pk > 0.99 else mix
pB = libmaster(w(os.path.join(WORK, "tv_m0.wav"), mix), os.path.join(WORK, "tv_m1.wav"))
y = bbmatch(load(pB)); pk = np.max(np.abs(y)); y = y*(0.995/pk) if pk > 0.995 else y
y = matchering_avg(w(os.path.join(WORK, "tv_m2.wav"), y), "tv")
y = bq_shelf(y, 75.0, SHELF_DB, False)      # low-shelf 60-90 Hz (default +1.5, override por argv[4])
if AIR_DB != 0.0: y = bq_shelf(y, 9000.0, AIR_DB, True)   # high-shelf de aire (override por argv[5])
if PRES_DB != 0.0: y = bq_peak(y, 3500.0, PRES_DB, 0.7)   # peak de presencia 2-6 kHz (override por argv[7])
if NARROW > 0.0: y = mono_narrow(y, NARROW)               # estrecha el master hacia corr objetivo (override por argv[6])
if WIDEN > 1.0 and y.ndim == 2 and y.shape[1] == 2:       # ensancha via M/S (override por argv[8])
    _mid = (y[:, 0] + y[:, 1]) * 0.5; _side = (y[:, 0] - y[:, 1]) * 0.5 * WIDEN
    y = np.stack([_mid + _side, _mid - _side], 1)
    _pk = np.max(np.abs(y)); y = y * (0.995 / _pk) if _pk > 0.995 else y
pk = np.max(np.abs(y)); y = y*(0.995/pk) if pk > 0.995 else y
loud_to(w(os.path.join(WORK, "tv_m3.wav"), y), oM, Itgt=-9.3, tp_lin=0.871, drive=0.87)
Im, Lm, Tm = ebur(oM); L(f"[1] MASTER       I={Im:6.1f} LRA={Lm:4.1f} TP={Tm:5.1f} corr{corr_of(oM):+.2f}")

# 2) INSTRUMENTAL
oI = os.path.join(OUT, PFX + "INSTRUMENTAL.wav")
inst = glue(transient_shape(load(IC), boost_db=2.5))   # menos boost -> menos crest
pk = np.max(np.abs(inst)); inst = inst*(0.99/pk) if pk > 0.99 else inst
pB = libmaster(w(os.path.join(WORK, "tv_i0.wav"), inst), os.path.join(WORK, "tv_i1.wav"))
y = mono_narrow(polish(load(pB)), 0.82)                 # estrecha ANTES de limitar -> mas headroom
y = bq_shelf(y, 75.0, SHELF_DB, False)                  # mismo shelf de graves que el master
y = np.tanh(y*1.6)/np.tanh(1.6)                         # soft-clip suave: raspa picos, sube RMS alcanzable
pk = np.max(np.abs(y)); y = y*(0.995/pk) if pk > 0.995 else y
loud_to(w(os.path.join(WORK, "tv_i2.wav"), y), oI, Itgt=-9.3, tp_lin=0.871, drive=0.87)
Ii, Li, Ti = ebur(oI); L(f"[2] INSTRUMENTAL I={Ii:6.1f} LRA={Li:4.1f} TP={Ti:5.1f} corr{corr_of(oI):+.2f}")

# 3) ACAPELLA
oA = os.path.join(OUT, PFX + "ACAPELLA.wav")
va = plate(VOX); rr = rms(va); va = va*(r0/rr) if rr > 0 else va
pk = np.max(np.abs(va)); va = va*(0.98/pk) if pk > 0.98 else va
loud_to(w(os.path.join(WORK, "tv_a0.wav"), va), oA, Itgt=-12.0, tp_lin=0.891, drive=0.89)
Ia, La, Ta = ebur(oA); L(f"[3] ACAPELLA     I={Ia:6.1f} LRA={La:4.1f} TP={Ta:5.1f}")

# 4) APPLE
oP = os.path.join(OUT, PFX + "APPLE DIGITAL MASTER.wav")
arr = load(oM)
_, l0, _ = ebur(w(os.path.join(WORK, "tv_p0.wav"), arr)); l0 = l0 or 4.0
arr = slow_expand(arr, ratio=1.45 if l0 < 8.0 else 1.20); arr = mix_punch(arr, amount=2.2)
pk = np.max(np.abs(arr)); arr = arr*(0.995/pk) if pk > 0.995 else arr
loud_to(w(os.path.join(WORK, "tv_p1.wav"), arr), oP, Itgt=-12.0, tp_lin=0.891, drive=0.93)
Ip, Lp, Tp = ebur(oP); L(f"[4] APPLE        I={Ip:6.1f} LRA={Lp:4.1f} TP={Tp:5.1f}")

for f in os.listdir(WORK):
    if f.startswith("tv_"):
        try: os.remove(os.path.join(WORK, f))
        except Exception: pass

# ================== COMPARISON vs REFS ==================
def profile(p):
    I, Lr, T = ebur(p); lo, pr, air, corr = bands_arr(load(p))
    return dict(I=I, LRA=Lr, TP=T, low=lo, pres=pr, air=air, corr=corr)

L("\n--- COMPARISON (band dB rel. 200-2k) ---")
L(f"{'':24} {'I':>7} {'LRA':>6} {'TP':>6} {'low':>7} {'pres':>7} {'air':>7} {'corr':>6}")
rows = [("MASTER V2", oM), ("APPLE V2", oP)] + [(f"REF {k}", v) for k, v in REFS.items()]
P = {}
for nm, pth in rows:
    d = profile(pth); P[nm] = d
    L(f"{nm:24} {d['I']:7.1f} {d['LRA']:6.1f} {d['TP']:6.1f} {d['low']:7.1f} {d['pres']:7.1f} {d['air']:7.1f} {d['corr']:6.2f}")
rp = [P[f"REF {k}"] for k in REFS]
mean = {k: float(np.mean([r[k] for r in rp])) for k in ("I", "LRA", "TP", "low", "pres", "air", "corr")}
mv = P["MASTER V2"]
L(f"\nMASTER V2 vs MEAN refs:  low {mv['low']-mean['low']:+.1f}  pres {mv['pres']-mean['pres']:+.1f}  "
  f"air {mv['air']-mean['air']:+.1f}  I {mv['I']-mean['I']:+.1f}  corr {mv['corr']-mean['corr']:+.2f}")
chk = [
    ("loudness >= ref min",  mv['I'] >= min(r['I'] for r in rp)-0.5),
    ("true-peak <= -1.0",    mv['TP'] <= -1.0),
    ("low  +-1.5 dB",        abs(mv['low']-mean['low']) <= 1.5),
    ("pres +-1.5 dB",        abs(mv['pres']-mean['pres']) <= 1.5),
    ("air  +-1.5 dB",        abs(mv['air']-mean['air']) <= 1.5),
    ("stereo in range",      min(r['corr'] for r in rp)-0.03 <= mv['corr'] <= max(r['corr'] for r in rp)+0.03),
]
L("\n--- VERDICT ---")
ok = 0
for nm, g in chk:
    ok += g; L(f"  [{'OK ' if g else 'XX '}] {nm}")
L(f"\n{ok}/6 axes match or beat the {len(REFS)} refs.")
L("DONE track_v2")
for f in sorted(os.listdir(OUT)):
    L(f"  {f}  ({os.path.getsize(os.path.join(OUT, f))//1024} KB)")
