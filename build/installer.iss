; BREKEM STUDIO - Inno Setup script
; Build:  ISCC.exe build\installer.iss              (CPU edition)
;         ISCC.exe /DFlavor=gpu build\installer.iss  (GPU edition: the app frozen with CUDA PyTorch)
; run from the project root, after PyInstaller

#define AppName "BREKEM STUDIO"
#define AppVer  "3.5.0"
#define AppExe  "BrekemStudio.exe"
; project root = folder above this .iss
#define Root AddBackslash(SourcePath) + ".."
#ifndef Flavor
  #define Flavor "cpu"
#endif
#if Flavor == "gpu"
  ; no spaces: GitHub stores release files with dots for spaces, and the setup finds its
  ; .bin parts by the exact name it was built with
  #define OutName "BREKEM.STUDIO." + AppVer + ".GPU.Setup"
#else
  #define OutName "BREKEM STUDIO " + AppVer + " Setup"
#endif

[Setup]
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=BREKEM
DefaultDirName={autopf}\BREKEM STUDIO
DefaultGroupName=BREKEM STUDIO
DisableProgramGroupPage=yes
OutputDir={#Root}\dist
OutputBaseFilename={#OutName}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
#if Flavor == "gpu"
; CUDA PyTorch makes the app ~3x bigger: the setup comes as an .exe plus .bin parts
; (each under GitHub's 2 GB per-file limit) that must sit in the same folder
DiskSpanning=yes
DiskSliceSize=1900000000
#endif
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#Root}\LICENSE
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Files]
Source: "{#Root}\dist\BrekemStudio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\BREKEM STUDIO"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\BREKEM STUDIO"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir BREKEM STUDIO"; Flags: nowait postinstall skipifsilent
