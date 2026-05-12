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
UninstallDisplayIcon={app}\assets\icons\unicorn-viz.ico
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#RepoRoot}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Unicorn Viz"; Filename: "{app}\tools\launchers\windows\UnicornVizGUI.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\unicorn-viz.ico"
Name: "{group}\Unicorn Viz Installer"; Filename: "{app}\tools\install_windows.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\unicorn-viz.ico"
Name: "{autodesktop}\Unicorn Viz"; Filename: "{app}\tools\launchers\windows\UnicornVizGUI.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\unicorn-viz.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\tools\install_windows.bat"; Description: "Run Unicorn Viz dependency installer now"; Flags: postinstall shellexec
