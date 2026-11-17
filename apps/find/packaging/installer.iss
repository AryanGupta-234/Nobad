; Inno Setup 6 script for NOBAD Find. Build:  iscc /DMyAppVersion=0.1.0 packaging\installer.iss   (build.ps1 does this)
; Per-user install without admin rights: NOBAD Find runs as the normal user, so it installs like one, into
; %LOCALAPPDATA%\Programs\NOBAD Find, with a Start menu shortcut for this user only.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "NOBAD Find"
#define MyAppExe "NobadFind.exe"

[Setup]
AppId={{A8A5690D-F9AF-4028-8E58-6D29BA8ECF84}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=NOBAD
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoCompany=NOBAD
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\NOBAD Find
DisableDirPage=yes
DefaultGroupName=NOBAD Find
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist-installer
OutputBaseFilename=NobadFind-Setup-{#MyAppVersion}
SetupIconFile=nobadfind.ico
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
Source: "..\dist\NobadFind\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; AppUserModelID: "NOBAD.Find"
; No "start with Windows" option here: NOBAD Find has its own setting for that.

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Runs after CurUninstallStepChanged(usUninstall) below has stopped NOBAD Find. It puts Windows Search back the way
; it was if NOBAD Find turned it off (Windows may ask for permission once) and removes NOBAD Find's own
; start-with-Windows entry. Uninstall waits for it.
Filename: "{app}\{#MyAppExe}"; Parameters: "--uninstall"; Flags: waituntilterminated; RunOnceId: "NobadFindUninstall"

[UninstallDelete]
; Anything created inside the program folder at run time (the folder itself goes too).
Type: filesandordirs; Name: "{app}"

[Code]
const
  INVALID_FILE_ATTRIBUTES = $FFFFFFFF;     // FILE_ATTRIBUTE_REPARSE_POINT is built into Inno Setup

function GetFileAttributes(lpFileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

// ---------------------------------------------------------------- stop NOBAD Find (install, upgrade, uninstall)
// Only this user's copies: the name filter is Windows' own user name (it can't contain a quote), and taskkill is
// started directly, never through a shell. First a normal close request, then forced; /T takes the text-reading
// worker processes with it. Run twice to catch a copy started meanwhile.
procedure StopFind;
var
  rc: Integer;
  tk, user, args: String;
begin
  user := GetUserNameString;
  if (user = '') or (Pos('"', user) > 0) then
    Exit;
  tk := ExpandConstant('{sys}\taskkill.exe');
  args := '/IM {#MyAppExe} /T /FI "USERNAME eq ' + user + '"';
  Exec(tk, args, '', SW_HIDE, ewWaitUntilTerminated, rc);
  Sleep(1200);
  Exec(tk, '/F ' + args, '', SW_HIDE, ewWaitUntilTerminated, rc);
  Sleep(500);
  Exec(tk, '/F ' + args, '', SW_HIDE, ewWaitUntilTerminated, rc);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  StopFind;                          // so files in use never block an upgrade
end;

// True only for a real folder (not a link or junction that could point somewhere else).
function IsPlainDir(Path: String): Boolean;
var
  a: Cardinal;
begin
  a := GetFileAttributes(Path);
  Result := (a <> INVALID_FILE_ATTRIBUTES) and ((a and FILE_ATTRIBUTE_REPARSE_POINT) = 0) and DirExists(Path);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  base, data: String;
begin
  if CurUninstallStep = usUninstall then
    StopFind;                        // before [UninstallRun] runs NobadFind.exe --uninstall
  if CurUninstallStep = usPostUninstall then
  begin
    StopFind;
    base := ExpandConstant('{localappdata}\NOBAD');
    data := base + '\Find';
    if (not UninstallSilent) and IsPlainDir(base) and IsPlainDir(data) then
      if MsgBox('Also delete your NOBAD Find search index and settings?' + #13#10 + #13#10 +
          'They are in ' + data + '. Your own files are not touched.' + #13#10 +
          'Choose No to keep them for a later reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        // DelTree removes links and junctions inside the folder without following them.
        DelTree(data, True, True, True);
        RemoveDir(base);             // only when nothing else of NOBAD's is left in it
      end;
  end;
end;
