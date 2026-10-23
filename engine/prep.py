"""Separate one audio file into the stems cache the master engines consume.
Usage:  prep.py "<audio in>" "<TAG>" [model] [shifts]
  model   htdemucs_ft (default: 4 stems, best quality, ~4x slower)
          htdemucs_6s (6 stems: + guitar, piano)
          htdemucs    (4 stems, fast)
          (or env BREKEM_SEP)
  shifts  Demucs random-shift passes averaged (1 = off, 2 = cleaner, 2x time)
Writes: %BREKEM_STEMS%/<TAG>/{vocals,drums,bass,other[,guitar,piano]}.flac
        + no_vocals.flac (sum of every non-vocal stem) + stems.json
Skips when the cache already holds the same model's stems.
Prints: TAG=<tag> on success.
"""
import os, sys, json, glob, shutil, subprocess
import numpy as np
import soundfile as sf

HOME  = os.environ.get("BREKEM_HOME")  or os.path.dirname(os.path.abspath(__file__))
WORK  = os.environ.get("BREKEM_WORK")  or os.path.join(HOME, "_work")
STEMS = os.environ.get("BREKEM_STEMS") or os.path.join(HOME, "_stems")
PYEXE = os.environ.get("BREKEM_PY")    or sys.executable
os.makedirs(WORK, exist_ok=True); os.makedirs(STEMS, exist_ok=True)

MODELS = ("htdemucs_ft", "htdemucs_6s", "htdemucs")

def run(c): return subprocess.run(c, capture_output=True, text=True, encoding="utf-8", errors="replace")

SRCIN  = sys.argv[1]
TAG    = sys.argv[2]
MODEL  = (sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else
          os.environ.get("BREKEM_SEP", "htdemucs_ft"))
SHIFTS = int(sys.argv[4]) if len(sys.argv) > 4 else 1
if MODEL not in MODELS:
    print(f"unknown model {MODEL!r} -> htdemucs_ft"); MODEL = "htdemucs_ft"
sd    = os.path.join(STEMS, TAG)
vc    = os.path.join(sd, "vocals.flac")
ic    = os.path.join(sd, "no_vocals.flac")
meta  = os.path.join(sd, "stems.json")

def cached():
    try:
        with open(meta, encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        return False
    return (m.get("model") == MODEL and os.path.exists(vc) and os.path.exists(ic)
            and all(os.path.exists(os.path.join(sd, s + ".flac")) for s in m.get("stems", [])))

if cached():
    print(f"TAG={TAG}"); print(f"stems: cache hit ({MODEL})", flush=True); sys.exit(0)

os.makedirs(sd, exist_ok=True)
src = os.path.join(WORK, TAG + "_src.wav")
# decoded 6 dB down so no stem can hit Demucs' clip stage (undone below, in float)
PAD_DB = 6.0
r = run(["ffmpeg", "-hide_banner", "-y", "-i", SRCIN, "-af", f"volume=-{PAD_DB}dB",
         "-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le", src])
if not os.path.exists(src):
    print("ERROR: ffmpeg decode failed"); print(r.stderr[-800:]); sys.exit(2)

# the NVIDIA GPU when the app found a usable one (brekem_env.gpu sets BREKEM_CUDA), else the CPU
DEVICE = {"1": "cuda", "0": "cpu"}.get(os.environ.get("BREKEM_CUDA", ""))
# set for the batch's look-ahead separation of the next song: GPU or nothing (it must not
# take the CPU from the song being mastered); the song's own turn does the fallbacks
GPU_ONLY = os.environ.get("BREKEM_SEP_GPU_ONLY") == "1"
if GPU_ONLY and DEVICE != "cuda":
    try: os.remove(src)
    except Exception: pass
    print("no GPU -> this song is separated when its turn comes", flush=True)
    sys.exit(5)


def separate(model, device=DEVICE):
    """-> {stem: wav path} or None. float32 output + headroom so the stems still add
    up to the song (the old int16 + per-stem 'rescale' broke that)."""
    sep = os.path.join(WORK, "sep_" + TAG)
    shutil.rmtree(sep, ignore_errors=True)
    where = {"cuda": "on the GPU", "cpu": "on the CPU (this is the slow part)"}.get(device, "(this is the slow part)")
    print(f"demucs {model}: separating all stems {where}...", flush=True)
    r = run([PYEXE, "-m", "demucs", "-n", model, "--float32", "--clip-mode", "clamp",
             "--shifts", str(max(1, SHIFTS)), "--overlap", "0.25"] + (["-d", device] if device else []) +
            ["--filename", "{stem}.{ext}", "-o", sep, src])
    got = {os.path.splitext(os.path.basename(p))[0]: p
           for p in glob.glob(os.path.join(sep, model, "*.wav"))}
    if "vocals" not in got or len(got) < 2:
        print(f"demucs {model} failed:"); print(r.stderr[-1200:])
        if device == "cuda" and GPU_ONLY:        # a prefetch while the GPU is busy: try again later
            print("GPU busy -> this song is separated when its turn comes", flush=True)
            shutil.rmtree(sep, ignore_errors=True)
            try: os.remove(src)
            except Exception: pass
            sys.exit(5)
        if device == "cuda":                     # out of GPU memory / driver trouble -> same model on the CPU
            print("GPU separation failed -> retrying on the CPU", flush=True)
            return separate(model, "cpu")
        return None
    return got

used = MODEL
got = separate(MODEL)
if got is None and MODEL != "htdemucs":
    print("falling back to htdemucs (4 stems)", flush=True)
    used = "htdemucs"; got = separate(used)
if got is None:
    try: os.remove(src)
    except Exception: pass
    print("ERROR: demucs produced no stems"); sys.exit(3)

arrs, sr = {}, None
for k, p in got.items():
    arrs[k], sr = sf.read(p, dtype="float32", always_2d=True)
n = min(len(a) for a in arrs.values())
arrs = {k: a[:n] * 10 ** (PAD_DB / 20) for k, a in arrs.items()}
inst = [k for k in arrs if k != "vocals"]
arrs["no_vocals"] = np.sum([arrs[k] for k in inst], axis=0)
# one common gain for every stem (keeps the balance between them) if any would clip
pk = max(float(np.max(np.abs(a))) for a in arrs.values())
gain = 0.999 / pk if pk > 0.999 else 1.0
for f in glob.glob(os.path.join(sd, "*.flac")) + glob.glob(os.path.join(sd, "*.wav")):
    os.remove(f)
for k, a in arrs.items():
    sf.write(os.path.join(sd, k + ".flac"), a * gain, sr, subtype="PCM_24")
with open(meta, "w", encoding="utf-8") as f:
    json.dump({"model": MODEL, "used": used, "stems": sorted(arrs), "shifts": SHIFTS,
               "gain": gain}, f)
print("stems: " + ", ".join(sorted(inst)) + " + vocals"
      + (f"  (scaled {20*np.log10(gain):+.1f} dB to avoid clipping)" if gain < 1 else ""), flush=True)

for p in (src,):
    try: os.remove(p)
    except Exception: pass
shutil.rmtree(os.path.join(WORK, "sep_" + TAG), ignore_errors=True)

if os.path.exists(vc) and os.path.exists(ic):
    print(f"TAG={TAG}"); print("stems: written", flush=True); sys.exit(0)
print("ERROR: flac encode failed"); sys.exit(4)
