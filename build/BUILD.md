# Building the BREKEM STUDIO installer

## Requirements
- Windows 10/11 x64
- Python 3.10 (`py -3.10 --version`)
- ~12 GB free disk during the build (frozen app is ~3.5–4 GB)
- Optional: Inno Setup 6 (`winget install JRSoftware.InnoSetup`) for a real `Setup.exe`

## One shot
From the project root:
```
build\build.bat
```
It creates `.venv`, installs `requirements.txt`, runs PyInstaller with
`build\brekem.spec`, and — if Inno Setup is on the machine — produces
`dist\BREKEM STUDIO Setup.exe`. Without Inno Setup you get the portable folder
`dist\BrekemStudio\` (zip it and share).

## Known-resolved issues (already handled in brekem.spec)
- **libsndfile missing** → `soundfile` is a single module, `collect_all` misses its
  DLL. The spec ships `_soundfile_data/` explicitly.
- **`No module named 'pandas'`** → Matchering → statsmodels → pandas. All three are
  in `requirements.txt` and the spec's `collect_all` loop.
- **`dnnl.lib` (~660 MB) + `cv2` bloat** → the spec's `_keep()` filter drops `.lib`
  static libs and the transitively-pulled OpenCV. Cuts ~700 MB off the install.
- **ISCC not on PATH** → `build.bat` also looks in `%LocalAppData%\Programs\Inno Setup 6`.
- LZMA2/max on a ~2 GB payload takes 15–20 min; ISCC prints nothing meanwhile.

## If the frozen app errors on launch
PyInstaller + torch/demucs/deepfilternet usually needs one or two hidden-import
fixes. When `BrekemStudio.exe` throws `ModuleNotFoundError: X`:
1. add `"X"` to `hiddenimports` in `build\brekem.spec`
2. `pyinstaller build\brekem.spec --noconfirm`
Common offenders already covered: `numba`, `llvmlite`, `lazy_loader`, `soxr`,
`sklearn.utils._typedefs`, `scipy.special._cdflib`.

For DeepFilterNet: if `libdf` / the model tar is missing at runtime, confirm
`collect_all("df")` picked up `df/**/*.tar.gz` and the `*.pyd`; if not add them
to `datas` explicitly.

## Model weights
By default the frozen app downloads Demucs (~80 MB) + DeepFilterNet weights on
first run to `%LOCALAPPDATA%\BrekemStudio\models`. To ship fully offline,
pre-populate that folder on your build machine (run the app once), then add its
contents to `[Files]` in `installer.iss` under `DestDir: "{localappdata}\BrekemStudio\models"`.

## Size trim (optional)
- swap `vendor\ffmpeg.exe`/`ffprobe.exe` for the gyan.dev *essentials* build (~90 MB vs 222 MB each)
- in `brekem.spec` `excludes`, add anything torch pulls that you don't need
