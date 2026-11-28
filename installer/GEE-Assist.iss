; GEE-Assist installer (Inno Setup 6). Built by build_app.py, which passes:
;   /DAppVersion=X.Y.Z   the version (also stamped into the Setup's file properties: the app's
;                        updater reads it there to check a downloaded Setup)
;   /DSourceDir=...      the PyInstaller folder build (dist\GEE-Assist)
;   /DOutputDir=...      where GEE-Assist-Setup-X.Y.Z.exe goes (dist)
;
; Installs per user (%LOCALAPPDATA%\Programs\GEE-Assist) without administrator rights; the
; user may choose "for all users" instead (Program Files, needs administrator rights).
;
; Updates: the running app starts this Setup with
;   /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /RELAUNCH=1 /CURRENTUSER|/ALLUSERS /DIR=<app folder>
; and quits. The Setup waits for the app to close (its mutex "GEE-Assist-Running"), replaces
; the program files and, with /RELAUNCH=1, starts the new version. User data lives in
; %APPDATA%\GEE-Assist and is never touched, also not by the uninstaller.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\GEE-Assist"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
; Never change the AppId: Windows recognises every later version as the same app by it
AppId={{A865DDBA-A978-4C0A-A474-0007BA0806F8}
AppName=GEE-Assist
AppVersion={#AppVersion}
AppVerName=GEE-Assist {#AppVersion}
AppPublisher=GEE-Assist
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
VersionInfoProductName=GEE-Assist
VersionInfoDescription=GEE-Assist Setup
DefaultDirName={autopf}\GEE-Assist
DefaultGroupName=GEE-Assist
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
OutputDir={#OutputDir}
OutputBaseFilename=GEE-Assist-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\GEE-Assist.exe
Compression=lzma2/normal
SolidCompression=no
DiskSpanning=no
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; the previous version's program files: a file the new version no longer has must not linger
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\GEE-Assist"; Filename: "{app}\GEE-Assist.exe"
Name: "{autodesktop}\GEE-Assist"; Filename: "{app}\GEE-Assist.exe"; Tasks: desktopicon

[Run]
; after a normal install: offer to open it
Filename: "{app}\GEE-Assist.exe"; Description: "Open GEE-Assist"; Flags: nowait postinstall skipifsilent
; after an update started by the app: open the new version
Filename: "{app}\GEE-Assist.exe"; Flags: nowait; Check: Relaunch

[Code]
const
  AppMutex = 'GEE-Assist-Running';

function Relaunch(): Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

{ Wait for the app to close (it quits right after starting an update) before files are replaced. }
function InitializeSetup(): Boolean;
var
  Waited: Integer;
begin
  Waited := 0;
  while CheckForMutexes(AppMutex) and (Waited < 120) do
  begin
    Sleep(500);
    Waited := Waited + 1;
  end;
  Result := True;
  if CheckForMutexes(AppMutex) then
  begin
    if WizardSilent() then
      Result := False
    else
      Result := MsgBox('GEE-Assist is still open. Close it, then click OK to continue.',
                       mbInformation, MB_OKCANCEL) = IDOK;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  if CheckForMutexes(AppMutex) then
  begin
    MsgBox('Close GEE-Assist before uninstalling it.', mbInformation, MB_OK);
    Result := False;
  end;
end;
