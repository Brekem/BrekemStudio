@echo off
REM ==== BREKEM STUDIO - build the frozen app (+ installer if Inno Setup present) ====
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Creating venv...
  py -3.10 -m venv .venv || (echo need Python 3.10 & exit /b 1)
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt || exit /b 1

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
  "%ISCC%" build\installer.iss || exit /b 1
  echo Installer: dist\BREKEM STUDIO Setup.exe
) else (
  echo Inno Setup not found - skipping installer. Zip dist\BrekemStudio\ instead,
  echo or: winget install JRSoftware.InnoSetup  then re-run this script.
)
endlocal
