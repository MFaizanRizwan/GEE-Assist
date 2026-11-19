; Inno Setup script for the GEE-Assist installer. Run through build_app.py,
; which passes AppVersion and the built app folder (dist\GEE-Assist).
;
; Installs for the current user by default (no admin needed) into
; %LOCALAPPDATA%\Programs\GEE-Assist; the user can choose all users instead.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\GEE-Assist"
#endif

[Setup]
AppId={{6E0B1C52-3F4A-4C8E-9B1D-7A2E5F0C9D41}
AppName=GEE-Assist
AppVersion={#AppVersion}
AppVerName=GEE-Assist {#AppVersion}
AppPublisher=GEE-Assist
DefaultDirName={autopf}\GEE-Assist
DefaultGroupName=GEE-Assist
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=GEE-Assist-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\GEE-Assist.exe
UninstallDisplayName=GEE-Assist
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName=GEE-Assist

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove the previous version's files so nothing stale is left beside the new ones.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\GEE-Assist"; Filename: "{app}\GEE-Assist.exe"
Name: "{autodesktop}\GEE-Assist"; Filename: "{app}\GEE-Assist.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GEE-Assist.exe"; Description: "{cm:LaunchProgram,GEE-Assist}"; Flags: nowait postinstall skipifsilent
