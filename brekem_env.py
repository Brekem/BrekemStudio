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
import threading

VERSION = "3.3.0"
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
    os.environ["BREKEM_LOGS"]  = LOGS    # engine logs: the install folder (Program Files) is read-only
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
    # NVIDIA RTX 30/40/50: matrix math on the tensor cores (TF32) - Demucs' transformer and
    # DeepFilterNet. Convolutions already use them (cuDNN default). No fp16: same quality.
    os.environ.setdefault("TORCH_ALLOW_TF32_CUBLAS_OVERRIDE", "1")
    if os.environ.get("BREKEM_GPU", "1") == "0":       # --cpu: hide the GPU from every engine
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    # bundled ffmpeg first on PATH so bare "ffmpeg"/"ffprobe" resolve to ours
    if os.path.isdir(VENDOR):
        os.environ["PATH"] = VENDOR + os.pathsep + os.environ.get("PATH", "")
    # engine dir importable (acap_pro etc.)
    if ENGINE not in sys.path:
        sys.path.insert(0, ENGINE)

def _child_exe():
    """the interpreter engines run with: the console twin when frozen, else this python."""
    if FROZEN:
        cli = os.path.join(os.path.dirname(sys.executable), "BrekemStudioCLI.exe")
        if os.path.exists(cli):
            return cli
    return sys.executable


_GPU_CODE = (
    "import torch\n"
    "if torch.cuda.is_available():\n"
    "    a = torch.ones(256, 256, device='cuda'); float((a @ a).sum())\n"   # a real kernel: a card this
    "    p = torch.cuda.get_device_properties(0)\n"                            # build can't run fails here
    "    print('GPU|%s|%s|%d.%d|%d' % (p.name, torch.version.cuda, p.major, p.minor, p.total_memory >> 20))\n"
    "else:\n"
    "    print('CPU|%s' % torch.version.cuda)\n")
_GPU = {}
_GPU_LOCK = threading.Lock()


def gpu():
    """the NVIDIA GPU the AI models (Demucs, DeepFilterNet) can run on:
    {name, cuda, cc, vram_mb} - or {} = CPU, with {"hint": ...} saying why when it helps.
    Probed once per process in a child process, so a broken driver can't take the app down."""
    with _GPU_LOCK:
        if "info" not in _GPU:
            _GPU["info"] = _probe_gpu()
        return _GPU["info"]


def _probe_gpu():
    info = {}
    if os.environ.get("BREKEM_GPU", "1") == "0":
        info = {"hint": "GPU turned off (--cpu)"}
    else:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        line, err = "", ""
        try:
            r = subprocess.run([_child_exe(), "-c", _GPU_CODE], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=300, env=env,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
            lines = [l for l in r.stdout.splitlines() if l.startswith(("GPU|", "CPU|"))]
            line, err = (lines[-1] if lines else ""), r.stderr[-300:]
        except Exception as e:
            err = str(e)
        p = line.split("|")
        if p[0] == "GPU" and len(p) == 5:
            info = {"name": p[1], "cuda": p[2], "cc": p[3], "vram_mb": int(p[4])}
        elif p[0] == "CPU" and len(p) == 2 and p[1] in ("None", ""):
            nv = any(os.path.exists(os.path.join(d, "nvidia-smi.exe"))
                     for d in os.environ.get("PATH", "").split(os.pathsep) + [r"C:\Windows\System32"])
            info = {"hint": "this is the CPU edition" + (" - an NVIDIA card is installed: the GPU edition uses it"
                                                          if nv else "")}
        else:
            info = {"hint": "no usable NVIDIA GPU (driver too old, or a card older than GTX 16 / RTX 20)"
                            + (f": {err.strip().splitlines()[-1]}" if err.strip() else "")}
    if not info.get("name"):
        os.environ["CUDA_VISIBLE_DEVICES"] = ""          # every engine on the CPU, none tries a bad GPU
    os.environ["BREKEM_CUDA"] = "1" if info.get("name") else "0"
    return info


def gpu_line():
    g = gpu()
    if g.get("name"):
        tc = "tensor cores (TF32)" if int(g["cc"].split(".")[0]) >= 8 else "CUDA cores"
        return (f"GPU: {g['name']} ({round(g['vram_mb'] / 1024)} GB, CUDA {g['cuda']}) - AI separation + "
                f"vocal cleaning run on it, {tc}")
    return "GPU: not used - " + g.get("hint", "CPU") + " (everything runs on the CPU)"


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
    # engine output is UTF-8 both ways: a reference or song named with symbols the Windows
    # console code page can't show (e.g. U+29F9) used to crash the engine's print()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    creat = 0
    if os.name == "nt":
        creat = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", bufsize=1,
                         cwd=cwd or WORK, env=env,   # never the install folder: it is read-only
                         creationflags=creat if os.name == "nt" else 0)
    for line in p.stdout:
        if on_line:
            on_line(line.rstrip("\n"))
    p.wait()
    return p.returncode
