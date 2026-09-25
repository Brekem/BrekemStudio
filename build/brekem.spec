# PyInstaller spec for BREKEM STUDIO
#   build from the project root:  pyinstaller build\brekem.spec --noconfirm
import os, glob
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

# SPECPATH is injected by PyInstaller = directory containing this .spec (…/BREKEM STUDIO/build)
ROOT = os.path.dirname(SPECPATH)
MAIN = os.path.join(ROOT, "BrekemStudio.py")

datas, binaries, hiddenimports = [], [], []

for pkg in ("torch", "torchaudio", "demucs", "df", "matchering", "pedalboard",
            "librosa", "soxr", "lazy_loader", "audioread", "pooch", "statsmodels",
            "pandas", "pyloudnorm", "numba", "llvmlite", "scipy", "sklearn"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print("collect_all skipped", pkg, e)

# soundfile is a single module (not a package) -> collect_all misses its libsndfile.
# Ship _soundfile_data/ explicitly so sf.read()/sf.write() work when frozen.
try:
    import _soundfile_data
    _sfd = os.path.dirname(_soundfile_data.__file__)
    for f in glob.glob(os.path.join(_sfd, "*")):
        if os.path.isfile(f):
            datas.append((f, "_soundfile_data"))
    hiddenimports += ["soundfile", "_soundfile_data", "cffi"]
    print("bundled _soundfile_data from", _sfd)
except Exception as e:
    print("soundfile data NOT bundled:", e)

# our own resources (kept as a folder tree next to the exe internals)
for sub in ("engine", "vendor", "refs", "models"):
    p = os.path.join(ROOT, sub)
    for dirpath, _, files in os.walk(p):
        if sub == "models" and "blobs" in dirpath.replace("\\", "/").split("/"):
            continue   # Hugging Face cache: snapshots/ already resolve to these files (no 2x size)
        for fn in files:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(dirpath, ROOT)
            datas.append((full, rel))
for fn in ("LICENSE", "NOTICE.md", "README.md"):
    if os.path.exists(os.path.join(ROOT, fn)):
        datas.append((os.path.join(ROOT, fn), "."))

hiddenimports += [
    "brekem_env", "brekem_cli", "brekem_gui",
    "sklearn.utils._typedefs", "sklearn.neighbors._partition_nodes",
    "scipy._lib.array_api_compat.numpy.fft",
]

block_cipher = None

# --- size trim: drop dead weight PyInstaller over-collects ---
def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    if dest.endswith(".lib"):            # torch static link libs (dnnl.lib ~660MB) - useless at runtime
        return False
    if "/cv2/" in dest or dest.startswith("cv2/"):   # opencv pulled transitively, unused
        return False
    if "/torch/lib/" in dest and dest.endswith((".h", ".hpp")):
        return False
    return True

a = Analysis(
    [MAIN],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "matplotlib", "PyQt5", "PySide2", "PySide6", "PyQt6",
              "IPython", "notebook", "pytest", "nbconvert"],
    cipher=block_cipher,
    noarchive=False,
)
a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BrekemStudio",
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "icons", "brekem.ico") if os.path.exists(os.path.join(ROOT, "icons", "brekem.ico")) else None,
)
# same program as a console app: the GUI runs the engines through it (real stdout),
# and it is the command-line entry point:  BrekemStudioCLI.exe cli master "<song>" "<out>"
exe_cli = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BrekemStudioCLI",
    console=True,
)
coll = COLLECT(
    exe, exe_cli, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="BrekemStudio",
)
