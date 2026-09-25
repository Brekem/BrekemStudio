"""Download the AI model weights into <project>/models so the build ships fully offline.
Run with the build venv's python, from the project root:  python build\\fetch_models.py
  models/torch/hub/checkpoints/*.th   Demucs: htdemucs_ft (default), htdemucs_6s (6 stems),
                                      htdemucs (fast + fallback)
  models/dfn/DeepFilterNet3/          DeepFilterNet3 (vocal denoise)
The frozen app bundles this folder and seeds it into %LOCALAPPDATA%\\BrekemStudio\\models
on first launch (brekem_env._seed_models). Every model the app can use is here: the
installed app never needs the internet.
"""
import io, os, sys, zipfile, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")
os.environ["TORCH_HOME"] = os.path.join(MODELS, "torch")

from demucs.pretrained import get_model
for name in ("htdemucs", "htdemucs_ft", "htdemucs_6s"):
    print("demucs", name, "->", get_model(name).__class__.__name__, flush=True)

dfn = os.path.join(MODELS, "dfn")
if not os.path.isdir(os.path.join(dfn, "DeepFilterNet3")):
    os.makedirs(dfn, exist_ok=True)
    url = "https://github.com/Rikorose/DeepFilterNet/raw/main/models/DeepFilterNet3.zip"
    print("dfn <-", url, flush=True)
    with urllib.request.urlopen(url) as r:
        zipfile.ZipFile(io.BytesIO(r.read())).extractall(dfn)
if not os.path.exists(os.path.join(dfn, "DeepFilterNet3", "config.ini")):
    sys.exit("DeepFilterNet3 model missing after download")

tot = 0
for d, _, fs in os.walk(MODELS):
    for f in fs:
        p = os.path.join(d, f); tot += os.path.getsize(p)
        print(f"  {os.path.relpath(p, MODELS)}  {os.path.getsize(p) // (1 << 20)} MB")
print(f"models total {tot / (1 << 20):.0f} MB")
