[Setup]
AppId={{CAFA6B2B-FBA2-44EA-9A7B-93230AD7B2D8}
AppName=XPS Studio
AppVersion=1.1.0
AppPublisher=XPS Studio
DefaultDirName={localappdata}\Programs\XPS Studio
DefaultGroupName=XPS Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\release
OutputBaseFilename=XPSStudio-v1.1-Setup
SetupIconFile=xps.ico
UninstallDisplayIcon={app}\XPSStudio.exe
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\release\XPSStudio.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\XPS Studio"; Filename: "{app}\XPSStudio.exe"; WorkingDir: "{userdocs}"
Name: "{autodesktop}\XPS Studio"; Filename: "{app}\XPSStudio.exe"; WorkingDir: "{userdocs}"; Tasks: desktopicon

[Run]
Filename: "{app}\XPSStudio.exe"; Description: "Launch XPS Studio"; Flags: nowait postinstall skipifsilent
