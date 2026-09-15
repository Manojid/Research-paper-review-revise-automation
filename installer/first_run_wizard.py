"""First-run setup wizard for the installed Paper Review Automation.

Run once by the Inno Setup installer right after copying the frozen exes
(installer/installer.iss's post-install [Run] step). Not part of the normal
"py run.py" / "py ui.py" source-run workflow — see README/CLAUDE.md for
that; this only exists to save a new install from three manual steps (copy
config.example.toml, edit research_papers_root, run manage_users.py add).

Writes %USERPROFILE%\\PaperReviewAutomation\\config.toml (research_papers_root
+ timezone from the form, everything else left at config.example.toml's
defaults) and creates the first admin account by calling
paper_automation.auth.create_user() directly — the exact same function the
web UI's /users "Add user" button and manage_users.py add use, so account
creation logic is not duplicated here. The account gets the fixed default
password ("iMatiz") and is forced to set a real one on first login, same as
any other account created this way.
"""

import sys
import zoneinfo
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# When frozen, installer/first_run_wizard.py and the paper_automation package
# are bundled into the same shared dist folder (see paper_review_automation.spec's
# MERGE), so this import resolves the same way it does for the other exes.
from paper_automation import auth
from paper_automation import config as config_module
from paper_automation import scanner, service
from paper_automation.storage import build_storage

DATA_DIR = Path.home() / "PaperReviewAutomation"
APP_NAME = "Paper Review Automation — First-run Setup"


def _template_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "config.example.toml"


def _write_config(papers_root: str, timezone: str) -> Path:
    template = _template_path().read_text(encoding="utf-8-sig")
    lines = []
    for line in template.splitlines():
        if line.startswith("research_papers_root ="):
            escaped = papers_root.replace("\\", "/")
            lines.append(f'research_papers_root = "{escaped}"')
        elif line.startswith("timezone ="):
            lines.append(f'timezone = "{timezone}"')
        else:
            lines.append(line)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    config_path = DATA_DIR / "config.toml"
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path


def _enable_dpi_awareness() -> None:
    """Best-effort only. A non-DPI-aware Tk window is bitmap-scaled by
    Windows on any scaled display, which is what actually causes the
    blur — this must run before Tk() is constructed. A failure here must
    never stop the wizard from starting."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _system_dpi() -> int:
    """The screen's logical DPI (96 = 100% scaling), for Tk's own widget/
    font scaling — separate from _enable_dpi_awareness(), which only stops
    Windows from bitmap-stretching the window after the fact."""
    if sys.platform != "win32":
        return 96
    try:
        import ctypes

        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi or 96
    except Exception:
        return 96


def _detect_local_timezone() -> str:
    """Best-effort IANA zone name for this PC, via tzlocal. Never raises —
    falls back to a sensible default so setup is never blocked by this."""
    try:
        import tzlocal

        name = tzlocal.get_localzone_name()
        if name:
            return name
    except Exception:
        pass
    return "Asia/Kolkata"


class Wizard(tk.Tk):
    """Three steps in one window; steps 2 and 3 are entirely skippable.

    Step 1 (papers folder, timezone, admin account) is mandatory, same as
    it always was. Step 2 (first month/employee folder) and step 3
    (CLI-vs-API choice) only exist to save a couple of clicks later —
    "Skip this step" on either one leaves that part exactly as step 1 left
    it, since none of it is required to start using the app (all of it is
    reachable from Settings afterwards).
    """

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.resizable(False, False)
        try:
            self.tk.call("tk", "scaling", _system_dpi() / 72.0)
        except Exception:
            pass
        self.papers_root = tk.StringVar(value=str(Path.home() / "Research Papers"))
        self.timezone = tk.StringVar(value=_detect_local_timezone())
        self.admin_name = tk.StringVar(value="")
        self.employee_name = tk.StringVar(value="")
        self.provider_choice = tk.StringVar(value="cli")
        # Set once step 1 succeeds; later steps reuse them rather than reloading.
        self.cfg = None
        self.config_path = None
        self.frame = None
        self._build_account_step()

    def _reset_frame(self):
        if self.frame is not None:
            self.frame.destroy()
        self.frame = ttk.Frame(self)
        self.frame.pack(fill="both", expand=True, padx=8, pady=8)
        return self.frame

    # --- step 1: papers folder, timezone, admin account ---------------------

    def _build_account_step(self):
        pad = {"padx": 12, "pady": 6}
        frame = self._reset_frame()

        ttk.Label(
            frame,
            text="Set up Paper Review Automation",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        ttk.Label(frame, text="Research papers folder:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.papers_root, width=48).grid(row=1, column=1, **pad)
        ttk.Button(frame, text="Browse…", command=self._browse).grid(row=1, column=2, **pad)

        ttk.Label(frame, text="Timezone:").grid(row=2, column=0, sticky="w", **pad)
        timezone_box = ttk.Combobox(
            frame, textvariable=self.timezone, width=45, state="readonly",
            values=sorted(zoneinfo.available_timezones()),
        )
        timezone_box.grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(
            frame, text="Detected from this PC — change it if it's wrong.",
            foreground="#555555",
        ).grid(row=2, column=2, sticky="w")

        ttk.Label(frame, text="Your name (first admin account):").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.admin_name, width=48).grid(row=3, column=1, **pad)

        ttk.Label(
            frame,
            text=(
                "Default password: iMatiz — you'll be asked to change it the\n"
                "first time you log in."
            ),
            foreground="#555555",
        ).grid(row=4, column=0, columnspan=3, sticky="w", **pad)

        ttk.Button(frame, text="Continue", command=self._finish_account).grid(
            row=5, column=0, columnspan=3, pady=(12, 4)
        )

    def _browse(self):
        chosen = filedialog.askdirectory(title="Choose the research papers folder")
        if chosen:
            self.papers_root.set(chosen)

    def _finish_account(self):
        papers_root = self.papers_root.get().strip()
        timezone = self.timezone.get().strip() or "Asia/Kolkata"
        admin_name = self.admin_name.get().strip()

        if not papers_root:
            messagebox.showerror(APP_NAME, "Please choose a research papers folder.")
            return
        if not admin_name:
            messagebox.showerror(APP_NAME, "Please enter a name for the first admin account.")
            return

        try:
            Path(papers_root).mkdir(parents=True, exist_ok=True)
            config_path = _write_config(papers_root, timezone)
            cfg = config_module.load(path=config_path, base_dir=DATA_DIR)
            auth.create_user(cfg.state_db, admin_name, auth.Role.ADMIN)
        except auth.AuthError as exc:
            messagebox.showerror(APP_NAME, f"Could not create the admin account: {exc}")
            return
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not set up the papers folder: {exc}")
            return
        except config_module.ConfigError as exc:
            messagebox.showerror(APP_NAME, f"Could not write config.toml: {exc}")
            return

        self.cfg = cfg
        self.config_path = config_path
        self._build_folder_step()

    # --- step 2: first month/employee folder, entirely optional -------------

    def _build_folder_step(self):
        pad = {"padx": 12, "pady": 6}
        frame = self._reset_frame()
        month = scanner.current_month(self.cfg)

        ttk.Label(
            frame,
            text="Your first folder (optional)",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(
            frame,
            text=(
                "Papers are organized as:\n"
                "  <Papers folder>  →  <Month Year>  →  <Employee>  →  <Client>\n\n"
                f"For example: Research Papers / {month} / Priya / Acme Corp.\n"
                "Each employee gets their own folder inside the current month;\n"
                "client folders appear automatically as papers come in — you\n"
                "only ever need to create the employee folder yourself."
            ),
            foreground="#555555",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(frame, text="This month's folder:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Label(frame, text=month).grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(frame, text="First employee's name (optional):").grid(
            row=3, column=0, sticky="w", **pad
        )
        ttk.Entry(frame, textvariable=self.employee_name, width=36).grid(
            row=3, column=1, sticky="w", **pad
        )

        ttk.Label(
            frame,
            text="Skip this if you'd rather set it up later — nothing here is required.",
            foreground="#555555",
        ).grid(row=4, column=0, columnspan=2, sticky="w", **pad)

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, pady=(12, 4))
        ttk.Button(buttons, text="Skip this step", command=self._skip_folder_step).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="Continue", command=self._finish_folder_step).pack(
            side="left", padx=6
        )

    def _skip_folder_step(self):
        self._build_provider_step()

    def _finish_folder_step(self):
        employee = self.employee_name.get().strip()
        if employee:
            storage = build_storage(self.cfg)
            month = scanner.current_month(self.cfg)
            result = service.create_employee_folder(self.cfg, storage, month, employee)
            if not result["ok"]:
                messagebox.showerror(APP_NAME, result["message"])
                return
        self._build_provider_step()

    # --- step 3: CLI vs API, entirely optional -------------------------------

    def _build_provider_step(self):
        pad = {"padx": 12, "pady": 6}
        frame = self._reset_frame()

        ttk.Label(
            frame,
            text="How should this app reach the models? (optional)",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(
            frame,
            text="Skip this to decide later — CLI is used by default until you change it.",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, sticky="w", **pad)

        ttk.Radiobutton(
            frame, text="CLI (recommended) — uses your Codex/Claude subscription login",
            variable=self.provider_choice, value="cli",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=24, pady=(8, 2))
        ttk.Radiobutton(
            frame, text="API — billed per token, needs your own API keys",
            variable=self.provider_choice, value="api",
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=24, pady=(2, 8))

        ttk.Label(
            frame,
            text=(
                "Either way, sign-in (CLI) or your API keys are set up from the "
                "dashboard's Settings page, not here — this only records your "
                "preference. All of it can be changed anytime."
            ),
            foreground="#555555",
            wraplength=440,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", **pad)

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, pady=(12, 4))
        ttk.Button(buttons, text="Skip this step", command=self._skip_provider_step).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="Finish setup", command=self._finish_provider_step).pack(
            side="left", padx=6
        )

    def _skip_provider_step(self):
        self._show_completion()

    def _finish_provider_step(self):
        provider_api = self.provider_choice.get() == "api"
        if provider_api:
            try:
                service.update_config_file(self.config_path, {"provider_mode": "api"})
            except (config_module.ConfigError, OSError) as exc:
                messagebox.showerror(APP_NAME, f"Could not save provider mode: {exc}")
                return
        self._show_completion(provider_api=provider_api)

    def _show_completion(self, provider_api: bool = False):
        admin_name = self.admin_name.get().strip()
        lines = [
            "Setup complete.",
            "",
            f"Login: {admin_name}",
            "Password: iMatiz (you'll be asked to change it)",
            "",
        ]
        if provider_api:
            lines.append(
                "Add your Anthropic/OpenAI API keys from the dashboard's Settings "
                "page (Provider mode: API) before your first run."
            )
        else:
            lines.append(
                "Sign in to Codex and Claude from the dashboard's Settings page "
                "(each has a Sign in button) before your first run."
            )
        lines.append("")
        lines.append("Open the desktop icon to get started.")

        messagebox.showinfo(APP_NAME, "\n".join(lines))
        self.destroy()


def main() -> int:
    _enable_dpi_awareness()
    Wizard().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
