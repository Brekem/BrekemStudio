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
"""Cadena V2 para un tema con STEMS REALES del DAW (mezcla + instrumental + voz).
Fuente dual-mono -> se sintetiza ancho estereo (mono-compatible).
Genera MASTER / INSTRUMENTAL / ACAPELLA / APPLE + FLAC + MP3 + comparativa vs 3 refs.
"""
import os, sys, warnings, subprocess, numpy as np, soundfile as sf, scipy.signal as sig
warnings.filterwarnings("ignore")

SP = _HOME
import acap_pro as AP
from acap_pro import (SR, load, rms, run, ebur, bands_arr, vbus, glue, polish,
                      bbmatch, kweight, WORK, debreath_at, eq_sub, plate, loud_to,
                      bq_shelf, bq_peak)
import matchering as mg
try: mg.log(info_handler=lambda *a, **k: None, warning_handler=lambda *a, **k: None)
except Exception: pass

MIXP  = sys.argv[1]     # mezcla completa
INSTP = sys.argv[2]     # instrumental (mezcla con voz en mute)
VOXP  = sys.argv[3]     # voz (lider, o lider+coros ya sumados) tal cual en la mezcla
OUT   = sys.argv[4]
SHELF_DB = float(sys.argv[5]) if len(sys.argv) > 5 else 1.5
AIR_DB   = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
PRES_DB  = float(sys.argv[7]) if len(sys.argv) > 7 else 0.0
CORR_M   = float(sys.argv[8]) if len(sys.argv) > 8 else 0.80   # corr objetivo del master
NARROW_M = float(sys.argv[9]) if len(sys.argv) > 9 else 0.0     # estrecha el master DESPUES del matchering (0=off)
os.makedirs(OUT, exist_ok=True)

LOG = os.path.join(SP, "daw_song.log")
def L(m): open(LOG, "a", encoding="utf-8").write(str(m) + "\n"); print(m, flush=True)
def w(tmp, arr): sf.write(tmp, np.asarray(arr, np.float32), SR, subtype="PCM_24"); return tmp

REFS = _refdict()
def corr_of_arr(z):
    a, b = z[:, 0], z[:, 1]
    return float(np.sum(a*b)/(np.sqrt(np.sum(a**2)*np.sum(b**2))+1e-12))
def corr_of(p): return corr_of_arr(load(p))

def libmaster(pin, pout):
    if os.path.exists(pout): os.remove(pout)
    run([_PYEXE, os.path.join(_HOME, "libmaster.py"), pin, pout])
    return pout if os.path.exists(pout) else pin

def transient_shape(x, band_hi=170.0, boost_db=3.0):
    low = sig.sosfilt(sig.butter(3, band_hi/(SR/2), btype="low", output="sos"), x, axis=0)
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
    ri, ro = rms(x), rms(y)
    return y*(ri/ro) if ro > 0 else y

def widen_highs(x, f=9000.0, amount=1.30):
    hp = sig.butter(2, f/(SR/2), btype="high", output="sos")
    mid = (x[:, 0]+x[:, 1])*0.5; side = (x[:, 0]-x[:, 1])*0.5
    side_hi = sig.sosfilt(hp, side); side_lo = side - side_hi
    side2 = side_lo + side_hi*amount
    return np.stack([mid+side2, mid-side2], 1)

def _schroeder_ap(x, delay, g):
    b = np.zeros(delay + 1); b[0] = -g; b[delay] = 1.0
    a = np.zeros(delay + 1); a[0] = 1.0; a[delay] = -g
    return sig.lfilter(b, a, x)

def stereoize(x, corr_target=0.80, mono_hz=110.0):
    """Fuente (dual-)mono -> ancho. <mono_hz al centro. L+R == 2*mono exacto
    (suma mono perfecta). El side es un difusor allpass decorrelado del centro.
    Busca k por biseccion para clavar corr_target."""
    mono = x.mean(1).astype(np.float64)
    low = sig.sosfilt(sig.butter(4, mono_hz/(SR/2), btype="low", output="sos"), mono)
    hm = mono - low
    diff = hm.copy()
    for d, g in ((89, 0.70), (131, 0.65), (197, 0.60), (281, 0.55), (383, 0.50)):
        diff = _schroeder_ap(diff, d, g)
    diff *= 0.9 * (np.sqrt(np.mean(hm**2)) / (np.sqrt(np.mean(diff**2)) + 1e-12))
    base = low + hm
    def c_at(k):
        return corr_of_arr(np.stack([base + k*diff, base - k*diff], 1))
    if c_at(0.02) <= corr_target:
        k = 0.02
    else:
        klo, khi = 0.0, 3.0
        while c_at(khi) > corr_target and khi < 12.0:
            khi *= 1.6
        k = khi
        for _ in range(40):
            mid = 0.5*(klo + khi); c = c_at(mid)
            if abs(c - corr_target) < 0.008:
                k = mid; break
            if c > corr_target: klo = mid
            else: khi = mid
            k = mid
    y = np.stack([base + k*diff, base - k*diff], 1)
    pk = np.max(np.abs(y))
    return y*(0.99/pk) if pk > 0.99 else y

def width_post(x, corr_target):
    """Ajusta el ancho de una senal YA estereo escalando el side, por biseccion
    (k<1 estrecha / k>1 ensancha). matchering/libmaster re-imponen su propio
    ancho, asi que este paso se aplica DESPUES de esa cadena, sobre la senal
    final, para clavar corr_target con precision en cualquier direccion."""
    mid = (x[:, 0] + x[:, 1]) * 0.5
    side = (x[:, 0] - x[:, 1]) * 0.5
    def c_at(k):
        return corr_of_arr(np.stack([mid + k*side, mid - k*side], 1))
    c1 = c_at(1.0)
    if abs(c1 - corr_target) < 0.006:
        return x
    if c1 > corr_target:
        klo, khi = 1.0, 2.0
        while c_at(khi) > corr_target and khi < 10.0:
            khi *= 1.6
    else:
        klo, khi = 0.0, 1.0
    k = 1.0
    for _ in range(40):
        mid_k = 0.5*(klo + khi); c = c_at(mid_k)
        if abs(c - corr_target) < 0.006:
            k = mid_k; break
        if c > corr_target: klo = mid_k
        else: khi = mid_k
        k = mid_k
    y = np.stack([mid + k*side, mid - k*side], 1)
    pk = np.max(np.abs(y))
    return y*(0.995/pk) if pk > 0.995 else y

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
    if not outs: return load(premaster_wav)
    m = min(len(a) for a in outs)
    L(f"    matchering: averaged {len(outs)}/{len(REFS)} refs")
    return np.mean([a[:m] for a in outs], axis=0)

def dcblock_hpf(x, hz=85.0):
    return sig.sosfilt(sig.butter(2, hz/(SR/2), btype="high", output="sos"), x, axis=0)

# ================== VOZ (stem real, limpia) ==================
L("=== daw_song: stems reales del DAW ===")
vraw = load(VOXP); r0 = rms(vraw); n = len(vraw)
voc = dcblock_hpf(vraw, 85.0)
voc, nb = debreath_at(voc, n, at_db=-9.0)
voc = eq_sub(voc)
voc = vbus(voc)
VOX = voc.copy()
L(f"voz: rms0={20*np.log10(r0+1e-12):.1f} dBFS  breath={nb}")

# nivel voz:instrumental tal como estaba en la mezcla original (para preservar el balance)
mixr = load(MIXP); instr = load(INSTP)
mm0 = min(len(mixr), len(instr), len(vraw))
ratio_db = 20*np.log10((rms(vraw[:mm0])+1e-12)/(rms(instr[:mm0])+1e-12))
L(f"balance original voz-instrumental: {ratio_db:+.1f} dB")

# ================== 1) MASTER ==================
oM = os.path.join(OUT, "MASTER.wav")
inst = transient_shape(load(INSTP), boost_db=3.0)
# recoloca la voz al balance original + ~1 dB para voz moderna al frente
vmix = VOX*(rms(inst)/ (rms(VOX)+1e-12)) * 10**((ratio_db+1.0)/20)
vmix = 0.62*plate(vmix) + 0.38*vmix
mm = min(len(vmix), len(inst)); mix = vmix[:mm] + inst[:mm]
mix = stereoize(mix, corr_target=CORR_M)
mix = glue(mix); mix = polish(mix); mix = dyn_eq(mix)
mix = tape_sat(mix, wet=0.16); mix = widen_highs(mix, 9000, 1.28)
pk = np.max(np.abs(mix)); mix = mix*(0.99/pk) if pk > 0.99 else mix
pB = libmaster(w(os.path.join(WORK, "ds_m0.wav"), mix), os.path.join(WORK, "ds_m1.wav"))
y = bbmatch(load(pB)); pk = np.max(np.abs(y)); y = y*(0.995/pk) if pk > 0.995 else y
y = matchering_avg(w(os.path.join(WORK, "ds_m2.wav"), y), "ds")
y = bq_shelf(y, 75.0, SHELF_DB, False)
if AIR_DB != 0.0:  y = bq_shelf(y, 9000.0, AIR_DB, True)
if PRES_DB != 0.0: y = bq_peak(y, 3500.0, PRES_DB, 0.7)
if NARROW_M > 0.0: y = width_post(y, NARROW_M)
pk = np.max(np.abs(y)); y = y*(0.995/pk) if pk > 0.995 else y
loud_to(w(os.path.join(WORK, "ds_m3.wav"), y), oM, Itgt=-9.3, tp_lin=0.871, drive=0.87)
Im, Lm, Tm = ebur(oM); L(f"[1] MASTER       I={Im:6.1f} LRA={Lm:4.1f} TP={Tm:5.1f} corr{corr_of(oM):+.2f}")

# ================== 2) INSTRUMENTAL ==================
oI = os.path.join(OUT, "INSTRUMENTAL.wav")
inst2 = transient_shape(load(INSTP), boost_db=2.5)
inst2 = stereoize(inst2, corr_target=0.90)
inst2 = glue(inst2)
pk = np.max(np.abs(inst2)); inst2 = inst2*(0.99/pk) if pk > 0.99 else inst2
pB = libmaster(w(os.path.join(WORK, "ds_i0.wav"), inst2), os.path.join(WORK, "ds_i1.wav"))
y = polish(load(pB))
y = bq_shelf(y, 75.0, SHELF_DB, False)
y = np.tanh(y*1.6)/np.tanh(1.6)
pk = np.max(np.abs(y)); y = y*(0.995/pk) if pk > 0.995 else y
loud_to(w(os.path.join(WORK, "ds_i2.wav"), y), oI, Itgt=-9.3, tp_lin=0.871, drive=0.87)
Ii, Li, Ti = ebur(oI); L(f"[2] INSTRUMENTAL I={Ii:6.1f} LRA={Li:4.1f} TP={Ti:5.1f} corr{corr_of(oI):+.2f}")

# ================== 3) ACAPELLA ==================
oA = os.path.join(OUT, "ACAPELLA.wav")
va = plate(VOX)
va = stereoize(va, corr_target=0.91, mono_hz=190.0)
rr = rms(va); va = va*(r0/rr) if rr > 0 else va
pk = np.max(np.abs(va)); va = va*(0.98/pk) if pk > 0.98 else va
loud_to(w(os.path.join(WORK, "ds_a0.wav"), va), oA, Itgt=-12.0, tp_lin=0.891, drive=0.89)
Ia, La, Ta = ebur(oA); L(f"[3] ACAPELLA     I={Ia:6.1f} LRA={La:4.1f} TP={Ta:5.1f} corr{corr_of(oA):+.2f}")

# ================== 4) APPLE DIGITAL MASTER ==================
oP = os.path.join(OUT, "APPLE DIGITAL MASTER.wav")
def mix_punch(x, amount=2.2):
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
    mono = x.mean(1); wv = int(1.0*SR); hop = int(0.25*SR); kw = kweight(mono); N = len(mono)
    env = np.array([10*np.log10(np.mean(kw[i:i+wv]**2)+1e-12) for i in range(0, max(1, N-wv), hop)])
    if len(env) < 8: return x
    centre = np.percentile(env, 60)
    g = np.clip((env-centre)*(ratio-1.0), lo, hi)
    fs_env = SR/hop
    g = sig.sosfiltfilt(sig.butter(2, 0.15/(fs_env/2), btype="low", output="sos"), g)
    tsamp = np.arange(N); tenv = np.arange(len(g))*hop + wv//2
    return x*(10**(np.interp(tsamp, tenv, g)/20.0))[:, None]
arr = load(oM)
_, l0, _ = ebur(w(os.path.join(WORK, "ds_p0.wav"), arr)); l0 = l0 or 4.0
arr = slow_expand(arr, ratio=1.45 if l0 < 8.0 else 1.20); arr = mix_punch(arr, amount=2.2)
pk = np.max(np.abs(arr)); arr = arr*(0.995/pk) if pk > 0.995 else arr
loud_to(w(os.path.join(WORK, "ds_p1.wav"), arr), oP, Itgt=-12.0, tp_lin=0.891, drive=0.93)
Ip, Lp, Tp = ebur(oP); L(f"[4] APPLE        I={Ip:6.1f} LRA={Lp:4.1f} TP={Tp:5.1f} corr{corr_of(oP):+.2f}")

for f in os.listdir(WORK):
    if f.startswith("ds_"):
        try: os.remove(os.path.join(WORK, f))
        except Exception: pass

# ================== FLAC + MP3 (MASTER y ADM) ==================
for kind in ("MASTER", "APPLE DIGITAL MASTER"):
    s = os.path.join(OUT, kind + ".wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", s, "-c:a", "flac",
                    "-compression_level", "8", os.path.join(OUT, kind + ".flac")], check=False)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", s, "-c:a", "libmp3lame",
                    "-b:a", "320k", "-id3v2_version", "3", os.path.join(OUT, kind + ".mp3")], check=False)

# ================== COMPARATIVA vs REFS ==================
def profile(p):
    I, Lr, T = ebur(p); lo, pr, air, corr = bands_arr(load(p))
    return dict(I=I, LRA=Lr, TP=T, low=lo, pres=pr, air=air, corr=corr)
L("\n--- COMPARISON (band dB rel. 200-2k) ---")
L(f"{'':24} {'I':>7} {'LRA':>6} {'TP':>6} {'low':>7} {'pres':>7} {'air':>7} {'corr':>6}")
rows = [("MASTER", oM), ("APPLE", oP)] + [(f"REF {k}", v) for k, v in REFS.items()]
P = {}
for nm, pth in rows:
    d = profile(pth); P[nm] = d
    L(f"{nm:24} {d['I']:7.1f} {d['LRA']:6.1f} {d['TP']:6.1f} {d['low']:7.1f} {d['pres']:7.1f} {d['air']:7.1f} {d['corr']:6.2f}")
rp = [P[f"REF {k}"] for k in REFS]
mean = {k: float(np.mean([r[k] for r in rp])) for k in ("I", "LRA", "TP", "low", "pres", "air", "corr")}
mv = P["MASTER"]
L(f"\nMASTER vs MEAN refs:  low {mv['low']-mean['low']:+.1f}  pres {mv['pres']-mean['pres']:+.1f}  "
  f"air {mv['air']-mean['air']:+.1f}  I {mv['I']-mean['I']:+.1f}  corr {mv['corr']-mean['corr']:+.2f}")
chk = [
    ("loudness >= ref min", mv['I'] >= min(r['I'] for r in rp)-0.5),
    ("true-peak <= -1.0",   mv['TP'] <= -1.0),
    ("low  +-1.5 dB",       abs(mv['low']-mean['low']) <= 1.5),
    ("pres +-1.5 dB",       abs(mv['pres']-mean['pres']) <= 1.5),
    ("air  +-1.5 dB",       abs(mv['air']-mean['air']) <= 1.5),
    ("stereo in range",     min(r['corr'] for r in rp)-0.03 <= mv['corr'] <= max(r['corr'] for r in rp)+0.03),
]
L("\n--- VERDICT ---")
ok = 0
for nm, g in chk:
    ok += g; L(f"  [{'OK ' if g else 'XX '}] {nm}")
L(f"\n{ok}/6 axes match or beat the 3 refs.")
for f in sorted(os.listdir(OUT)):
    fp = os.path.join(OUT, f)
    if os.path.isfile(fp): L(f"  {f}  ({os.path.getsize(fp)//1024} KB)")
L("LISTO daw_song")
