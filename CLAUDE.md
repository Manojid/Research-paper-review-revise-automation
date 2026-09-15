# Paper Review Automation

Windows app automating research-paper review (Codex CLI) and revision
(Claude Code CLI), both driven non-interactively via subscription login —
no API keys. `paper_automation/` = pipeline/business logic; `webui/` = thin
Flask control panel over it; `run.py`/`ui.py`/`tray_app.py`/
`manage_users.py` = CLI entry points; `installer/` = PyInstaller + Inno
Setup portable installer.

**Before doing any work, read `PROJECT-NOTES.md` in full** (what's built,
why, bugs already fixed, abandoned approaches, known tech debt) **and
`TODO-v2.md`** (planned work, priority-ordered). This file only holds what
changes your behavior; those two hold everything else.

## Commands

```bash
py -m pytest tests/ -q      # all tests
py run.py --dry-run         # report decisions, change nothing
py ui.py                    # start the web control panel
```

No linter/formatter configured — don't add one without asking.

## Conventions enforced

- Always `py`, never `python`/`python3`.
- Every `subprocess.run`/`Popen` needs `creationflags=CREATE_NO_WINDOW` on
  Windows (else it flashes a console from the windowless UI/tray process).
- Frozen-build branches use `getattr(sys, "frozen", False)` (see
  `config.py`, `tray_app.py`, `paper_automation/__init__.py`).
- `SubprocessProvider` subclasses set `label_base`, never `model_label`.
- Bump root `VERSION` for any release — single source for app + installer.

## Hard constraints

- CLI-only — no API keys, no direct model API calls.
- Zero delete/rename/move against client folders anywhere in
  `paper_automation/`, AST-enforced by `tests/test_safety.py`.
- Never commit `Papers/`, `config.toml`, `state/`, `logs/`, `dist/`,
  `build/` (see `.gitignore`).
- No auto-update, log/backup pruning, or job-retry button without
  discussing first.

## Temporary vs. fixed

- **Temporary**: `task_mode = "grammar"` is a cheap testing state, not the
  destination — `"full"` (Q1 review + scientific revision) is production.
  Never remove the `full` prompts.
- **Fixed, don't relitigate**: CLI-not-API; MANAGER role dropped
  (ADMIN/WRITER only); subprocess-based tray; no-delete invariant;
  unsigned installer for now.
- Admin-edited prompts always get `_contract()`/`INTEGRITY_RULES`
  appended, never editable away.
- UI text is plain English for non-technical users — no raw enum values
  or phase names shown.
