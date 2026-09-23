"""No-reference master from explicit mix / instrumental / vocal files
(the output of stemmix.py). Same idea as noref.py but not from the stems cache.
Usage:  noref_daw.py "<MIX>" "<INST>" "<VOX>" "<outdir>"
Outputs MASTER / INSTRUMENTAL / ACAPELLA / APPLE DIGITAL MASTER + absolute metrics.
"""
import os, sys, warnings, numpy as np, soundfile as sf, scipy.signal as sig
warnings.filterwarnings("ignore")

SP = os.environ.get("BREKEM_HOME") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP)
from acap_pro import (SR, load, rms, ebur, bands_arr, glue, polish, plate,
                      loud_to, bq_shelf, bq_peak, macro_expand, WORK)

MIXP, INSTP, VOXP, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(SP, "noref_daw.log")

def L(m):
    try: open(LOG, "a", encoding="utf-8").write(str(m) + "\n")
    except Exception: pass
    print(m, flush=True)

def w(tmp, arr):
    sf.write(tmp, np.asarray(arr, np.float32), SR, subtype="PCM_24"); return tmp

def mono_narrow(y, target=0.82):
    for CT in (0.72, 0.78, 0.83, 0.88, 0.93, 0.97):
        Lc, Rc = y[:, 0], y[:, 1]
        c0 = float(np.sum(Lc * Rc) / (np.sqrt(np.sum(Lc ** 2) * np.sum(Rc ** 2)) + 1e-12))
        if c0 >= target: return y
        k = float(np.clip(np.sqrt(((1 - CT) * (1 + c0)) / ((1 + CT) * (1 - c0) + 1e-12)), 0.12, 1.0))
        mid = (Lc + Rc) * 0.5; side = (Lc - Rc) * 0.5 * k
        y = np.stack([mid + side, mid - side], 1)
    return y

def self_deres(x):
    m = x.mean(1)
    f, P = sig.welch(m, SR, nperseg=8192)
    Pdb = 10 * np.log10(P + 1e-12)
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

mix = load(MIXP)
inst = load(INSTP)
vox = load(VOXP)

# ---- MASTER ----
oM = os.path.join(OUT, "MASTER.wav")
y = glue(polish(mix))
y = self_deres(y)
y = bq_shelf(y, 80.0, 1.0, False)
y = bq_shelf(y, 12000.0, 1.0, True)
_, lra0, _ = ebur(w(os.path.join(WORK, "nd_m0.wav"), y)); lra0 = lra0 or 6.0
if lra0 < 6.0:
    y = macro_expand(y, ratio=1.25 + (6.0 - lra0) * 0.22)
pk = np.max(np.abs(y)); y = y * (0.995 / pk) if pk > 0.995 else y
loud_to(w(os.path.join(WORK, "nd_m1.wav"), y), oM, Itgt=-9.5, tp_lin=0.891, drive=0.88)
Im, Lm, Tm = ebur(oM); L(f"[1] MASTER       I={Im:6.1f} LRA={Lm:4.1f} TP={Tm:5.1f}")

# ---- INSTRUMENTAL ----
oI = os.path.join(OUT, "INSTRUMENTAL.wav")
yi = mono_narrow(polish(inst), 0.82)
yi = bq_shelf(yi, 80.0, 1.0, False)
yi = np.tanh(yi * 1.5) / np.tanh(1.5)
pk = np.max(np.abs(yi)); yi = yi * (0.995 / pk) if pk > 0.995 else yi
loud_to(w(os.path.join(WORK, "nd_i1.wav"), yi), oI, Itgt=-9.5, tp_lin=0.891, drive=0.88)
Ii, Li, Ti = ebur(oI); L(f"[2] INSTRUMENTAL I={Ii:6.1f} LRA={Li:4.1f} TP={Ti:5.1f}")

# ---- ACAPELLA ----
oA = os.path.join(OUT, "ACAPELLA.wav")
va = plate(vox); pk = np.max(np.abs(va))
va = va * (0.98 / pk) if pk > 0.98 else va
loud_to(w(os.path.join(WORK, "nd_a0.wav"), va), oA, Itgt=-12.0, tp_lin=0.891, drive=0.89)
Ia, La, Ta = ebur(oA); L(f"[3] ACAPELLA     I={Ia:6.1f} LRA={La:4.1f} TP={Ta:5.1f}")

# ---- APPLE DIGITAL MASTER ----
oP = os.path.join(OUT, "APPLE DIGITAL MASTER.wav")
arr = load(oM)
_, l0, _ = ebur(w(os.path.join(WORK, "nd_p0.wav"), arr)); l0 = l0 or 4.0
if l0 < 8.0:
    arr = macro_expand(arr, ratio=1.30)
pk = np.max(np.abs(arr)); arr = arr * (0.995 / pk) if pk > 0.995 else arr
loud_to(w(os.path.join(WORK, "nd_p1.wav"), arr), oP, Itgt=-12.0, tp_lin=0.891, drive=0.93)
Ip, Lp, Tp = ebur(oP); L(f"[4] APPLE        I={Ip:6.1f} LRA={Lp:4.1f} TP={Tp:5.1f}")

for fn in os.listdir(WORK):
    if fn.startswith("nd_"):
        try: os.remove(os.path.join(WORK, fn))
        except Exception: pass

lo, pr, air, corr = bands_arr(load(oM))
L("\n--- METRICS (no references) ---")
L(f"  loudness {Im:6.1f} LUFS   true-peak {Tm:6.1f} dBTP   LRA {Lm:.1f}   corr {corr:+.2f}")
chk = [
    ("loudness in [-12,-8] LUFS", -12.5 <= Im <= -8.0),
    ("true-peak <= -1.0 dBTP",    Tm is not None and Tm <= -1.0),
    ("dynamics LRA >= 3",         Lm is not None and Lm >= 3.0),
    ("mono-compatible corr >= 0.4", corr >= 0.4),
]
L("\n--- VERDICT ---")
ok = sum(bool(g) for _, g in chk)
for nm, g in chk:
    L(f"  [{'OK ' if g else 'XX '}] {nm}")
L(f"\n{ok}/4 absolute targets met.")
L("DONE noref_daw")
