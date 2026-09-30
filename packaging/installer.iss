; Inno Setup script - built by CI:  iscc /DMyAppVersion=0.1.0 packaging\installer.iss
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "AppBridge"
#define MyAppExe "AppBridge.exe"

[Setup]
AppId={{6C1E2B7A-4F0B-4A63-9D0B-1E2F0A6B9C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=yswef alhmzy
AppPublisherURL=https://github.com/yswef/AppBridge
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=AppBridge-{#MyAppVersion}-setup
SetupIconFile=appbridge.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "Open .appbridge bundles with AppBridge"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AppBridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.appbridge"; ValueType: string; ValueName: ""; ValueData: "AppBridge.Bundle"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\AppBridge.Bundle"; ValueType: string; ValueName: ""; ValueData: "AppBridge bundle"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\AppBridge.Bundle\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\AppBridge.Bundle\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\platform-tools\adb.exe"; Parameters: "kill-server"; Flags: runhidden skipifdoesntexist; RunOnceId: "KillAdb"
