; Unicorn Viz Windows Installer (Inno Setup)
; Build with ISCC.exe packaging\windows\UnicornViz.iss

#define AppName "Unicorn Viz"
#define AppVersion "0.1.0"
#define AppPublisher "Unicorn Viz"
#define RepoRoot "..\.."

[Setup]
AppId={{7F4A7D48-38DE-4B80-95F7-773ECA5B2D13}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\UnicornViz
DefaultGroupName={#AppName}
DisableProgramGroupPage=no
OutputDir=.
OutputBaseFilename=UnicornVizInstaller
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#RepoRoot}\assets\icons\unicorn-viz.ico
LicenseFile={#RepoRoot}\LICENSE
UninstallDisplayIcon={app}\assets\icons\unicorn-viz.ico
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; The recursive sweep below packages the whole working tree, so anything that
; must not be redistributed has to be excluded here explicitly.  Three groups:
;
;   1. Restricted third-party assets.  assets\sims\ holds NVIDIA Reallusion USD
;      packs under the Omniverse License Agreement, which forbids
;      redistribution; drop-ins\projectm-01\presets\ holds MilkDrop presets
;      whose authors retain copyright.  Both are git-ignored for the same
;      reason, but a filesystem sweep does not read .gitignore.
;   2. Operator secrets and runtime state — .env, tokens under runtime\, logs,
;      recordings.
;   3. Build and VCS junk that has no business in an installer.
;
; assets\sims\README.md is re-added below: it documents where operators fetch
; the restricted packs themselves.
Source: "{#RepoRoot}\*"; DestDir: "{app}"; \
  Excludes: "\.git,\.git\*,\.github\*,\.venv\*,\venv\*,\build\*,\dist\*,\logs\*,\recordings\*,\runtime\*,\screenshots\*,\.pytest_cache\*,\.ruff_cache\*,\unicorn_viz.egg-info\*,\assets\sims\*,\assets\training\*,\drop-ins\*\presets\*,\drop-ins\*\preset-trash\*,\drop-ins\*\vendor\*,\.env,*.pyc,__pycache__\*"; \
  Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#RepoRoot}\assets\sims\README.md"; DestDir: "{app}\assets\sims"; Flags: ignoreversion
; Attribution: MIT/BSD/Apache dependencies require their notices to travel with
; any binary distribution.  Regenerate THIRD_PARTY_LICENSES.md with
; tools\gen_third_party_licenses.py when requirements.txt pins change.
Source: "{#RepoRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\THIRD_PARTY_LICENSES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Unicorn Viz"; Filename: "{app}\tools\launchers\windows\UnicornVizGUI.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\unicorn-viz.ico"
Name: "{group}\Unicorn Viz Installer"; Filename: "{app}\tools\install_windows.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\unicorn-viz.ico"
Name: "{autodesktop}\Unicorn Viz"; Filename: "{app}\tools\launchers\windows\UnicornVizGUI.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\unicorn-viz.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\tools\install_windows.bat"; Description: "Run Unicorn Viz dependency installer now"; Flags: postinstall shellexec
