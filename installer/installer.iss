; Paper Review Automation — Inno Setup installer script.
;
; Build with (after `py -m PyInstaller installer\paper_review_automation.spec
; --distpath dist --workpath build --noconfirm` has produced dist\PaperReviewAutomation\):
;
;     ISCC.exe installer\installer.iss
;
; Per-user install (PrivilegesRequired=lowest) — no admin rights, no UAC
; prompt. Program files live under %LOCALAPPDATA%\Programs\PaperReviewAutomation;
; user data (config.toml, state\, logs\) lives separately under
; %USERPROFILE%\PaperReviewAutomation — see paper_automation/config.py's
; _default_base_dir(). Uninstall always removes the program-files half, and
; re-running a newer installer over an existing one (Inno Setup's built-in
; upgrade-in-place behaviour) always replaces the exes while leaving
; accounts/job history/config alone. The data folder is a separate choice
; at uninstall time (MaybeDeleteDataFolder, [Code] section below) — asked,
; defaulting to No, never deleted silently, since it holds real
; unrecoverable data (accounts, job history, saved backups). The research
; papers folder itself is never touched either way.

#define MyAppName "Paper Review Automation"
; Single source of truth: paper_automation/__init__.py reads this same file
; at runtime, so the installer version and the running app's version can
; never drift apart.
#define MyAppVersion Trim(FileRead(FileOpen(SourcePath + "..\VERSION")))
#define MyAppPublisher "iMatiz"
#define MyAppExeName "PaperReviewAutomation.exe"
#define DistDir "..\dist\PaperReviewAutomation"

[Setup]
AppId={{6E6F5C6D-6F6E-4B0A-9B7F-5B6D1B0C9F1A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Must match tray_app.py's _APP_MUTEX_NAME exactly — lets Setup detect the
; tray is running during an upgrade and offer to close it first, instead of
; failing to overwrite the locked exes.
AppMutex=PaperReviewAutomation_AppMutex
DefaultDirName={localappdata}\Programs\PaperReviewAutomation
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputBaseFilename=PaperReviewAutomation-Setup-{#MyAppVersion}
OutputDir=..\dist\installer
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\webui\static\tray.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; Not code-signed (see CLAUDE.md / project plan) — Windows SmartScreen may
; warn on first run until a certificate is added later.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Everything PyInstaller's COLLECT step produced — the five exes plus their
; shared runtime/DLLs and bundled webui templates/static/models.json/config.example.toml.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; IconFilename must point at the INSTALLED copy, not the source tree.
; PyInstaller's default layout nests every bundled data file (including
; webui/static/) under {app}\_internal\ — pointing this at {app}\webui\...
; (without _internal) resolves to nothing, so Windows silently falls back
; to a generic icon instead of erroring. Confirmed by checking the actual
; dist folder, not assumed.
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Parameters: "--open"; WorkingDir: "{app}"; \
    IconFilename: "{app}\_internal\webui\static\tray.ico"; \
    Comment: "Open the Paper Review Automation dashboard"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Parameters: "--open"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; First-run setup wizard: papers folder, timezone, first admin account.
; "runascurrentuser" is the default for a lowest-privilege install; skipifsilent
; keeps a fully unattended /VERYSILENT install from blocking on a GUI prompt
; (an admin can still run FirstRunSetup.exe by hand afterwards in that case).
; Check: FirstRunNeeded skips this on an upgrade — config.toml already
; existing means an admin account already exists, so re-running the wizard
; would just hit auth.AuthError on a duplicate username.
Filename: "{app}\FirstRunSetup.exe"; Description: "Run first-time setup"; \
    Flags: postinstall skipifsilent nowait; Check: FirstRunNeeded

[UninstallDelete]
; Explicitly scoped to the program-files install directory only — Inno Setup's
; default uninstall already limits itself to {app}, but this is spelled out so
; it's obvious on review that the data folder below is deliberately absent
; from every [UninstallDelete]/[UninstallRun] entry in this script.
Type: filesandordirs; Name: "{app}"

[Code]
const
  TaskNameRun = 'ResearchPaperAutomation';
  TaskNameTray = 'ResearchPaperAutomationTray';

// Data folder (config.toml, state\, logs\) lives under %USERPROFILE%\
// PaperReviewAutomation regardless of install/upgrade — matches
// paper_automation/config.py's _default_base_dir().
function DataDir(): String;
begin
  Result := ExpandConstant('{%USERPROFILE%}\PaperReviewAutomation');
end;

// Its existence means an admin account already exists, so the first-run
// wizard should be skipped.
function FirstRunNeeded(): Boolean;
begin
  Result := not FileExists(DataDir() + '\config.toml');
end;

// Simple line-scan for research_papers_root — no TOML parser needed, and
// this only ever needs one key. Returns '' if config.toml is missing or
// the key isn't found.
function ResearchPapersRoot(): String;
var
  ConfigPath, Line, Value: String;
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  ConfigPath := DataDir() + '\config.toml';
  if not FileExists(ConfigPath) then
    Exit;
  if not LoadStringsFromFile(ConfigPath, Lines) then
    Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    Line := Trim(Lines[I]);
    if Copy(Line, 1, Length('research_papers_root')) = 'research_papers_root' then
    begin
      Value := Line;
      Delete(Value, 1, Pos('"', Value));
      Value := Copy(Value, 1, Pos('"', Value) - 1);
      Result := Value;
      Exit;
    end;
  end;
end;

// The hard "never delete client folders" rule (see tests/test_safety.py on
// the Python side) extends to this installer script too: refuse to even
// offer deleting the data folder if research_papers_root was ever pointed
// inside it. Should never happen with the default setup, but costs nothing
// to guard against, and a silent, unconditional wipe is exactly what this
// rule exists to prevent.
function DataFolderSafeToDelete(): Boolean;
var
  Root, Data: String;
begin
  Root := ResearchPapersRoot();
  if Root = '' then
  begin
    Result := True;
    Exit;
  end;
  // config.toml always stores this path with forward slashes (see
  // service.update_config_file/_write_config, both of which normalize to
  // "/" on write) while DataDir() below is native Windows backslashes —
  // without normalizing first, this prefix check would silently never
  // match, making the guard a no-op exactly when it matters most.
  StringChangeEx(Root, '/', '\', True);
  Data := DataDir();
  Result := (Pos(Lowercase(Data) + '\', Lowercase(Root) + '\') <> 1);
end;

// Uninstall only ever removes program files (see [UninstallDelete]) unless
// the person uninstalling explicitly asks for the data folder too — never
// a silent default, since it holds real, unrecoverable data: accounts,
// job history, saved prompts, and state\backups\ (the safety net
// "py run.py --backup-now" writes). Defaults to No (MB_DEFBUTTON2): a
// destructive default-Yes on a dialog people click through fast is exactly
// what this project's own "no silent pruning" convention warns against.
procedure MaybeDeleteDataFolder();
var
  Data: String;
begin
  // A silent/unattended uninstall (/SILENT, /VERYSILENT) must never delete
  // data or hang waiting on a dialog nobody is there to answer — same
  // "never silent" rule as the confirmation itself, just applied earlier.
  if UninstallSilent() then
    Exit;

  if not DataFolderSafeToDelete() then
    Exit;

  Data := DataDir();
  if not DirExists(Data) then
    Exit;

  if MsgBox(
    'Also permanently delete your accounts, settings, and job history?' + #13#10 + #13#10 +
    'This removes ' + Data + ', including saved backups.' + #13#10 +
    'Your research papers folder is never touched.' + #13#10 + #13#10 +
    'This cannot be undone.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    DelTree(Data, True, True, True);
  end;
end;

procedure RegisterScheduledTasks();
var
  ResultCode: Integer;
  RunExe, TrayExe, Cmd: String;
begin
  RunExe := ExpandConstant('{app}\paper-review-run.exe');
  TrayExe := ExpandConstant('{app}\PaperReviewAutomation.exe');

  // Daily 09:00 run (Task Scheduler fires in machine local time; the pipeline
  // itself decides "current month" using config.toml's timezone — see
  // scripts/register_task.ps1, which this mirrors for the installed exe).
  Cmd := Format('/Create /F /SC DAILY /ST 09:00 /TN "%s" /TR "\"%s\""', [TaskNameRun, RunExe]);
  Exec(ExpandConstant('{sys}\schtasks.exe'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  // Logon autostart for the tray icon (mirrors scripts/register_tray_autostart.ps1).
  Cmd := Format('/Create /F /SC ONLOGON /TN "%s" /TR "\"%s\""', [TaskNameTray, TrayExe]);
  Exec(ExpandConstant('{sys}\schtasks.exe'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure UnregisterScheduledTasks();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /F /TN "' + TaskNameRun + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /F /TN "' + TaskNameTray + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RegisterScheduledTasks();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    UnregisterScheduledTasks();
  // Asked only after program files are already gone, so canceling the data
  // question never leaves a half-finished uninstall.
  if CurUninstallStep = usPostUninstall then
    MaybeDeleteDataFolder();
end;
