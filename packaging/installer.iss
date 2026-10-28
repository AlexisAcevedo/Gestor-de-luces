; Inno Setup script. Build with:  iscc /DAppVersion=0.2.1 packaging\installer.iss
; Expects the PyInstaller one-folder output in dist\GestorDeLuces (see scripts\build.ps1).

#ifndef AppVersion
  #define AppVersion "0.2.1"
#endif

#define AppName "WiZ Lighting Console"
#define AppExe "GestorDeLuces.exe"

[Setup]
AppId={{6B1E2C0A-3F1B-4D7E-9A55-5C0B7D1E8F42}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Gestor de Luces
DefaultDirName={autopf}\GestorDeLuces
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=GestorDeLuces-Setup-{#AppVersion}
SetupIconFile=..\assets\icon\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The app stores user data in %LOCALAPPDATA%\GestorDeLuces, never under Program Files.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Start with Windows (minimized to the tray)"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\GestorDeLuces\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same key and value name as the in-app "Start with Windows" toggle (WindowsRegistryAutostart).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GestorDeLuces"; ValueData: """{app}\{#AppExe}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function IsWebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not IsWebView2Installed() then
  begin
    if MsgBox('The Microsoft Edge WebView2 Runtime was not detected. The application needs it to show its window.' + #13#10 +
              'Install it from https://developer.microsoft.com/microsoft-edge/webview2/ after setup.' + #13#10#13#10 +
              'Continue with the installation?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
