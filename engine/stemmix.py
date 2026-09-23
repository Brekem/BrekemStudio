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
"""Mezcla automatica desde stems (Suno o DAW) -> produce los 3 inputs de daw_song.py
Uso:  python stemmix.py <stemdir> <voxfile> <outdir> [vox_offset_lufs=-3.0]
Escribe en outdir:  INSTRUMENTAL_premix.wav  VOX_premix.wav  MIX_premix.wav
Deteccion de stems por nombre de archivo (cualquier subconjunto):
  *drum* *bass* *guitar* *keyboard*/*keys* *string* *synth* *other* *pad* *perc* *fx*
Stems no reconocidos van a la cadena 'otros'.
"""
import sys, os, glob, numpy as np, soundfile as sf, scipy.signal as sig
import pyloudnorm as pyln
from pedalboard import (Pedalboard, Compressor, Gain, HighpassFilter, LowpassFilter,
                        LowShelfFilter, HighShelfFilter, PeakFilter, Reverb, Distortion)

SP = _HOME
sys.path.insert(0, SP)
from acap_pro import deepfilter, deplosive_gated, dereverb   # limpieza de voz

SR = 48000
STEMDIR = sys.argv[1]
VOXFILE = sys.argv[2]
OUTDIR  = sys.argv[3]
VOX_OFFSET = float(sys.argv[4]) if len(sys.argv) > 4 else -3.0
os.makedirs(OUTDIR, exist_ok=True)

def load(path, sr=SR):
    x, s = sf.read(path, dtype="float64", always_2d=True)
    if x.shape[1] == 1: x = np.repeat(x, 2, 1)
    if s != sr:
        g = np.gcd(int(s), sr); x = sig.resample_poly(x, sr//g, s//g, axis=0)
    return x

_M = pyln.Meter(SR)
def lufs(x):
    try: return _M.integrated_loudness(x)
    except Exception: return float("nan")
def set_lufs(x, tgt):
    l = lufs(x)
    return x * 10**((tgt - l)/20.0) if np.isfinite(l) else x
def pb(board, x):
    return board(x.T.astype(np.float32), SR).T.astype(np.float64)
def mono_fold_low(x, f=120.0):
    L, R = x[:, 0], x[:, 1]; mid = (L+R)/2.0; side = (L-R)/2.0
    side = sig.sosfilt(sig.butter(2, f/(SR/2), btype="high", output="sos"), side)
    return np.stack([mid+side, mid-side], 1)
def widen(x, amount=1.15, above=300.0):
    L, R = x[:, 0], x[:, 1]; mid = (L+R)/2.0; side = (L-R)/2.0
    side = sig.sosfilt(sig.butter(2, above/(SR/2), btype="high", output="sos"), side)*(amount-1.0) + side
    return np.stack([mid+side, mid-side], 1)

# ---------------------------------------------------------------- clasificar stems
TAGS = {
    "drums":    ["drum", "bater", "kick", "snare", "hat", "perc"],
    "bass":     ["bass", "808", "sub", "bajo"],
    "guitar":   ["guitar", "guitarra", "gtr"],
    "keys":     ["keyboard", "keys", "piano", "rhodes", "teclado"],
    "strings":  ["string", "cuerda", "orchestr"],
    "synth":    ["synth", "lead", "arp"],
    "other":    ["other", "pad", "fx", "vox", "choir", "brass", "bell", "misc"],
}
def classify(fn):
    b = os.path.basename(fn).lower()
    for cat, keys in TAGS.items():
        if any(k in b for k in keys): return cat
    return "other"

files = sorted(glob.glob(os.path.join(STEMDIR, "*.wav")))
if not files: raise SystemExit(f"no .wav en {STEMDIR}")
groups = {}
for f in files:
    groups.setdefault(classify(f), []).append(f)
print("stems:", {k: [os.path.basename(x) for x in v] for k, v in groups.items()}, flush=True)

def sum_group(cat):
    arrs = [load(f) for f in groups.get(cat, [])]
    if not arrs: return None
    n = min(len(a) for a in arrs)
    return np.sum([a[:n] for a in arrs], 0)

# ---------------------------------------------------------------- cadenas por grupo
proc = {}

d = sum_group("drums")
if d is not None:
    d = pb(Pedalboard([
        HighpassFilter(30),
        Compressor(threshold_db=-17, ratio=3.0, attack_ms=8, release_ms=120),
        PeakFilter(cutoff_frequency_hz=90, gain_db=+1.5, q=1.0),
        HighShelfFilter(cutoff_frequency_hz=8000, gain_db=+1.6, q=0.7),
    ]), d)
    proc["drums"] = set_lufs(d, -13.0)

b = sum_group("bass")
if b is not None:
    b = pb(Pedalboard([
        HighpassFilter(25), LowpassFilter(320),
        PeakFilter(cutoff_frequency_hz=70, gain_db=+1.5, q=0.8),
        Compressor(threshold_db=-22, ratio=3.5, attack_ms=15, release_ms=150),
        Distortion(drive_db=5.0), LowpassFilter(340),
    ]), b)
    b = mono_fold_low(b, 120.0)
    if "drums" in proc:
        env = np.abs(proc["drums"]).mean(1)
        env = sig.sosfilt(sig.butter(2, 30/(SR/2), output="sos"), env)
        env = env/(env.max()+1e-9)
        b = b * (1.0 - 0.16*env)[:, None]
    proc["bass"] = set_lufs(b, -13.5)

def tonal(cat, hp, demud_hz, demud_db, comp_thr, wamt, wabove, tgt):
    x = sum_group(cat)
    if x is None: return
    x = pb(Pedalboard([
        HighpassFilter(hp),
        PeakFilter(cutoff_frequency_hz=demud_hz, gain_db=demud_db, q=1.1),
        Compressor(threshold_db=comp_thr, ratio=2.0, attack_ms=25, release_ms=180),
        HighShelfFilter(cutoff_frequency_hz=9000, gain_db=+0.8, q=0.7),
    ]), x)
    x = widen(x, wamt, wabove)
    proc[cat] = set_lufs(x, tgt)

tonal("guitar",  90, 350, -1.5, -22, 1.16, 320, -18.5)
tonal("keys",    80, 320, -1.5, -22, 1.14, 320, -19.5)
tonal("strings", 130, 400, -1.0, -24, 1.22, 360, -20.5)
tonal("synth",   80, 340, -1.5, -22, 1.18, 320, -18.5)
tonal("other",   95, 350, -1.5, -22, 1.16, 300, -19.0)

# ---------------------------------------------------------------- bus instrumental
n = min(len(v) for v in proc.values())
inst = np.sum([v[:n] for v in proc.values()], 0)
pk = np.max(np.abs(inst))
if pk > 0.99: inst *= 0.99/pk
inst = pb(Pedalboard([
    Compressor(threshold_db=-15, ratio=2.0, attack_ms=30, release_ms=200),
    Distortion(drive_db=1.5),
]), inst)
inst = set_lufs(inst, -15.5)
pk = np.max(np.abs(inst))
if pk > 0.98: inst *= 0.98/pk
Li = lufs(inst)
print(f"instrumental bus: {Li:.2f} LUFS  peak {20*np.log10(np.max(np.abs(inst))):.2f} dBFS", flush=True)

# ---------------------------------------------------------------- voz limpia
vraw = load(VOXFILE); nv = len(vraw); r0 = np.sqrt(np.mean(vraw**2))
voc = deepfilter(vraw, nv)
voc, _ = deplosive_gated(voc, len(voc))
voc = dereverb(voc)
# renivela a su RMS original (la limpieza cambia el nivel)
rr = np.sqrt(np.mean(voc**2)); voc = voc * (r0/rr) if rr > 0 else voc
m = min(len(inst), len(voc))
inst, voc = inst[:m], voc[:m]
voc = set_lufs(voc, Li + VOX_OFFSET)
print(f"voz: {lufs(voc):.2f} LUFS  (offset {VOX_OFFSET:+.1f} vs instrumental)", flush=True)

# ---------------------------------------------------------------- salidas
mix = inst + voc
pk = np.max(np.abs(mix))
if pk > 0.98: mix *= 0.98/pk; inst *= 0.98/pk; voc *= 0.98/pk

sf.write(os.path.join(OUTDIR, "INSTRUMENTAL_premix.wav"), inst.astype(np.float32), SR, subtype="PCM_24")
sf.write(os.path.join(OUTDIR, "VOX_premix.wav"),          voc.astype(np.float32),  SR, subtype="PCM_24")
sf.write(os.path.join(OUTDIR, "MIX_premix.wav"),          mix.astype(np.float32),  SR, subtype="PCM_24")
print("LISTO stemmix ->", OUTDIR, flush=True)
