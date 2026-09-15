# TODO — Version 2

Full detail from discussion, not a summary — read `PROJECT-NOTES.md` first
for context on why things are the way they are in v1.

## Must-have

### 1. ✅ DONE (v1.0.1) — Fix the first-run wizard re-launching on every install, including upgrades

`installer/installer.iss`'s `[Run]` section currently launches
`FirstRunSetup.exe` unconditionally after every install:

```
Filename: "{app}\FirstRunSetup.exe"; Description: "Run first-time setup"; \
    Flags: postinstall skipifsilent nowait
```

On an upgrade (re-running a newer installer over an existing install),
`%USERPROFILE%\PaperReviewAutomation\config.toml` already exists, and the
wizard will try to create a duplicate admin account with the same name,
hitting `auth.AuthError: User '<name>' already exists.` — a confusing
error popping up right after what should be a silent update.

**Fix**: add a `Check:` function in `installer.iss`'s `[Code]` section
(e.g. `FirstRunNeeded`) that returns `False` when
`%USERPROFILE%\PaperReviewAutomation\config.toml` already exists, and
attach it to the `[Run]` line so the wizard step is skipped entirely on
any upgrade. Test by installing fresh, then installing a bumped-version
build over it — the wizard should launch the first time and not the
second.

### 2. ✅ DONE (v1.1.0) — Handle running processes during an upgrade install

If the tray icon and/or web service (`PaperReviewAutomation.exe` /
`PaperReviewAutomationService.exe`) are running when a newer installer
executes, Windows file locking could prevent Inno Setup from overwriting
those exes.

**Fix**: set `AppMutex` in `installer.iss`'s `[Setup]` section — this
requires `tray_app.py` to hold a named mutex while running, so Inno Setup
can detect the running app and offer to close it automatically before
copying files (Inno Setup's standard built-in mechanism for exactly this
case). Avoids having to tell every user "manually exit the tray icon
before updating."

### 3. ✅ ESTABLISHED — Real version-bump discipline for future releases

v1.0.0's tag was force-moved once mid-session (to fold the version-display
feature in after the fact, at the user's explicit request, since the repo
was brand-new and single-user). **Going forward, any code change should
get a real version bump** (bump `VERSION`, tag `vX.Y.Z`, new GitHub
Release) rather than repeating that force-move — once other people or
tooling depend on the repo, moving a published tag becomes genuinely
disruptive, not just unconventional.

## Nice-to-have

### 4. ✅ DONE (v1.1.0) — API-mode provider toggle

**As actually built, this diverged from the original scoped design below
in one deliberate way** — see `PROJECT-NOTES.md` §5's "API-mode provider
toggle" entry for the real shape: API keys are entered through the
Settings page (not env-var-only) and stored in Windows Credential
Manager via a new `keyring` dependency, per an explicit user decision
that overrides `settings.html`'s otherwise-real "no secrets in a browser
form" principle. Everything else below (the `CliProvider` seam, the
`build_providers` factory shape, the security principles) held as
originally scoped. Left in place for the historical rationale.

Full design already scoped during discussion, not yet built. The seam
already exists — this is additive, not a rewrite:

- `paper_automation/providers/base.py`'s `CliProvider` abstract base only
  requires `_invoke(workdir, prompt) -> str` (read `manuscript.md` from
  the scratch dir, write `output.md`). `MockProvider` already proves a
  provider can satisfy this without any subprocess at all — an
  `ApiProvider` would be the same shape, calling the Anthropic or OpenAI
  SDK instead.
- `paper_automation/providers/__init__.py`'s `build_providers(cfg)` is
  the single factory every run goes through, keyed off `cfg.provider_mode`
  (currently `"auto"`/`"mock"`/`"real"`). Add an `"api"` value returning
  `ApiProvider(cfg.codex)` / `ApiProvider(cfg.claude)` (or one generic
  class parameterized by vendor). Nothing in `phases.py`, `service.py`,
  or the web UI needs to change — they only ever talk to the
  `CliProvider` interface.
- `preflight()` becomes "does the API key work" instead of "does the
  binary run."
- **Security — reuse the existing secret-handling pattern**, don't invent
  a new one: `config.py`'s `_notify()` already does env-var-override-
  config-file for SMTP/Telegram/Slack/Teams secrets
  (`os.environ.get("SMTP_PASSWORD", raw.get("smtp_password", ""))`). A
  future `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` should follow the exact
  same shape — `config.toml` only ever holds an empty placeholder, the
  real value lives in the environment. `logging_setup.py`'s redaction
  filter (`_SECRET_KEYS`) already includes `"api_key"`, so log-file
  exposure is already covered without further changes.
- **Stronger option for a shared/company deployment**: a plain user-level
  env var is still plaintext at rest, readable by anything else running
  as that Windows user. For a multi-person company rollout, use the
  `keyring` package against Windows Credential Manager (DPAPI-encrypted
  per-user) instead of `os.environ` directly.
- **Other security principles discussed, worth applying whenever this is
  built**: use a least-privilege/scoped API key, not a full-access org
  key; use a separate, low-limit key for `--test-mode` runs so a testing
  mistake can't exhaust a real budget; have a rotation plan before the
  first key is issued (unlike a personal CLI login, a leaked API key can
  be silently reused elsewhere); never log raw `Authorization` headers
  (usage/billing metadata is fine to log, credentials are not).
- **Why API mode might matter later**: it removes the CLI's dependency on
  an interactive desktop-app login, so this could enable headless/server
  deployment (no logged-in user session required) — the concrete
  "reason to add it" this was deferred pending.
- **Trade-off to keep visible when this is built**: API access is billed
  per-token separately from a Codex/Claude subscription — this is a real
  cost change, not just a technical one, and should be called out
  explicitly when this ships (per the standing "flag security/cost
  concerns explicitly per phase" instruction).

### 5. Code signing certificate

Would remove the SmartScreen "unknown publisher" warning on first run of
the installer. Deliberately deferred for v1 (cost/complexity vs. a small
internal user base). Revisit if it becomes an actual adoption blocker —
i.e., if people are hesitant to click through the warning.

### 6. "New version available" notice in the app

Discussed as update-story option 2 (of 3): the tray or dashboard checks a
version marker (a shared network file, or an internal webpage) and shows
a download link when the running version is behind. Still a manual
re-install — just adds visibility, so an admin doesn't have to
proactively check GitHub. Explicitly designed to layer on top of the
current "re-run installer" model without needing a redesign — build this
without disturbing the existing upgrade-in-place mechanics.

### 7. Relocate `Papers/` (research data root) outside the project folder

Currently `research_papers_root` points at `Papers/` inside this same git
repo's working directory, relying entirely on `.gitignore` to keep real
client manuscripts out of version control. Works, but structurally
fragile (see `PROJECT-NOTES.md` §5). Moving the actual data folder
somewhere outside the repo (e.g. directly under `%USERPROFILE%`, matching
where the installer already puts the data folder for installed copies)
would remove the dependency on `.gitignore` discipline entirely. Config-
only change (`research_papers_root` in `config.toml`), no code change
needed — just needs the actual files moved and the setting updated.

### 8. In-app "check for updates"

Related to #6 but distinct: even without a push notification, expose the
currently-running version (already done — dashboard footer / tray tooltip)
next to a link to the GitHub Releases page, so checking for an update is
one click from inside the app rather than requiring an admin to know the
repo URL.

## Ideas (not committed, more speculative)

### 9. True self-update (background download + swap)

Update-story option 3 (of 3), explicitly the most expensive: a running
`.exe` can't overwrite itself on Windows, so this needs a small separate
updater process plus rollback handling if the download/swap fails
mid-way. Judged disproportionate machinery for a small internal-tool user
base at v1. **Only revisit if the number of installs grows significantly**
— re-running an installer manually stops being reasonable at some scale,
but that scale hasn't been reached.

### 10. Google Drive direct-API storage backend

`paper_automation/storage/gdrive.py` is already a documented stub behind
the `StorageBackend` ABC (`storage/base.py`). Currently
`storage_backend = "gdrive"` fails fast at config-load time with a clear
"not implemented yet, use local" message — Drive-for-Desktop + local
storage already covers the common case. Only worth building a direct API
backend if there's a concrete reason local sync isn't sufficient (e.g.
needing to work with files not present on the automation machine's disk).

### 11. Running the pipeline when the machine is off/asleep

Already an explicitly-flagged open decision in `CLAUDE.md`, carried
forward here for visibility since it's a real gap, not because it's newly
discussed:
- **Option A**: a Task Scheduler wake timer that brings the machine out
  of sleep for the scheduled run.
- **Option B**: catch-up on power-on — run the missed job when the
  machine next starts. `StartWhenAvailable` is already set in
  `register_task.ps1`, which gets partway there.
Neither is implemented. Do not implement either without discussing first
— this was a deliberate hold, not an oversight, per `CLAUDE.md`.

### 12. Reconsider a third role if the team grows

MANAGER was explicitly dropped for v1 ("only admin and user is enough" —
the user's correction, not an oversight). If the user base grows past a
size where "every non-writer is trusted with full admin" stops making
sense, a scoped-down role (e.g. can view `/jobs` and `/history` but not
`/users` or `/settings`) might become worth it. Not a v2 priority; noted
so it isn't proposed as if it were a new idea when it resurfaces.

### 13. "Browse…" button for the Papers folder field in web Settings

`webui/templates/settings.html`'s "Papers folder" field is a plain text
input — the user has to type or paste the full path. The Tkinter
first-run wizard already has a real `Browse…` button
(`installer/first_run_wizard.py`'s `_browse()`, via
`tkinter.filedialog.askdirectory`), and this is the same request for the
web Settings page.

**Not a trivial add — flag this before starting**: a browser page cannot
open a native OS folder picker and get back a real filesystem path
(security sandboxing — `<input type="file">`/`webkitdirectory` only
exposes file *contents* to the page, never an absolute local path this
app could write into `config.toml`). Since this is a local
desktop-controlling app (not a public web service), the realistic
approach is a small server-side folder browser instead: a new read-only
API route (e.g. `GET /api/browse-folders?path=...`) that lists
subdirectories of a given starting point, and a modal/dropdown in
`settings.html` that lets the user navigate down into folders and pick
one, writing the resulting path into the existing text field rather than
replacing it. `paper_automation/storage/local.py`'s `LocalStorage.list_folders(path)`
already exists and does most of the needed work (lists subdirectories of
a path) — reuse it rather than writing new directory-listing logic.
Needs a sensible starting point (e.g. the current field value if set,
else the user's home folder) and the usual guardrails against path
traversal outside anything sensible (though unlike client-folder writes,
this is read-only directory listing, not a delete/move risk).
