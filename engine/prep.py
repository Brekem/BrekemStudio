"""Separate one audio file into the stems cache that track_v2.py consumes.
Usage:  prep.py "<audio in>" "<TAG>"
Writes: %BREKEM_STEMS%/<TAG>/{vocals.flac,no_vocals.flac}  (skips if present)
Prints: TAG=<tag> on success.
"""
import os, sys, glob, shutil, subprocess

HOME  = os.environ.get("BREKEM_HOME")  or os.path.dirname(os.path.abspath(__file__))
WORK  = os.environ.get("BREKEM_WORK")  or os.path.join(HOME, "_work")
STEMS = os.environ.get("BREKEM_STEMS") or os.path.join(HOME, "_stems")
PYEXE = os.environ.get("BREKEM_PY")    or sys.executable
os.makedirs(WORK, exist_ok=True); os.makedirs(STEMS, exist_ok=True)

def run(c): return subprocess.run(c, capture_output=True, text=True)

SRCIN = sys.argv[1]
TAG   = sys.argv[2]
sd    = os.path.join(STEMS, TAG)
vc    = os.path.join(sd, "vocals.flac")
ic    = os.path.join(sd, "no_vocals.flac")

if os.path.exists(vc) and os.path.exists(ic):
    print(f"TAG={TAG}"); print("stems: cache hit", flush=True); sys.exit(0)

os.makedirs(sd, exist_ok=True)
src = os.path.join(WORK, TAG + "_src.wav")
r = run(["ffmpeg", "-hide_banner", "-y", "-i", SRCIN, "-ar", "48000", "-ac", "2",
         "-c:a", "pcm_s24le", src])
if not os.path.exists(src):
    print("ERROR: ffmpeg decode failed"); print(r.stderr[-800:]); sys.exit(2)

sep = os.path.join(WORK, "sep_" + TAG)
print("demucs: separating (this is the slow part)...", flush=True)
r = run([PYEXE, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "-o", sep, src])
sepdir = os.path.join(sep, "htdemucs", os.path.splitext(os.path.basename(src))[0])
vp = os.path.join(sepdir, "vocals.wav")
ip = os.path.join(sepdir, "no_vocals.wav")
if not (os.path.exists(vp) and os.path.exists(ip)):
    print("ERROR: demucs produced no stems"); print(r.stderr[-1200:]); sys.exit(3)

run(["ffmpeg", "-hide_banner", "-y", "-i", vp, "-c:a", "flac", "-sample_fmt", "s32",
     "-compression_level", "8", vc])
run(["ffmpeg", "-hide_banner", "-y", "-i", ip, "-c:a", "flac", "-sample_fmt", "s32",
     "-compression_level", "8", ic])
for p in (src,):
    try: os.remove(p)
    except Exception: pass
try: shutil.rmtree(sep)
except Exception: pass

if os.path.exists(vc) and os.path.exists(ic):
    print(f"TAG={TAG}"); print("stems: written", flush=True); sys.exit(0)
print("ERROR: flac encode failed"); sys.exit(4)
