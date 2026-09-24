"""No-reference master: get the best out of the source itself, with no external
target. Self de-resonance, gentle sub/air, dynamics recovery, true-peak safe.
Usage:  noref.py "<name>" "<outdir>" ["<prefix>"]  (name only used to find the stems cache tag)
Outputs MASTER / INSTRUMENTAL / ACAPELLA / APPLE DIGITAL MASTER + absolute metrics.
"""
import os, sys, re, warnings, numpy as np, soundfile as sf, scipy.signal as sig
warnings.filterwarnings("ignore")

SP = os.environ.get("BREKEM_HOME") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP)
import acap_pro as AP
from acap_pro import (SR, load, rms, ebur, bands_arr, deepfilter, vbus, glue, polish,
                      kweight, WORK, STEMS, debreath_at, deplosive_gated, dereverb,
                      eq_sub, plate, loud_to, bq_shelf, bq_peak, macro_expand)
import stems as ST

NAME = sys.argv[1]
OUT  = sys.argv[2]
PFX  = sys.argv[3] if len(sys.argv) > 3 else ""
os.makedirs(OUT, exist_ok=True)
TAG  = re.sub(r"\s*master\.wav$", "", NAME).replace(" ", "_")[:60]
VC   = os.path.join(STEMS, TAG, "vocals.flac")
IC   = os.path.join(STEMS, TAG, "no_vocals.flac")
LOG  = os.path.join(SP, "noref.log")

def L(m):
    try: open(LOG, "a", encoding="utf-8").write(str(m) + "\n")
    except Exception: pass
    print(m, flush=True)

def w(tmp, arr):
    sf.write(tmp, np.asarray(arr, np.float32), SR, subtype="PCM_24"); return tmp

def transient_shape(x, band_hi=170.0, boost_db=3.0):
    low = sig.sosfilt(sig.butter(3, band_hi / (SR / 2), btype="low", output="sos"), x, axis=0)
    m = np.abs(low).mean(1)
    fa = np.exp(-1.0 / (0.003 * SR)); sa = np.exp(-1.0 / (0.060 * SR))
    ef = np.sqrt(sig.lfilter([1 - fa], [1, -fa], m ** 2) + 1e-12)
    es = np.sqrt(sig.lfilter([1 - sa], [1, -sa], m ** 2) + 1e-12)
    d = 20 * np.log10(ef + 1e-9) - 20 * np.log10(es + 1e-9)
    g = 1.0 + np.clip(d, 0, 8.0) / 8.0 * (10 ** (boost_db / 20) - 1.0)
    a = np.exp(-1.0 / (0.004 * SR)); g = sig.lfilter([1 - a], [1, -a], g)
    return x + low * (g[:, None] - 1.0)

def mono_narrow(y, target=0.80):
    for CT in (0.72, 0.78, 0.83, 0.88, 0.93, 0.97):
        Lc, Rc = y[:, 0], y[:, 1]
        c0 = float(np.sum(Lc * Rc) / (np.sqrt(np.sum(Lc ** 2) * np.sum(Rc ** 2)) + 1e-12))
        if c0 >= target: return y
        k = float(np.clip(np.sqrt(((1 - CT) * (1 + c0)) / ((1 + CT) * (1 - c0) + 1e-12)), 0.12, 1.0))
        mid = (Lc + Rc) * 0.5; side = (Lc - Rc) * 0.5 * k
        y = np.stack([mid + side, mid - side], 1)
    return y

def self_deres(x):
    """pull down the two worst resonances vs the track's own broad spectral trend."""
    m = x.mean(1)
    f, P = sig.welch(m, SR, nperseg=8192)
    Pdb = 10 * np.log10(P + 1e-12)
    # 1-octave running mean as the 'trend'
    trend = Pdb.copy()
    for i, fc in enumerate(f):
        if fc <= 0: continue
        k = (f >= fc * 2 ** -0.5) & (f <= fc * 2 ** 0.5)
        if k.any(): trend[i] = Pdb[k].mean()
    excess = Pdb - trend
    band = (f >= 120) & (f <= 9000)
    y = x
    for _ in range(2):
        idx = np.where(band)[0]
        j = idx[np.argmax(excess[idx])]
        if excess[j] < 2.5: break
        y = bq_peak(y, float(f[j]), -float(np.clip(excess[j] * 0.7, 0, 3.5)), 3.0)
        excess[max(0, j - 3):j + 4] = 0.0
    return y

if not (os.path.exists(VC) and os.path.exists(IC)):
    L("NO STEMS -> abort"); sys.exit(1)

# ---- vocal pro (same cleaning chain as the reference master) ----
voc = load(VC); n = len(voc); r0 = rms(voc)
RAW = voc.copy()
VACT = ST.vocal_activity(RAW, load(IC))      # where the vocal stem really holds a vocal
voc = deepfilter(voc, n)
voc, nb = debreath_at(voc, n, at_db=-9.0)
voc, npl = deplosive_gated(voc, n)
voc = dereverb(voc)
voc = eq_sub(voc)
voc = vbus(voc)
VOX = voc.copy()
L(f"vocal pro: breath={nb} plos={npl}")

# ---- 1) MASTER ----
oM = os.path.join(OUT, PFX + "MASTER.wav")
inst = ST.instrumental(TAG, transient_shape, VACT, log=L)
vmix = ST.gate(VOX * (r0 / rms(VOX)) * 10 ** (1.0 / 20), VACT)
vmix = 0.6 * plate(vmix) + 0.4 * vmix + ST.bleed(RAW, VACT)
mm = min(len(vmix), len(inst))
mix = glue(vmix[:mm] + inst[:mm])
mix = polish(mix)                    # M/S low mono-fold + 280 Hz dip + de-harsh 6-8.5k
mix = self_deres(mix)               # own-trend de-resonance
mix = bq_shelf(mix, 80.0, 1.0, False)   # gentle sub lift
mix = bq_shelf(mix, 12000.0, 1.0, True) # gentle air
_, lra0, _ = ebur(w(os.path.join(WORK, "nr_m0.wav"), mix)); lra0 = lra0 or 6.0
if lra0 < 6.0:
    mix = macro_expand(mix, ratio=1.25 + (6.0 - lra0) * 0.22)   # recover crushed dynamics
pk = np.max(np.abs(mix)); mix = mix * (0.995 / pk) if pk > 0.995 else mix
loud_to(w(os.path.join(WORK, "nr_m1.wav"), mix), oM, Itgt=-9.5, tp_lin=0.891, drive=0.88)
Im, Lm, Tm = ebur(oM)
L(f"[1] MASTER       I={Im:6.1f} LRA={Lm:4.1f} TP={Tm:5.1f}")

# ---- 2) INSTRUMENTAL ----
oI = os.path.join(OUT, PFX + "INSTRUMENTAL.wav")
y = glue(ST.instrumental(TAG, lambda x: transient_shape(x, boost_db=2.5), log=L))
y = mono_narrow(polish(y), 0.82)
y = bq_shelf(y, 80.0, 1.0, False)
y = np.tanh(y * 1.5) / np.tanh(1.5)
pk = np.max(np.abs(y)); y = y * (0.995 / pk) if pk > 0.995 else y
loud_to(w(os.path.join(WORK, "nr_i1.wav"), y), oI, Itgt=-9.5, tp_lin=0.891, drive=0.88)
Ii, Li, Ti = ebur(oI)
L(f"[2] INSTRUMENTAL I={Ii:6.1f} LRA={Li:4.1f} TP={Ti:5.1f}")

# ---- 3) ACAPELLA ----
oA = os.path.join(OUT, PFX + "ACAPELLA.wav")
va = plate(ST.gate(VOX, VACT)); rr = rms(va)
va = va * (r0 / rr) if rr > 0 else va
pk = np.max(np.abs(va)); va = va * (0.98 / pk) if pk > 0.98 else va
loud_to(w(os.path.join(WORK, "nr_a0.wav"), va), oA, Itgt=-12.0, tp_lin=0.891, drive=0.89)
Ia, La, Ta = ebur(oA)
L(f"[3] ACAPELLA     I={Ia:6.1f} LRA={La:4.1f} TP={Ta:5.1f}")

# ---- 4) APPLE DIGITAL MASTER ----
oP = os.path.join(OUT, PFX + "APPLE DIGITAL MASTER.wav")
arr = load(oM)
_, l0, _ = ebur(w(os.path.join(WORK, "nr_p0.wav"), arr)); l0 = l0 or 4.0
if l0 < 8.0:
    arr = macro_expand(arr, ratio=1.30)
pk = np.max(np.abs(arr)); arr = arr * (0.995 / pk) if pk > 0.995 else arr
loud_to(w(os.path.join(WORK, "nr_p1.wav"), arr), oP, Itgt=-12.0, tp_lin=0.891, drive=0.93)
Ip, Lp, Tp = ebur(oP)
L(f"[4] APPLE        I={Ip:6.1f} LRA={Lp:4.1f} TP={Tp:5.1f}")

for f in os.listdir(WORK):
    if f.startswith("nr_"):
        try: os.remove(os.path.join(WORK, f))
        except Exception: pass

# ---- absolute checks (no references) ----
lo, pr, air, corr = bands_arr(load(oM))
L("\n--- METRICS (no references) ---")
L(f"  loudness   {Im:6.1f} LUFS")
L(f"  true-peak  {Tm:6.1f} dBTP")
L(f"  dynamics   LRA {Lm:.1f}")
L(f"  stereo     corr {corr:+.2f}")
L(f"  low/pres/air  {lo:+.1f} / {pr:+.1f} / {air:+.1f}  dB rel. 200-2k")
chk = [
    ("loudness in [-12,-8] LUFS", -12.5 <= Im <= -8.0),
    ("true-peak <= -1.0 dBTP",    Tm is not None and Tm <= -1.0),
    ("dynamics LRA >= 3",         Lm is not None and Lm >= 3.0),
    ("mono-compatible corr >= 0.4", corr >= 0.4),
]
L("\n--- VERDICT ---")
ok = 0
for nm, g in chk:
    ok += bool(g); L(f"  [{'OK ' if g else 'XX '}] {nm}")
L(f"\n{ok}/4 absolute targets met.")
L("DONE noref")
for fn in sorted(os.listdir(OUT)):
    L(f"  {fn}  ({os.path.getsize(os.path.join(OUT, fn)) // 1024} KB)")
