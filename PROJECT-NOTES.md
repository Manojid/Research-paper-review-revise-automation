# Project Notes — Version 1 Reference

Reference doc for continuing work without re-exploring the codebase. Factual,
not narrative. Does not repeat what's already in `CLAUDE.md` (conventions,
account lifecycle, provider design, failure classification, etc. — read that
first) or `ROADMAP.md` (phase-by-phase feature history).

## 1. What's been built

| Area | Where | Notes |
|---|---|---|
| Core pipeline | `paper_automation/` | scanner, phases, config, state (SQLite), providers, prompts, docx_io, validation, usage, notify, backup, fingerprint, model_registry, auth, service |
| Web control panel | `webui/` (`app.py`, `templates/`, `static/`) | Flask + Flask-Login + waitress |
| CLI entry points | `run.py`, `ui.py`, `manage_users.py`, `tray_app.py` | each is independently runnable via `py <file>.py` |
| Portable installer | `installer/` (`paper_review_automation.spec`, `first_run_wizard.py`, `installer.iss`) | PyInstaller + Inno Setup, built this session |
| Version tracking | `VERSION` (repo root), read by `paper_automation/__init__.py` and `installer.iss` | single source of truth, added this session |
| Tests | `tests/` | 581 passing, no network/login needed |
| Docs | `README.md`, `CLAUDE.md`, `ROADMAP.md`, `docs/*.docx` | `docs/Paper_Review_Automation_Demonstration.docx` is a non-technical/technical walkthrough built this session |
| Version control | GitHub, private repo `manojimatiz/paper-review-automation` | tag `v1.0.0`, Release with the compiled installer attached as an asset |

Live production config on the dev machine: `research_papers_root` currently
points at `Papers/` **inside this same project folder** (not a separate
location) — see §5, this is a structural risk, not a design recommendation.

## 2. Key architectural decisions (this session, not already in CLAUDE.md)

- **MANAGER role dropped.** Originally planned as ADMIN/MANAGER/User; the
  user corrected this mid-design ("I said manager by mistake, only admin
  and user is enough") before any code was written. Only `Role.ADMIN` and
  `Role.WRITER` exist. Don't reintroduce a third role without a real need.
- **Account deletion is real and permanent**, reversing the original
  disable-only design, per explicit user request ("remove the existing
  users..."). Guarded so the last active Admin can't be deleted (would
  either revert to implicit-local-admin mode or strand User accounts with
  nobody able to reach `/users`).
- **Tray/service is subprocess-based, not in-process threading.**
  `tray_app.py`'s `ServerController` spawns `ui.py` (or, when frozen, the
  sibling `PaperReviewAutomationService.exe`) as a child process; Stop is
  `Popen.terminate()`. Chosen deliberately for simplicity — an
  interrupted run recovers the same way a crash already does
  (`requeue_stale_processing_jobs()`), so no graceful-shutdown plumbing
  was built. Trade-off: an in-flight review/revision is cut off rather
  than finishing first when Stop is clicked.
- **Portable installer: five separate frozen executables sharing one
  PyInstaller runtime**, not one multiplexed exe with a `--mode` flag.
  The codebase already had four clean entry points (`run.py`, `ui.py`,
  `tray_app.py`, `manage_users.py`) plus the new `first_run_wizard.py`;
  building each as its own `Analysis`/`EXE` block and merging them with
  `MERGE()` keeps each exe's console/windowed subsystem correct
  (`run`/`manage_users` keep a console; `ui`/`tray`/`wizard` are windowed)
  without inventing self-relaunch logic.
- **First-run wizard is Tkinter (stdlib), not Inno Setup Pascal Script.**
  It runs as a real Python process with `paper_automation` importable, so
  it calls `auth.create_user()` directly — the exact function `/users`
  and `manage_users.py add` already use — instead of duplicating
  account-creation logic in a second language.
- **Installer is per-user, no admin rights** (`PrivilegesRequired=lowest`
  in `installer.iss`), installing to `%LOCALAPPDATA%\Programs\...`. Avoids
  a UAC prompt; Task Scheduler registration for the current user (no
  "highest privileges") doesn't need elevation either.
- **Program files and data folder are separate from day one**: program
  files under `%LOCALAPPDATA%\Programs\PaperReviewAutomation`; data
  (`config.toml`, `state\`, `logs\`) under `%USERPROFILE%\PaperReviewAutomation`
  — matching the existing, already-proven `DEFAULT_SCRATCH` home-folder
  placement in `config.py` (Codex's sandbox rejects `AppData` paths). This
  is what makes upgrade-in-place safe: Inno Setup's fixed `AppId` lets a
  newer installer replace program files without ever touching accounts,
  job history, or config.
- **Code signing deliberately skipped for v1.** Accepts the SmartScreen
  "unknown publisher" warning; reversible later without touching the app.
- **`VERSION` file is the single source of truth for the version string**,
  read by `paper_automation/__init__.py` at runtime (frozen-aware, same
  `sys.frozen`/`sys._MEIPASS` pattern as `config.py`) and by
  `installer.iss` at compile time via Inno Setup Preprocessor's
  `FileRead(FileOpen(...))`. Bump this one file, not two.
- **GitHub repo is private.** Code comments and folder-naming conventions
  reflect real business logic, not meant for public visibility. The
  compiled installer is a Release **asset**, never committed to git
  history (binaries don't belong in version-controlled source).

## 3. Tricky bugs hit and fixed (don't reintroduce)

- **Console flash on Dashboard/Settings/Jobs clicks.** Root cause:
  `service.py`'s `_schtasks()`/`set_schedule()` and
  `subprocess_provider.py`'s three `subprocess.run()` calls didn't pass
  `creationflags=subprocess.CREATE_NO_WINDOW`, so Windows briefly opened
  a console for every `schtasks.exe`/`powershell.exe`/CLI invocation from
  the windowless (`pythonw.exe`) web process. **First hypothesis was
  wrong** — assumed it was the tray's own subprocess spawning; a
  clarifying question revealed it was dashboard page loads, not the tray.
  Fixed by adding the flag at every affected call site, including a
  defensive addition in `tray_app.py` itself. Any *new* `subprocess.run`/
  `Popen` call in this codebase needs the same `_CREATE_NO_WINDOW`
  constant or it will silently reintroduce the flash.
- **PyInstaller pulled in ~950MB of unrelated packages** (torch, pandas,
  scipy, pyarrow, matplotlib, jedi, zmq...) on the first build, because
  this dev machine's site-packages also holds an unrelated data-science/
  Jupyter stack and PyInstaller's static analysis bundles anything
  reachable. Fixed with an explicit `COMMON_EXCLUDES` list in
  `paper_review_automation.spec` — cut the build to 89MB. Harmless to
  keep on a clean machine; necessary on this one. If a rebuild balloons
  in size again, check for new unrelated imports before assuming it's a
  real new dependency.
- **`packaging/` directory name collided with the pip `packaging`
  library** (a transitive dependency of PyInstaller/setuptools) — a
  `from packaging.X import Y`-style import silently resolved to the
  installed pip package instead of the project's own folder. Renamed the
  directory to `installer/`. Don't name a project directory `packaging`.
- **Real client data almost got committed to git.** `Papers/` (the actual
  `research_papers_root`, containing real client manuscripts/reviews)
  lives inside this project folder and was staged by an initial
  `git add -A` before `.gitignore` had a rule for it — caught by reviewing
  `git status` before committing, not by any automated check. Two other
  stray files (`py`, `would` — empty, accidental shell-redirect artifacts
  from an earlier session) were caught the same way. **`.gitignore` now
  excludes `Papers/`, `dist/`, `build/`, `/py`, `/would`, and Claude
  Code's own local session files** — always review `git status --short`
  line-by-line before the first commit in a repo that's been worked in
  interactively for a while, don't trust `.gitignore` alone until it's
  been checked against actual `git status` output.
- **Two test mocks broke** (`test_tray_app.py`) after `creationflags` was
  added to `subprocess.Popen()` calls — `def fake_popen(args, cwd=None)`
  and a lambda with the same signature didn't accept the new kwarg. Fixed
  by adding `**kwargs`. Any mock of a `subprocess.Popen`/`subprocess.run`
  call site in tests needs `**kwargs` to stay resilient to new flags.

## 4. Approaches tried and abandoned

- **Single multiplexed frozen exe with a `--mode run|ui|tray` flag** —
  considered, rejected in favor of five separate exes from one shared
  spec (`MERGE()`). Simpler, and avoids writing self-relaunch logic when
  the existing codebase already had clean separate entry points.
- **A third "MANAGER" role** — explicitly rejected by the user after
  initially being included in an early design pass; never implemented.
- **Automatic true self-update** (background download + swap) — discussed
  as one of three update-story options, rejected as disproportionate
  engineering (needs a separate updater process + rollback handling) for
  a small internal-tool user base. "Re-run a new installer" was chosen
  instead. Revisit only if install count grows significantly.
- **Automatic log/backup pruning** — deliberately rejected. The project's
  no-delete invariant (`tests/test_safety.py`'s AST check) is treated as
  load-bearing everywhere; carving out a "housekeeping" exception was
  judged to be exactly the kind of quiet erosion that invariant exists to
  prevent. Old logs/backups are left for a human to clear by hand.
- **A `/jobs` "Retry" button** — considered and explicitly left out; needs
  a worker pool consuming a genuinely persistent cross-run queue, which
  Phase 4 stopped short of building. Don't wire up a retry action without
  that underlying change first.

## 5. Current known issues / tech debt

- **First-run wizard skip on upgrade — fixed in v1.0.1.**
  `installer.iss`'s `[Run]` line now carries `Check: FirstRunNeeded`
  (`installer.iss`'s `[Code]` section), which returns `False` when
  `%USERPROFILE%\PaperReviewAutomation\config.toml` already exists.
  **Not live-tested end to end** — no Windows-desktop-automation tool was
  available in the session that built it, so only the compile step was
  verified; a real fresh-install-then-upgrade click-through is still
  worth doing once.
- **`AppMutex` — fixed in v1.1.0.** `installer.iss`'s `[Setup]` now sets
  `AppMutex=PaperReviewAutomation_AppMutex`, matching a named mutex
  `tray_app.py`'s `run_tray()` acquires via stdlib `ctypes` →
  `kernel32.CreateMutexW` (no new dependency; `pywin32` was deliberately
  avoided — see §6). **Known residual gap**: this lets Setup detect and
  offer to close the *tray* process, but doesn't cascade to killing the
  child `PaperReviewAutomationService.exe` if the tray is force-killed
  rather than exiting through `quit_app()` — same accepted trade-off
  class as "Stop = `Popen.terminate()`" below, not a regression.
- **Installer is unsigned** — SmartScreen shows an "unknown publisher"
  warning on first run. Deliberate for v1; revisit if it becomes a real
  adoption blocker.
- **The `v1.0.0` git tag was force-moved once**, after the version-display
  feature was added post-hoc and the user asked to fold it into "version
  1" rather than cut a new tag. This is unconventional (tags are normally
  treated as immutable once published) and was judged low-risk only
  because the repo was brand new and single-user. **Any future change
  should get a real version bump** — demonstrated since: `v1.0.1` (the
  first-run wizard fix) and `v1.1.0` (AppMutex + the API provider mode
  below), no further forced tag moves.
- **API-mode provider toggle — built in v1.1.0.** `provider_mode = "api"`
  is a new alternative to the CLI-subscription providers: `Settings` page
  toggle (`webui/templates/settings.html`) → `AnthropicApiProvider` /
  `OpenAiApiProvider` (`paper_automation/providers/api_provider.py`),
  same review/revision role split as Codex/Claude today
  (`providers/__init__.py`'s `build_providers`). Key design points, since
  they deliberately override or extend existing documented decisions:
  - **API keys are entered through the browser Settings form** — a
    narrow, explicit exception to `settings.html`'s otherwise-real
    "no secrets in a browser form" principle (see the "Not editable
    here" panel), accepted by the user for this one case. Mitigated by
    never writing the key to `config.toml`: it's stored in Windows
    Credential Manager (DPAPI, per-user) via the new `keyring` dependency
    and `paper_automation/secrets_store.py`, fetched by `ApiProvider`
    only at call time, never held on `Config`/`ProviderConfig` or logged.
  - **`keyring` is a required dependency**; the `anthropic`/`openai` SDKs
    themselves are deliberately NOT — `api_provider.py` imports them
    lazily and raises a clear `pip install` error if missing and API mode
    is actually used, so an install that never turns this on carries no
    extra weight (same minimalism `requirements.txt`'s header already
    asks for).
  - **`provider_mode` was previously not read from `config.toml` at all**
    (`Config`'s dataclass default silently applied); `config.py` now has
    `_validated_provider_mode()` (mirroring `_validated_task_mode`) and
    actually wires the TOML value through.
  - **Not done in this pass** (flagged, not silently skipped, per the
    standing "flag security concerns per phase" convention): no key
    rotation plan, no enforcement of a scoped/least-privilege key, and no
    separate low-limit key for `--test-mode` runs. API access is billed
    per-token, separate from and in addition to the Codex/Claude
    subscriptions — a real cost once an admin turns this on.
  - **PyInstaller risk carried forward, not yet verified with a live
    frozen-build smoke test**: `keyring`'s Windows backend needs
    `keyring.backends.Windows` / `win32ctypes.pywin32` /
    `win32ctypes.core` in `COMMON_HIDDENIMPORTS`
    (`installer/paper_review_automation.spec`) — added, but "save a key
    from Settings, restart the frozen exe, confirm it round-trips" has
    not actually been run yet.
- **`Papers/` (real client data) lives inside the git-tracked project
  folder**, relying entirely on `.gitignore` to keep it out of version
  control. Structurally fragile — a `.gitignore` mistake, a force-add, or
  a new contributor unaware of the convention could recommit it. Worth
  relocating `research_papers_root` outside the project directory
  entirely, independent of any code change.
- **No in-app "check for updates."** An admin has no way to know a newer
  version exists short of checking GitHub manually.
- **`tests/test_pipeline.py`'s concurrency tests are intermittently
  flaky** — noticed during v1.5.0's verification: a full `pytest` run
  failed a different one of
  `test_concurrent_run_still_finishes_all_reviews_before_any_revision` /
  `test_concurrent_processing_does_not_mix_up_papers` on two separate
  full-suite runs (`sqlite3.InterfaceError: bad parameter or other API
  misuse`, then a plain `IndexError`), both passing cleanly in isolation
  immediately after. Not caused by anything in v1.5.0 (no pipeline/
  threading/state.py code touched that session) — pre-existing, just not
  previously noticed/recorded. Likely shared mutable state across threads
  in the `max_concurrent_jobs > 1` test scenarios (a `MockProvider`
  instance, or a single `sqlite3` connection, touched from more than one
  worker thread without the lock `_process_folder` uses for its own
  writes). Worth a real look before trusting concurrent mode
  (`max_concurrent_jobs > 1`) in production — not investigated further
  this session, flagged rather than silently reported as "all green."
- **App icon rebranded — done in v1.1.1.** The old `webui/static/tray.ico`
  was literally `tray_app.py`'s own system-tray status glyph (a flat
  green circle + plain rectangle) saved as a file and reused everywhere —
  it didn't match the web UI's actual brand (indigo→violet gradient,
  `--accent: #4f46e5` → `#8b5cf6` in `style.css`, used on every primary
  button and the topbar `.brand-mark`). Also, **none of the five compiled
  exes had an `icon=` set at all** in
  `installer/paper_review_automation.spec`'s `build_exe()` — Explorer/
  taskbar were showing PyInstaller's bootloader default, not even the old
  green circle. Replaced with a proper multi-res `.ico`
  (16/24/32/48/64/128/256, the old one only had 16/32/48/64): a
  rounded-square badge in the real brand gradient, a folded-corner
  document glyph, and a soft drop shadow — generated with Pillow only
  (already a dependency, no new one added for a one-off asset script).
  Wired into: `build_exe()`'s `icon=` (all 5 exes), `installer.iss`'s new
  `SetupIconFile` (the installer program's own icon, previously unset
  too), `tray_app.py`'s `_icon_image()` (redrawn with the same glyph,
  pure PIL/no numpy since that one runs in the live app — status color
  green/gray is still the functional running-indicator, unchanged), and
  the browser favicon. **The favicon fix required editing four template
  files, not one** — `login.html`, `signup.html`, and `account.html` each
  have their own standalone `<head>` with a duplicate favicon `<link>`
  (they don't `{% extends "base.html" %}` for their unauthenticated/
  forced-password-change states), a duplication worth knowing about
  before assuming `base.html` is the only place head content lives.
  - **Desktop shortcut still showed a generic icon — fixed in v1.3.2.**
    `installer.iss`'s `[Icons]` `IconFilename` pointed at
    `{app}\webui\static\tray.ico`, which doesn't exist post-install —
    PyInstaller's default layout nests every bundled data file (including
    `webui/static/`) under `{app}\_internal\`, confirmed by actually
    listing the built `dist\PaperReviewAutomation\` folder rather than
    assuming. Windows silently falls back to a generic icon when a
    shortcut's `IconFilename` doesn't resolve — no error, no warning,
    just the placeholder the user saw. Fixed to
    `{app}\_internal\webui\static\tray.ico`. `SetupIconFile` (line 43,
    build-time, resolved against the source tree) and
    `UninstallDisplayIcon={app}\{#MyAppExeName}` (points at the exe
    directly, whose icon is embedded via PyInstaller's `icon=` at build
    time) were never affected — this was specifically a runtime-path bug
    in the one `IconFilename` directive. **Same `_internal\` gotcha would
    bite any future `installer.iss` change that references a bundled
    data file by an `{app}`-relative path** — check the actual dist
    folder layout, don't assume `{app}\<source-relative-path>` still
    holds under PyInstaller's current default `contents-directory`
    behavior.
  - **The same `_internal\` blind spot broke far more than the icon —
    fixed in the same v1.3.2, once a real install surfaced it.**
    `webui/app.py`'s `BASE_DIR = Path(__file__).resolve().parent.parent`
    had **no frozen-awareness gate at all** (unlike every sibling
    `BASE_DIR`/`_default_base_dir()` elsewhere in this codebase — config.py,
    `__init__.py`, tray_app.py all have one; this one was simply missed).
    In the frozen build this resolved to
    `{app}\_internal\webui` → `.parent.parent` = `{app}\_internal`, not
    `{app}` and nowhere near the real data folder
    (`%USERPROFILE%\PaperReviewAutomation`). Every route using `BASE_DIR`
    directly broke with `FileNotFoundError` — **Settings save**, the
    model registry (`registry_path`), and the schedule toggle — while
    `current_config()` and the dashboard kept working fine, because
    `current_config()` calls `config_module.load()` with no arguments,
    which already goes through `config.py`'s own correctly-gated
    `_default_base_dir()`. That split (`current_config()` fine, several
    other routes broken) is exactly why the dashboard rendered correctly
    while Settings' save button threw. Fixed by extracting
    `webui/app.py`'s own `_default_base_dir()`, mirroring `config.py`'s
    pattern exactly (`Path.home() / "PaperReviewAutomation"` when frozen).
    New regression test: `tests/test_webui.py::test_base_dir_is_frozen_aware`.
    **Neither of these two bugs was caught by the test suite before a
    real install surfaced them** — every existing webui test uses the
    `client` fixture, which monkeypatches `current_config`/`config_module.load`
    directly and never exercises frozen-mode `BASE_DIR` resolution at
    all. Worth remembering next time something "only breaks in the
    installed app, not in tests."
- **First-run wizard onboarding step — added in v1.2.0.**
  `installer/first_run_wizard.py`'s single flat Tkinter form is now two
  in-place steps in the same window: step 1 (papers folder, timezone,
  admin account) unchanged and still mandatory; step 2 is new and
  entirely optional — first month/employee folder creation
  (`service.create_employee_folder`, the same function `/api/create-folder`
  uses) and a CLI-vs-API `provider_mode` choice (`service.update_config_file`,
  the same function the Settings page uses), with a "Skip this step"
  button that leaves everything exactly as step 1 left it. No API keys
  are collected in the wizard — CLI choice shows the exact sign-in
  commands from `README.md` (`codex login`, `claude`); API choice just
  points at the Settings page, consistent with `secrets_store.py`'s
  keyring-only key storage.
  - **Found and fixed a real, previously-untested bug in
    `service.update_config_file()`** while wiring this up: its
    insert-if-absent path (for a key like `provider_mode` that predates
    `config.example.toml` having a line for it) used a `for...else` whose
    `else` never ran, because the loop's `break` on hitting the first
    `[table]` header (present in every real `config.toml`, e.g.
    `[providers.codex]`) always fired before falling through to `else`
    — so an absent top-level key was silently never inserted, no error,
    just quietly dropped. This affected the **web Settings page too**,
    not just the wizard: saving `provider_mode` for the first time on any
    config.toml that predates that key (i.e. every real install today)
    would have silently no-opped. Fixed by searching/inserting only
    within the pre-first-table region directly rather than relying on
    `for...else`. Added `test_editing_inserts_an_absent_key_before_the_first_table`
    (`tests/test_service.py`) — no such "key absent, must insert" case
    was tested before, only "key present, update in place."
- **Onboarding v2 — done in v1.3.0.** Follow-up on the wizard above, after
  actually clicking through it:
  - **DPI-awareness, added from scratch.** Nothing in this codebase had
    any before (`tray_app.py` included) — `first_run_wizard.py` now calls
    `ctypes.windll.shcore.SetProcessDpiAwareness(1)` (with a
    `SetProcessDPIAware()` fallback) before `Tk()` is constructed, plus
    `self.tk.call('tk', 'scaling', dpi / 72)` using the real screen DPI
    (`GetDeviceCaps(hdc, LOGPIXELSX)`). The blur was Windows
    bitmap-scaling a non-DPI-aware window — this is the first DPI-aware
    code anywhere in the project; reuse this pattern for any future
    Tkinter surface rather than reinventing it.
  - **Timezone is now a dropdown** (`ttk.Combobox`, `zoneinfo.available_timezones()`),
    pre-selected via the new `tzlocal` dependency's `get_localzone_name()`.
    Discovered along the way: **`tzdata` was already installed and already
    silently bundled into the frozen build** (PyInstaller's own hook
    picked it up) — it just wasn't declared in `requirements.txt`, working
    by accident of what else happened to be on this dev machine, not by
    design. Now declared explicitly, both there and in the spec's
    `COMMON_HIDDENIMPORTS`.
  - **Wizard is now three steps**, not two: account (mandatory) → folder
    (optional, now with an explanation of the `<Papers folder>/<Month
    Year>/<Employee>/<Client>` structure before the input, not just a
    bare field) → CLI/API choice (optional). The closing dialog no longer
    tells the user to open a terminal — it points at Settings, where
    sign-in now actually happens (next point).
  - **Real "Sign in" from Settings — `service.open_cli_login()`.** This
    is the **first and only place in this codebase that spawns a visible
    console** (`subprocess.CREATE_NEW_CONSOLE`) — every other subprocess
    call everywhere else deliberately hides its console
    (`_CREATE_NO_WINDOW`). Justified because codex/claude login is
    inherently interactive (browser OAuth / terminal prompts) and there
    is no way to complete it from a windowless web process. Codex gets
    `codex login`; Claude gets bare `claude` (no separate login-only
    subcommand is documented — the console drops into Claude Code's full
    interactive session after a successful sign-in, which the Settings
    page's copy calls out rather than hides).
  - **"Not ready" banners — corrected to proactive in v1.3.1, see below.**
    Originally shipped reactive-only for CLI mode (below), fixed once a
    real proactive signal was actually found.
- **CLI sign-in banner made proactive — v1.3.1, correcting v1.3.0.**
  v1.3.0 shipped the CLI-mode banner as reactive-only (`last_auth_failure()`)
  because investigation at the time concluded there was no way to check
  "is Codex/Claude logged in right now." **That conclusion was wrong** —
  running the actual binaries by hand (not guessed) found both have a
  real, fast, non-interactive status subcommand:
  - `codex login status` → exit 0, prints to **stderr** (not stdout —
    caught by testing, would have silently misclassified as "unknown"
    otherwise) `Logged in using ChatGPT`.
  - `claude auth status` → exit 0, JSON on stdout: `{"loggedIn": true,
    "authMethod": ..., "email": ..., "orgId": ..., ...}`. **Only
    `loggedIn` is ever extracted** — the rest of that payload (account
    email, org name, subscription tier) must never be logged, cached, or
    displayed anywhere in this app.
  - New `service.cli_signed_in(provider_name, provider_cfg) -> bool | None`,
    cached the same TTL-dict pattern as `cli_version()` (a real subprocess
    spawn, must not fire on every page load). Returns `None` — never a
    guessed `False` — on anything ambiguous: missing binary, timeout,
    unparseable output, non-zero exit. `model_status()`'s new
    `signed_in: {"codex": bool|None, "claude": bool|None}` (empty dict in
    API mode) replaced the old `cli_auth_failed` field.
  - `dashboard.html`/`settings.html`'s CLI-mode banner condition is now
    `models.signed_in.codex is sameas false or models.signed_in.claude is
    sameas false` — Jinja's `is sameas false` (not a truthy check) is
    required here specifically to keep `None` from being treated as
    `False`.
  - `last_auth_failure()` **was kept, deliberately, per explicit
    instruction** even though nothing calls it anymore — earmarked for a
    possible future "why did my last run fail" detail view. Don't delete
    it as unused-code cleanup without checking back on that.
  - New `.good-text { color: var(--done); }` in `style.css`, mirroring
    the existing `.bad-text` — used for the per-stage "Signed in."/"Signed
    out." status text in Settings' Models section, next to each CLI's new
    "Sign in" button.
- **Uninstall can now optionally wipe the data folder too — v1.4.0.**
  Previously uninstall only ever removed program files, unconditionally
  and undiscussed — deliberate, per the top-of-file comment. Changed
  because a real user asked "why does my account survive a
  reinstall" and then explicitly wanted a true clean uninstall. Not a
  silent default, though — `state\backups\` is a safety net
  (`py run.py --backup-now`), and CLAUDE.md's own standing rule flags
  "log/backup pruning ... without discussing first," so this is a
  confirmation dialog (`MaybeDeleteDataFolder()` in `installer.iss`'s
  `[Code]` section, run at `usPostUninstall`), defaulting to **No**
  (`MB_DEFBUTTON2`), not an unconditional wipe.
  - **Guard against ever deleting `research_papers_root`**, even if
    someone pointed it inside the data folder (shouldn't happen with the
    default setup, but the hard "never delete client folders" rule
    — AST-enforced on the Python side by `tests/test_safety.py` —
    deserves the same paranoia in installer Pascal code, which isn't
    covered by that AST check at all). `ResearchPapersRoot()` line-scans
    `config.toml` (no TOML parser available in Pascal Script) and
    `DataFolderSafeToDelete()` checks whether the data folder is a
    prefix of that path.
  - **Real bug caught before shipping, not after**: the first version of
    that prefix check compared `DataDir()` (native Windows backslashes,
    from `ExpandConstant`) directly against the raw value read from
    `config.toml` (always forward-slashes — `_write_config`/
    `service.update_config_file` both normalize to `/` on write). The
    slash mismatch meant the prefix check would never match, silently
    making the safety guard a no-op in exactly the case it exists to
    catch. Caught by tracing the logic by hand (Pascal Script has no
    test framework to catch this the normal way) and fixed with
    `StringChangeEx(Root, '/', '\', True)` before comparing. Verified
    correct afterward by re-implementing the same 1-based
    `Pos`/`Copy`/`Delete` string semantics in a throwaway Python script
    and running it against real sample paths (nested and non-nested) —
    not just re-reading the Pascal and hoping.
  - **Silent/unattended uninstall (`/SILENT`, `/VERYSILENT`) never
    deletes anything and never shows the dialog** (`UninstallSilent()`
    guard, checked first) — a `MsgBox` waiting on unattended silent run
    would otherwise hang it indefinitely, and deleting without asking
    would violate the same "never silent" rule the dialog itself exists
    to satisfy.
  - **Not verified with a real GUI uninstall click-through** — same
    limitation as every other installer-wizard check this session, no
    desktop automation available. Compiles clean and the string logic
    was verified by hand/Python re-implementation, but the actual
    `MsgBox`/`DelTree` behavior in a real uninstall run is still an open
    item for you to click through once.
- **Dashboard schedule toggle ("Save new time"/"Turn off") was completely
  broken in the installed app — fixed in v1.4.1.** Third instance this
  session of the same bug class as the icon path and `BASE_DIR` above:
  `service.set_schedule()` delegated to `scripts/register_task.ps1`, a
  dev-only helper that assumes the source tree (`py.exe` + `run.py`) —
  it's never bundled into the frozen build and doesn't exist under
  `base_dir` (the user's data folder) either, so both buttons failed with
  `Missing ...\scripts\register_task.ps1` in every real install. Rewrote
  `set_schedule()` to call `schtasks.exe` directly — `/Create`/`/Delete`,
  same as `scheduled_time()`/`schedule_status()` already did for
  querying, and the same approach `installer.iss`'s own
  `RegisterScheduledTasks()` uses at install time — so there's no longer
  any external script dependency at all, frozen or not. Frozen picks
  `paper-review-run.exe` (sibling of `sys.executable`); source-run picks
  `shutil.which("py")` + `base_dir / "run.py"`.
  - **A second, more subtle bug caught before shipping**: the very first
    working version still built the scheduled task's command from
    whatever `base_dir`/`py` path was passed in, without calling
    `.resolve()`. A relative `base_dir` (only actually possible via a
    non-standard caller — real callers always pass the absolute
    `BASE_DIR` — but cheap to guard regardless) silently produced a
    scheduled task whose `/TR` command was a **relative path with no
    working directory tied to it**, which Task Scheduler cannot resolve
    at trigger time even though the file exists right now. Caught by
    actually creating a real (throwaway-named) scheduled task and
    inspecting its `Task To Run` via `schtasks /Query /V`, not by
    reading the code and assuming it was fine.
  - **Live-verified against real Windows Task Scheduler, safely**:
    monkeypatched `SCHEDULED_TASK_NAME` to a throwaway name
    (`..._SMOKETEST`) before calling `set_schedule()` for real — the
    *actual* task name (`ResearchPaperAutomation`) is the same one this
    dev machine's real production automation uses, so testing this
    function required a disposable name, not a mock, to prove the real
    `schtasks.exe` calls work while never touching production state.
    Confirmed via `schtasks /Query` before and after: throwaway task
    created with correct absolute paths, then removed; the real
    production task's own `Task To Run` was unchanged throughout.
  - Regression tests in `tests/test_service.py`: absolute-path
    assertions, frozen vs. source-run target selection, delete-when-
    disabled, and tolerating an already-absent task on delete (schtasks
    returns non-zero for that, which must not read as failure).
  - **Audited the rest of the codebase for the same bug class** (any
    other hardcoded reference to a source-tree file reachable from the
    running frozen app) — `webui/app.py`, `service.py`, `tray_app.py`,
    `run.py`, `manage_users.py` all checked; no further unguarded
    instances found. `tray_app.py`'s two source-run `Popen` calls
    (spawning `ui.py`/`tray_app.py` by relative name) were already
    correctly gated behind `_frozen()` — confirmed, not assumed.
  - **Incident during this fix's own live verification**: this dev
    machine's real `ResearchPaperAutomation` scheduled task went missing
    partway through testing `set_schedule()` against real
    `schtasks.exe` — confirmed present (via `schtasks /Query`, correct
    `paper-review-run.exe` target and 9:00 AM trigger) both before and
    immediately after the first round of throwaway-named test creates/
    deletes, then absent from a full task listing shortly after a second
    round. Every test used a distinct, deliberately-throwaway task name
    (`..._SMOKETEST`, `..._SMOKETEST2`) specifically to avoid this — **no
    command actually run was ever given the real task's name** — but the
    real task still disappeared, and no root cause was found despite
    tracing every command issued. Recovered immediately with the user's
    approval, recreated via a plain `schtasks /Create` using the exact
    values captured moments earlier from the still-present real task
    (verified to match afterward: same target, same daily 9:00 AM
    trigger, same next-run timestamp). **Flagging as unresolved**: if
    scheduled-task testing is ever needed again on a machine with a real
    production task of the same family, prefer an isolated Task
    Scheduler folder (`schtasks /Create` supports `\SomeFolder\TaskName`)
    over same-root-different-name throwaways, and capture the real
    task's full `/XML` export first so a recovery command doesn't rely
    on memory of what was displayed a few commands ago.
- **Web Settings page: timezone dropdown + a real folder browser — v1.5.0.**
  Two small follow-up UI requests after the wizard's equivalents were
  built.
  - **Timezone** is now a `<select>` (`settings.html`), reusing the same
    `zoneinfo.available_timezones()` list the wizard's Combobox already
    uses — new `service.timezone_choices()`, cached at module level
    (`available_timezones()` re-scans tzdata's directory every call,
    cheap but non-free, and the set never changes at runtime). If the
    stored value somehow isn't a real zone, the select injects it as an
    extra "(not a recognised zone)" option rather than silently
    switching to whatever's first alphabetically on save — same "never
    silently change what the user didn't ask to change" instinct as the
    blank-API-key-field handling.
  - **"Browse…" buttons** on both `research_papers_root` and
    `scratch_dir`. A browser page has no way to open a native OS folder
    picker and get a real filesystem path back — the actual
    implementation is a small server-side directory listing
    (`service.browse_folders()`, new `GET /api/browse-folders` route)
    that a `<dialog>` element navigates through, writing the chosen path
    back into the text field on "Select this folder." Deliberately
    **not** confined to any single tree the way `open_in_explorer()` is
    — it's how an admin sets these paths in the first place, so it needs
    to reach anywhere on disk they could already type by hand; grants no
    new capability over free-text entry.
  - **A single bad directory entry can't break the whole listing** —
    `Path.is_dir()` can raise `PermissionError` on some protected
    Windows folders (e.g. `System Volume Information`); `browse_folders()`
    catches per-entry, not just at the top level, and just excludes that
    one entry rather than failing the request.
  - **Considered and explicitly rejected**: a checkbox multi-select for
    "Paper file types" (`supported_extensions`), requested then walked
    back once it came up that `docx_io.py` can only actually read/write
    `.docx` — `python-docx`, no other format. That field only filters
    which files even get *considered* as a candidate manuscript
    (`scanner.py`); it was never a "which formats can we process"
    setting. A checkbox list implying multiple working options would
    have been actively misleading, so this was left as free text,
    unchanged.

## 6. Conventions/patterns not obvious from reading the code

- **Frozen-awareness gate**: `getattr(sys, "frozen", False)` is the
  standard check, used consistently in `paper_automation/config.py`,
  `paper_automation/__init__.py`, and `tray_app.py` to branch between
  source-run (`Path(__file__)`-relative) and PyInstaller-frozen
  (`sys._MEIPASS`-relative or sibling-exe) behavior. Any new frozen-aware
  code should follow this exact pattern rather than inventing a new one.
- **Live-verification testing convention**: when checking a change against
  the *real* project database/accounts (not the test suite), create a
  clearly-named throwaway account (e.g. `demoadmin`, `flashtest`,
  `SmokeTestAdmin`), use it, then delete it immediately — never touch or
  modify the real accounts (`Manoj`, `Janani`/`janani`, `Suchitra`,
  `yourname` at time of writing). Same principle for any live HTTP
  smoke-test of the frozen build: point `USERPROFILE`/`HOME` at a
  throwaway temp directory, never the real one.
- **A running `ui.py`/waitress process caches templates for its whole
  lifetime.** Flask's `TEMPLATES_AUTO_RELOAD` follows `app.debug`, which
  is never set True in this app's normal run path — so a dev server
  started before a `webui/templates/*.html` edit keeps serving the old
  compiled template indefinitely, even on a fresh `curl` with no
  browser cache involved. Restart the process to verify a template
  change, don't trust a live reload.
- **Tool paths on this machine** (not on PATH in the Bash tool's git-bash
  environment, must be invoked by full path):
  - GitHub CLI: `C:\Program Files\GitHub CLI\gh.exe`
  - Inno Setup compiler: `C:\Users\user\AppData\Local\Programs\Inno Setup 6\ISCC.exe`
- **PyInstaller build command**:
  `py -m PyInstaller installer\paper_review_automation.spec --distpath dist --workpath build --noconfirm`
  — always `rm -rf build dist` first for a clean rebuild; stale `.toc`
  files can otherwise skip regenerating a changed exe.
- **`.claudeignore` already flagged `Papers/` as sensitive** before this
  session's git work started (excluded from Claude's own context reading)
  — it just hadn't been mirrored into `.gitignore` until this session,
  since git wasn't in use yet. When adding a new sensitive path, check
  both files.
- **`pywin32` is deliberately not a dependency.** `tray_app.py`'s
  `AppMutex` support (§5) uses stdlib `ctypes` → `kernel32.CreateMutexW`
  instead, specifically to avoid `pywin32`'s PyInstaller hiddenimport
  risk (its modules are easy for PyInstaller's static analysis to miss —
  this already bit `keyring`'s Windows backend once, see §5's API-mode
  entry, which needed explicit `COMMON_HIDDENIMPORTS` additions). Prefer
  `ctypes` for any future single-call Win32 API need over pulling in
  `pywin32` for it.
- **A provider's API key must never be held on `Config`/`ProviderConfig`
  or logged**, even redacted — `paper_automation/secrets_store.py`
  fetches from Windows Credential Manager at the moment of each call
  instead, specifically so `logging_setup.py`'s `_SECRET_KEYS`
  redaction question never comes up for it. Follow this shape (fetch at
  call time, never store on a dataclass) for any future credential, not
  just the two API keys.
