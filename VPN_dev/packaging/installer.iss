; Inno Setup script. Build:  iscc /DMyAppVersion=1.0.0 packaging\installer.iss   (build.ps1 does this, and signs)
; WireGuard for Windows is required (NOBAD drives its tunnel service). The official, WireGuard-LLC-signed MSIs are
; bundled (build.ps1 downloads and verifies them into packaging\redist) and installed silently when missing.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "NOBAD VPN"
#define MyAppExe "NobadVPN.exe"

[Setup]
AppId={{6B1E2F43-5C0A-4B7D-9E55-7A1C3D9A4E21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=NOBAD
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoCompany=NOBAD
DefaultDirName={autopf}\NOBAD VPN
DefaultGroupName=NOBAD VPN
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist-installer
OutputBaseFilename=NobadVPN-Setup-{#MyAppVersion}
SetupIconFile=..\nobadvpn\ui\brand\nobad.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
#ifdef SignBuild
SignTool=nobadsign
SignedUninstaller=yes
#endif

[Files]
Source: "..\dist\NobadVPN\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
; Licensing: NOBAD's MIT license and the notices for every bundled third-party component.
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
; Kept in {app}\redist so the app can repair a missing WireGuard later without internet access.
Source: "redist\wireguard-amd64.msi"; DestDir: "{app}\redist"; Flags: ignoreversion
Source: "redist\wireguard-arm64.msi"; DestDir: "{app}\redist"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
; Offline fail-safe: works with NOBAD closed (or broken) and without internet. Asks for admin rights, removes every
; NOBAD firewall rule, tunnel service and DNS change, then shows what it did.
Name: "{group}\Restore internet (NOBAD)"; Filename: "{app}\{#MyAppExe}"; Parameters: "--panic --show-result";   Comment: "Remove every NOBAD firewall rule, tunnel and DNS change, even if NOBAD is not running"
Name: "{group}\Repair network (NOBAD)"; Filename: "{app}\{#MyAppExe}"; Parameters: "--repair-network quick --show-result";   Comment: "Restore internet, then flush DNS, clear the ARP cache and renew DHCP"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Tasks]
Name: "autostart"; Description: "Start NOBAD VPN when I sign in (recommended: opens instantly and keeps protection on)"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
; 1) WireGuard first (only when it is not installed yet). DO_NOT_LAUNCH keeps WireGuard's own window closed.
Filename: "{sys}\msiexec.exe"; Parameters: "/i ""{app}\redist\{code:WireGuardMsi}"" /qn /norestart DO_NOT_LAUNCH=1"; \
  StatusMsg: "Installing WireGuard (required by NOBAD VPN)..."; Flags: runhidden waituntilterminated; \
  Check: NeedsWireGuard; AfterInstall: CheckWireGuard
; 2) Elevated scheduled tasks (registered for the installing user): no UAC prompt when NOBAD is opened, and
;    optionally start at sign-in. Run while Setup is still elevated, so the user never sees an extra prompt.
Filename: "{app}\{#MyAppExe}"; Parameters: "--install-tasks --autostart on"; StatusMsg: "Setting up NOBAD VPN...";   Flags: runhidden waituntilterminated; Tasks: autostart
Filename: "{app}\{#MyAppExe}"; Parameters: "--install-tasks --autostart off"; StatusMsg: "Setting up NOBAD VPN...";   Flags: runhidden waituntilterminated; Tasks: not autostart
; 3) Start NOBAD VPN.
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
; Silent installs come from the in-app updater, which has already quit: start the new version again.
Filename: "{app}\{#MyAppExe}"; Parameters: "--background"; Flags: nowait; Check: WizardSilent

[UninstallRun]
; Never leave someone offline: remove firewall rules / tunnels, then NOBAD's scheduled tasks.
; WireGuard itself is left installed (other apps or the user may rely on it); remove it in Settings > Apps if wanted.
Filename: "{app}\{#MyAppExe}"; Parameters: "--panic"; Flags: runhidden; RunOnceId: "NobadPanic"
Filename: "schtasks.exe"; Parameters: "/Delete /TN NobadVPN /F"; Flags: runhidden; RunOnceId: "NobadTask"
Filename: "schtasks.exe"; Parameters: "/Delete /TN ""NobadVPN Launcher"" /F"; Flags: runhidden; RunOnceId: "NobadLauncher"
Filename: "schtasks.exe"; Parameters: "/Delete /TN ""NobadVPN Guard"" /F"; Flags: runhidden; RunOnceId: "NobadGuard"
Filename: "schtasks.exe"; Parameters: "/Delete /TN NomadTunnel /F"; Flags: runhidden; RunOnceId: "LegacyTask"
; Configs and settings in C:\ProgramData\NobadVPN are kept on purpose (they hold your keys); delete them by hand if wanted.

[Code]
function WireGuardInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf64}\WireGuard\wireguard.exe')) or
            FileExists(ExpandConstant('{commonpf32}\WireGuard\wireguard.exe'));
end;

function NeedsWireGuard: Boolean;
begin
  Result := not WireGuardInstalled;
end;

function WireGuardMsi(Param: String): String;
begin
  if IsArm64 then
    Result := 'wireguard-arm64.msi'
  else
    Result := 'wireguard-amd64.msi';
end;

procedure CheckWireGuard;
begin
  if (not WireGuardInstalled) and (not WizardSilent) then
    MsgBox('WireGuard could not be installed automatically. NOBAD VPN will offer to install it when it starts.',
           mbInformation, MB_OK);
end;
