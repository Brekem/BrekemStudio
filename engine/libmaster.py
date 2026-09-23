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
"""Fast, conservative master to the 3-ref composite curve.
Usage: python libmaster.py "<input>" "<stage1_out>"
Then caller runs ONE ffmpeg loudnorm pass for loudness + true-peak.
Steps: L/R balance -> composite match EQ (50%, gentle sub) -> partial widen.
No compression/limiting here (ffmpeg loudnorm does peak control).
"""
import sys, os, numpy as np, soundfile as sf, scipy.signal as sig
import pyloudnorm as pyln

SR = 48000
SP = _HOME
INP, OUT = sys.argv[1], sys.argv[2]
REFS = _reflist()
def load(p, sr=SR):
    x, s = sf.read(p, dtype="float64", always_2d=True)
    if x.shape[1] == 1: x = np.repeat(x, 2, 1)
    if s != sr:
        g = np.gcd(int(s), sr); x = sig.resample_poly(x, sr//g, s//g, axis=0)
    return x
def setL(x, t):
    v = pyln.Meter(SR).integrated_loudness(x)
    return x*10**((t-v)/20) if np.isfinite(v) else x
def spec(x, n=8192):
    m = x.mean(1)[::4]                        # decimate for a fast broad curve
    f, p = sig.welch(m, SR/4, nperseg=n, noverlap=n//2, scaling="spectrum")
    return f, 10*np.log10(p+1e-20)
def osm(f, d, fr=1/6):
    o = d.copy()
    for i, fc in enumerate(f):
        if fc <= 0: continue
        k = (f >= fc*2**-fr) & (f <= fc*2**fr)
        if k.any(): o[i] = d[k].mean()
    return o
def smr(z):
    md=(z[:,0]+z[:,1])/2; sd=(z[:,0]-z[:,1])/2
    return np.sqrt(np.mean(sd**2))/(np.sqrt(np.mean(md**2))+1e-12)

# ---- composite curve (cached; curve only spans 0..SR/8 due to decimation) ----
CC = os.path.join(_WORK, "composite_curve_cache2.npz")
if os.path.exists(CC):
    z = np.load(CC); F, comp, RSM = z["F"], z["comp"], float(z["rsm"])
else:
    cs, sms = [], []
    for r in REFS:
        rx = load(r); a = np.abs(rx).mean(1); k = np.where(a > a.max()*0.02)[0]
        rx = setL(rx[k[0]:k[-1]+1], -12.0); f, d = spec(rx); cs.append(osm(f, d)); sms.append(smr(rx))
    F = f; comp = np.mean(cs, 0)
    low=(F>=20)&(F<=160); comp[low]-=np.interp(F[low],[20,60,160],[1.5,3.0,2.0])
    comp[(F>=200)&(F<=450)]-=1.5
    comp = osm(F, comp, 1/8)
    RSM = float(np.mean(sms))
    np.savez(CC, F=F, comp=comp, rsm=RSM)

# ---- process ----
x = load(INP)
lr = np.sqrt(np.mean(x[:,0]**2)); rr = np.sqrt(np.mean(x[:,1]**2)); bal = 0.0
if lr > 0 and rr > 0 and abs(20*np.log10(lr/rr)) > 0.15:
    g = np.sqrt(lr/rr); x[:,0] /= g; x[:,1] *= g; bal = 20*np.log10(1/g)

f2, s0 = spec(x); src = osm(f2, s0)
delta = np.clip((comp - np.interp(F, f2, src)) * 0.50, -6, 6)
delta[F < 150] = np.clip(delta[F < 150], -2.5, 2.5)
nf = 8192
fg = np.linspace(0, SR/2, nf//2+1)
gdb = np.interp(fg, F, delta, left=0, right=0); gdb[fg < 25] = 0.0
h = np.fft.irfft(10**(gdb/20), n=nf); h = np.roll(h, nf//2); h *= sig.windows.blackmanharris(nf)
y = np.stack([sig.fftconvolve(x[:,c], h, mode="same") for c in range(2)], axis=1)

md = (y[:,0]+y[:,1])/2; sd = (y[:,0]-y[:,1])/2
cur = np.sqrt(np.mean(sd**2))/(np.sqrt(np.mean(md**2))+1e-12)
w = float(np.clip(np.sqrt(RSM/(cur+1e-12)), 0.9, 2.2))
sos = sig.butter(2, 90/(SR/2), btype="high", output="sos")
sd = sig.sosfilt(sos, sd)*(w-1) + sd
y = np.stack([md+sd, md-sd], axis=1)
nsm = 20*np.log10(smr(y))

pk = np.max(np.abs(y))
if pk > 0.99: y *= 0.99/pk
sf.write(OUT, y.astype(np.float32), SR, subtype="PCM_24")
print(f"  {os.path.basename(INP)}: bal {bal:+.2f}dB  widen x{w:.2f} (S/M {nsm:+.1f}dB)  peak {20*np.log10(np.max(np.abs(y))):+.2f} dBFS")
