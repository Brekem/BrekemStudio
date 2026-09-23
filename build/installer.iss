; BREKEM STUDIO - Inno Setup script
; Build:  ISCC.exe build\installer.iss   (run from project root, after PyInstaller)

#define AppName "BREKEM STUDIO"
#define AppVer  "1.0.0"
#define AppExe  "BrekemStudio.exe"
; project root = folder above this .iss
#define Root AddBackslash(SourcePath) + ".."

[Setup]
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=BREKEM
DefaultDirName={autopf}\BREKEM STUDIO
DefaultGroupName=BREKEM STUDIO
DisableProgramGroupPage=yes
OutputDir={#Root}\dist
OutputBaseFilename=BREKEM STUDIO Setup
Compression=lzma2/max
SolidCompression=yes
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
