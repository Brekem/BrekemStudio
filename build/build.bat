@echo off
REM ==== BREKEM STUDIO - build the frozen app (+ installer if Inno Setup present) ====
REM   build.bat        CPU edition
REM   build.bat gpu    GPU edition (CUDA PyTorch: AI separation + vocal cleaning on an NVIDIA card)
setlocal
cd /d "%~dp0.."
set FLAVOR=cpu
if /i "%~1"=="gpu" set FLAVOR=gpu

if not exist ".venv\Scripts\python.exe" (
  echo Creating venv...
  py -3.10 -m venv .venv || (echo need Python 3.10 & exit /b 1)
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt || exit /b 1
if "%FLAVOR%"=="gpu" (
  pip install --force-reinstall --no-deps torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128 || exit /b 1
)

echo.
echo ==== PyInstaller ====
pyinstaller build\brekem.spec --noconfirm || exit /b 1
echo Frozen app: dist\BrekemStudio\BrekemStudio.exe

REM ---- optional: Inno Setup installer ----
set ISCC=
for %%P in (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles%\Inno Setup 6\ISCC.exe"
  "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
) do if exist %%P set ISCC=%%P

if defined ISCC (
  echo.
  echo ==== Inno Setup ====
  "%ISCC%" /DFlavor=%FLAVOR% build\installer.iss || exit /b 1
  echo Installer in dist\  ^(GPU edition: BREKEM.STUDIO.3.5.0.GPU.Setup.exe + its .bin parts^)
) else (
  echo Inno Setup not found - skipping installer. Zip dist\BrekemStudio\ instead,
  echo or: winget install JRSoftware.InnoSetup  then re-run this script.
)
endlocal
