; Inno Setup script. Build with:  iscc /DAppVersion=<version> packaging\installer.iss
; (scripts\build.ps1 passes the version taken from pyproject.toml).
; Expects the PyInstaller one-folder output in dist\WizConsole (see scripts\build.ps1).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

; One product name across the whole shell: the exe metadata
; (packaging/wiz_console.spec), the About dialog (app_menu.APP_DISPLAY_NAME), the
; Apps & features entry and the Start Menu group all read the same string.
#define AppName "WiZ Architectural Lighting Console"
#define AppExe "WizConsole.exe"

[Setup]
AppId={{6B1E2C0A-3F1B-4D7E-9A55-5C0B7D1E8F42}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AlexisAcevedo
DefaultDirName={autopf}\WizConsole
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=WizConsole-Setup-{#AppVersion}
SetupIconFile=..\assets\icon\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The app stores user data in %LOCALAPPDATA%\WizConsole, never under Program Files.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[CustomMessages]
english.AutostartTask=Start with Windows (minimized to the tray)
english.StartupGroup=Startup:
english.WebView2Missing=The Microsoft Edge WebView2 Runtime was not detected. The application needs it to show its window.%nInstall it from https://developer.microsoft.com/microsoft-edge/webview2/ after setup.%n%nContinue with the installation?
spanish.AutostartTask=Iniciar con Windows (minimizado en la bandeja)
spanish.StartupGroup=Inicio:
spanish.WebView2Missing=No se detecto Microsoft Edge WebView2 Runtime. La aplicacion lo necesita para mostrar su ventana.%nInstalalo desde https://developer.microsoft.com/microsoft-edge/webview2/ despues de finalizar.%n%nDeseas continuar con la instalacion?

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "{cm:AutostartTask}"; GroupDescription: "{cm:StartupGroup}"; Flags: unchecked

[Files]
Source: "..\dist\WizConsole\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same key and value name as the in-app "Start with Windows" toggle (WindowsRegistryAutostart).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WizConsole"; ValueData: """{app}\{#AppExe}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart
; Ensure uninstall removes the autostart entry even if the user enabled it from inside the app.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "WizConsole"; Flags: uninsdeletevalue
; Clean up legacy GestorDeLuces autostart entry on upgrade and uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "GestorDeLuces"; Flags: deletevalue uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

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
    if MsgBox(CustomMessage('WebView2Missing'), mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
