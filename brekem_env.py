"""BREKEM STUDIO - runtime bootstrap.
Resolves paths for both 'run from source' and the PyInstaller frozen build,
exports the BREKEM_* environment variables the engine/*.py scripts read, puts
the bundled ffmpeg on PATH, and offers run_engine() to launch an engine script
as a child process (or in-process when frozen).
"""
import os
import sys
import glob
import subprocess

VERSION = "2.0.0"
FROZEN = getattr(sys, "frozen", False)

def _res_root():
    if FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

RES   = _res_root()
ENGINE = os.path.join(RES, "engine")
VENDOR = os.path.join(RES, "vendor")

def _user_data():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "BrekemStudio")
    os.makedirs(d, exist_ok=True)
    return d

DATA   = _user_data()
WORK   = os.path.join(DATA, "work")
STEMS  = os.path.join(DATA, "stems")
MODELS = os.path.join(DATA, "models")
LOGS   = os.path.join(DATA, "logs")
for _d in (WORK, STEMS, MODELS, LOGS):
    os.makedirs(_d, exist_ok=True)

# the user's reference songs always live in per-user data (writable, survives
# reinstalls/updates). A bundled refs/ only seeds the README the first time.
REFS = os.path.join(DATA, "refs")
os.makedirs(REFS, exist_ok=True)
_seed = os.path.join(RES, "refs", "README.txt")
if os.path.exists(_seed) and not os.path.exists(os.path.join(REFS, "README.txt")):
    try:
        import shutil as _sh
        _sh.copy2(_seed, os.path.join(REFS, "README.txt"))
    except Exception:
        pass

def _ff(name):
    p = os.path.join(VENDOR, name + (".exe" if os.name == "nt" else ""))
    return p if os.path.exists(p) else name

FFMPEG  = _ff("ffmpeg")
FFPROBE = _ff("ffprobe")

def _seed_models():
    """Copy the models bundled with the app into the writable per-user cache the
    first time, so Demucs + DeepFilterNet work with zero internet."""
    src = os.path.join(RES, "models")
    if not os.path.isdir(src):
        return
    import shutil
    for rel_dir, _sub, files in os.walk(src):
        rel = os.path.relpath(rel_dir, src)
        dst_dir = os.path.join(MODELS, rel) if rel != "." else MODELS
        os.makedirs(dst_dir, exist_ok=True)
        for fn in files:
            d = os.path.join(dst_dir, fn)
            if not os.path.exists(d):
                try:
                    shutil.copy2(os.path.join(rel_dir, fn), d)
                except Exception:
                    pass

DFN_MODEL = os.path.join(MODELS, "dfn", "DeepFilterNet3")

def apply_env():
    _seed_models()
    os.environ["BREKEM_HOME"]  = ENGINE
    os.environ["BREKEM_WORK"]  = WORK
    os.environ["BREKEM_STEMS"] = STEMS
    os.environ["BREKEM_REFS"]  = REFS
    os.environ["BREKEM_PY"]    = sys.executable
    os.environ["BREKEM_FFMPEG"]  = FFMPEG
    os.environ["BREKEM_FFPROBE"] = FFPROBE
    # bundled DeepFilterNet3 model dir (offline)
    if os.path.isdir(DFN_MODEL):
        os.environ["BREKEM_DFN_MODEL"] = DFN_MODEL
    # demucs / torch.hub -> look inside the app data dir (offline weights seeded there)
    os.environ["TORCH_HOME"] = os.path.join(MODELS, "torch")
    os.environ.setdefault("DEMUCS_MODELS", os.path.join(MODELS, "demucs"))
    os.environ.setdefault("XDG_CACHE_HOME", os.path.join(MODELS, "cache"))
    # Demucs >= 4.1 loads its models from the Hugging Face hub cache: point it at the
    # bundled copy and never go online (the product is 100% offline)
    os.environ["HF_HOME"] = os.path.join(MODELS, "hf")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    # bundled ffmpeg first on PATH so bare "ffmpeg"/"ffprobe" resolve to ours
    if os.path.isdir(VENDOR):
        os.environ["PATH"] = VENDOR + os.pathsep + os.environ.get("PATH", "")
    # engine dir importable (acap_pro etc.)
    if ENGINE not in sys.path:
        sys.path.insert(0, ENGINE)

def refs_list():
    return sorted(glob.glob(os.path.join(REFS, "*.wav")) + glob.glob(os.path.join(REFS, "*.flac")))

def have_refs():
    return len(refs_list()) >= 2

def run_engine(script, args, on_line=None, cwd=None):
    """Launch engine/<script> with args. Streams stdout lines to on_line(str).
    Returns exit code. Works from source (child python) and frozen (multi-call exe)."""
    apply_env()
    spath = os.path.join(ENGINE, script)
    exe = sys.executable
    if FROZEN:   # the console twin has a real stdout for the engine's output and progress bars
        cli = os.path.join(os.path.dirname(sys.executable), "BrekemStudioCLI.exe")
        if os.path.exists(cli):
            exe = cli
            os.environ["BREKEM_PY"] = cli    # engines spawn demucs etc. through it too
    cmd = [exe, spath] + [str(a) for a in args]
    env = dict(os.environ)
    creat = 0
    if os.name == "nt":
        creat = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, cwd=cwd or ENGINE, env=env,
                         creationflags=creat if os.name == "nt" else 0)
    for line in p.stdout:
        if on_line:
            on_line(line.rstrip("\n"))
    p.wait()
    return p.returncode
