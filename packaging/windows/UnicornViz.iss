; Unicorn Viz — Windows installer (Inno Setup 6.3+).
;
; Packages the tree assembled by tools/packaging/build_windows_portable.sh
; --payload-out (curated payload + embedded python-build-standalone runtime with
; the pinned dependencies cross-installed). It never copies the repository and
; never runs pip on the user's machine (installer plan §8, §18 Block E2).
;
; Build:
;   bash tools/packaging/build_windows_portable.sh --payload-out build\windows
;   ISCC.exe /DAppVersion=1.0.0-beta.111 /DPayloadDir=..\..\build\windows\UnicornViz packaging\windows\UnicornViz.iss
;
; Signing (plan §10): pass /S"signtool=..." and add SignTool=signtool under
; [Setup] from CI only when a code-signing certificate secret is present.
; Until then the installer is unsigned — SmartScreen shows "More info → Run
; anyway" on first launch.

#define AppName "Unicorn Viz"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\..\build\windows\UnicornViz"
#endif
#define RepoRoot "..\.."

[Setup]
AppId={{7F4A7D48-38DE-4B80-95F7-773ECA5B2D13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Unicorn Viz
AppPublisherURL=https://unicornviz.io
AppSupportURL=https://github.com/djunicorntears/unicorn-viz/issues
DefaultDirName={autopf}\UnicornViz
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile={#PayloadDir}\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=UnicornViz-Setup-{#AppVersion}
SetupIconFile={#RepoRoot}\assets\icons\unicorn-viz.ico
UninstallDisplayIcon={app}\unicorn-viz.ico
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "addtopath"; Description: "Add unicorn-viz to PATH (run it from any terminal)"; GroupDescription: "Command line:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#RepoRoot}\assets\icons\unicorn-viz.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; pythonw.exe -m unicornviz with WorkingDir={app}: the package is imported from
; {app}\unicornviz, so APP_ROOT resolves to {app} and assets are found without
; any environment variable (see unicornviz/paths.py). No console window.
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: "-m unicornviz"; WorkingDir: "{app}"; IconFilename: "{app}\unicorn-viz.ico"; AppUserModelID: "io.unicornviz.UnicornViz"
Name: "{group}\{#AppName} (console)"; Filename: "{app}\unicorn-viz.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\unicorn-viz.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: "-m unicornviz"; WorkingDir: "{app}"; IconFilename: "{app}\unicorn-viz.ico"; AppUserModelID: "io.unicornviz.UnicornViz"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\runtime\python\pythonw.exe"; Parameters: "-m unicornviz"; WorkingDir: "{app}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKA, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;
