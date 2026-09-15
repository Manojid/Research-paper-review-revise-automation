"""Web routes. Thin layer, so these check wiring and the safety boundaries."""

from pathlib import Path

import pytest

flask = pytest.importorskip("flask", reason="web UI is optional")


def test_base_dir_is_frozen_aware(monkeypatch):
    """Regression test: BASE_DIR used to resolve to a PyInstaller
    _internal extraction path in a frozen build (Path(__file__)-relative,
    no frozen check at all) instead of the user's data folder — this is
    what made Settings save, the model registry, and the schedule toggle
    all fail with "No such file or directory" in the real installed app.
    """
    from webui import app as webapp

    monkeypatch.setattr(webapp.sys, "frozen", True, raising=False)
    assert webapp._default_base_dir() == Path.home() / "PaperReviewAutomation"

    monkeypatch.delattr(webapp.sys, "frozen", raising=False)
    assert webapp._default_base_dir() == Path(webapp.__file__).resolve().parent.parent


@pytest.fixture
def client(cfg, tmp_path, monkeypatch):
    """A test client whose config points at the temporary tree."""
    from paper_automation import config as config_module
    from webui import app as webapp

    monkeypatch.setattr(webapp, "current_config", lambda: cfg)
    monkeypatch.setattr(config_module, "load", lambda path=None: cfg)
    webapp.app.config["TESTING"] = True
    webapp.runs = __import__(
        "paper_automation.service", fromlist=["service"]
    ).RunManager()
    return webapp.app.test_client()


def test_prompt_editor_renders_both_phases(client):
    res = client.get("/prompts")
    assert res.status_code == 200
    assert b"Finding the mistakes" in res.data
    assert b"Writing the corrections" in res.data


def test_prompt_editor_save_and_restore(client, cfg):
    res = client.post("/prompts", data={
        "phase": "review", "action": "save", "body": "Custom {client} instructions.",
    })
    assert res.status_code == 200
    assert b"Saved as version 1" in res.data

    res = client.get("/prompts")
    assert b"Custom {client} instructions." in res.data
    assert b"edited" in res.data

    res = client.post("/prompts", data={"phase": "review", "action": "reset"})
    assert b"built-in instructions again" in res.data


def test_prompt_editor_rejects_an_unknown_placeholder(client):
    res = client.post("/prompts", data={
        "phase": "review", "action": "save", "body": "Bad {nonsense}",
    })
    assert b"Unknown placeholder" in res.data


def test_create_folder_api_creates_an_employee_folder(client, cfg):
    res = client.post("/api/create-folder", json={
        "month": "August 2026", "employee": "Priya",
    })
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert (cfg.research_papers_root / "August 2026" / "Priya").is_dir()


def test_create_folder_api_creates_a_client_folder(client, cfg):
    res = client.post("/api/create-folder", json={
        "month": "August 2026", "employee": "Priya", "client": "Acme",
    })
    assert res.status_code == 200
    assert (cfg.research_papers_root / "August 2026" / "Priya" / "Acme").is_dir()


def test_create_folder_api_requires_month_and_employee(client):
    res = client.post("/api/create-folder", json={"employee": "Priya"})
    assert res.status_code == 400
    res = client.post("/api/create-folder", json={"month": "August 2026"})
    assert res.status_code == 400


def test_create_folder_api_rejects_a_bad_name(client):
    res = client.post("/api/create-folder", json={
        "month": "August 2026", "employee": "../evil",
    })
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_dashboard_renders(client, make_client):
    make_client("Vani.docx")
    res = client.get("/")
    assert res.status_code == 200
    assert b"Vani" in res.data


def test_dashboard_shows_the_pending_action(client, make_client):
    make_client("Vani.docx")
    assert b"Waiting to be checked" in client.get("/").data


def test_dashboard_survives_a_missing_papers_folder(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"find your papers folder" in res.data.lower()


def test_history_and_settings_render(client):
    assert client.get("/history").status_code == 200
    assert client.get("/settings").status_code == 200


@pytest.fixture
def fake_signin_status(monkeypatch):
    """Dashboard/settings banner tests must never spawn a real subprocess."""
    from webui import app as webapp

    def _set(codex=True, claude=True):
        monkeypatch.setattr(webapp.service, "cli_version", lambda *a, **kw: "1.0.0")
        monkeypatch.setattr(
            webapp.service, "cli_signed_in",
            lambda name, cfg: {"codex": codex, "claude": claude}[name],
        )

    return _set


def test_dashboard_shows_sign_in_banner_when_codex_is_signed_out(client, fake_signin_status):
    fake_signin_status(codex=False, claude=True)
    res = client.get("/")
    assert b"Sign in required" in res.data
    assert b"Codex is signed out" in res.data


def test_dashboard_shows_no_banner_when_both_are_signed_in(client, fake_signin_status):
    fake_signin_status(codex=True, claude=True)
    res = client.get("/")
    assert b"Sign in required" not in res.data


def test_dashboard_shows_no_banner_when_status_is_unknown(client, monkeypatch):
    """None (couldn't determine) must never be treated as "signed out" —
    same "don't claim what we don't know" rule as the API-mode banner."""
    from webui import app as webapp

    monkeypatch.setattr(webapp.service, "cli_version", lambda *a, **kw: "")
    monkeypatch.setattr(webapp.service, "cli_signed_in", lambda name, cfg: None)
    res = client.get("/")
    assert b"Sign in required" not in res.data


def test_settings_shows_sign_in_banner_when_claude_is_signed_out(client, fake_signin_status):
    fake_signin_status(codex=True, claude=False)
    res = client.get("/settings")
    assert b"Sign in required" in res.data
    assert b"Claude is signed out" in res.data


@pytest.fixture
def fake_secrets_store(monkeypatch):
    """Settings-route tests must never touch the real Windows Credential
    Manager or the real config.toml on disk."""
    from paper_automation import secrets_store

    store = {}
    monkeypatch.setattr(secrets_store, "get_api_key", lambda vendor: store.get(vendor, ""))
    monkeypatch.setattr(secrets_store, "set_api_key", lambda vendor, value: store.__setitem__(vendor, value) if value else None)
    monkeypatch.setattr(secrets_store, "clear_api_key", lambda vendor: store.pop(vendor, None))
    return store


@pytest.fixture
def fake_update_config_file(monkeypatch):
    """Avoid the settings route writing to the real project config.toml."""
    from paper_automation import service

    monkeypatch.setattr(service, "update_config_file", lambda path, updates: list(updates.keys()))
    monkeypatch.setattr(service, "update_provider_model", lambda path, provider, model_id: False)


def test_settings_saves_a_new_api_key(client, fake_secrets_store, fake_update_config_file):
    res = client.post("/settings", data={"anthropic_api_key": "sk-throwaway-test-key"})
    assert res.status_code == 200
    assert fake_secrets_store["anthropic"] == "sk-throwaway-test-key"
    assert b"anthropic API key" in res.data or b"Saved" in res.data


def test_settings_blank_api_key_field_leaves_stored_key_untouched(
    client, fake_secrets_store, fake_update_config_file
):
    fake_secrets_store["openai"] = "sk-already-set"
    client.post("/settings", data={"openai_api_key": ""})
    assert fake_secrets_store["openai"] == "sk-already-set"


def test_settings_never_echoes_a_stored_api_key_back(client, fake_secrets_store, fake_update_config_file):
    fake_secrets_store["anthropic"] = "sk-super-secret-value"
    res = client.get("/settings")
    assert b"sk-super-secret-value" not in res.data


def test_cli_login_endpoint_calls_service_with_the_right_provider(client, monkeypatch):
    from webui import app as webapp

    calls = []
    monkeypatch.setattr(
        webapp.service, "open_cli_login",
        lambda name, cfg: (calls.append(name), (True, f"Opened a sign-in window for {name}."))[1],
    )

    res = client.post("/api/cli-login/codex")

    assert res.status_code == 200
    assert res.get_json() == {"ok": True, "message": "Opened a sign-in window for codex."}
    assert calls == ["codex"]


def test_schedule_endpoint_passes_base_dir_through(client, monkeypatch):
    """Regression guard for the same bug class as BASE_DIR/the desktop
    icon: /api/schedule must pass the real (frozen-aware) BASE_DIR through
    to service.set_schedule(), not a hardcoded or stale one."""
    from webui import app as webapp

    calls = []
    monkeypatch.setattr(
        webapp.service, "set_schedule",
        lambda enabled, base_dir, at: calls.append((enabled, base_dir, at)) or {"ok": True, "message": ""},
    )
    monkeypatch.setattr(webapp.service, "schedule_status", lambda: {})

    res = client.post("/api/schedule", json={"enabled": True, "at": "06:30"})

    assert res.status_code == 200
    assert calls == [(True, webapp.BASE_DIR, "06:30")]


def test_browse_folders_endpoint_returns_subfolders(client, tmp_path):
    (tmp_path / "Acme").mkdir()

    res = client.get(f"/api/browse-folders?path={tmp_path}")

    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert [f["name"] for f in data["folders"]] == ["Acme"]


def test_browse_folders_endpoint_reports_failure(client, monkeypatch):
    from webui import app as webapp

    monkeypatch.setattr(
        webapp.service, "browse_folders", lambda path: {"ok": False, "message": "nope"}
    )

    res = client.get("/api/browse-folders?path=whatever")

    assert res.status_code == 400
    assert res.get_json() == {"ok": False, "message": "nope"}


def test_cli_login_endpoint_rejects_an_unknown_provider(client):
    res = client.post("/api/cli-login/not-a-real-provider")
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_cli_login_endpoint_reports_failure_from_service(client, monkeypatch):
    from webui import app as webapp

    monkeypatch.setattr(
        webapp.service, "open_cli_login", lambda name, cfg: (False, "Could not find codex.")
    )

    res = client.post("/api/cli-login/codex")

    assert res.status_code == 400
    assert res.get_json() == {"ok": False, "message": "Could not find codex."}


def test_scan_api_returns_rows(client, make_client):
    make_client("Vani.docx")
    data = client.get("/api/scan").get_json()
    assert data["rows"][0]["client"] == "Vani"
    assert data["rows"][0]["status"] == "READY_REVIEW"


def test_preview_api_changes_nothing(client, make_client):
    folder = make_client("Vani.docx")
    before = sorted(p.name for p in folder.iterdir())
    assert client.get("/api/preview").status_code == 200
    assert sorted(p.name for p in folder.iterdir()) == before


def test_status_api_is_idle_initially(client):
    assert client.get("/api/status").get_json()["running"] is False


def test_open_api_rejects_a_path_outside_the_tree(client, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    res = client.post("/api/open", json={"path": str(outside)})
    assert res.get_json()["ok"] is False


def test_open_api_requires_a_path(client):
    assert client.post("/api/open", json={}).status_code == 400


def test_second_run_request_is_refused(client, make_client, cfg):
    """The UI must not be able to start two pipelines over the same folders."""
    from webui import app as webapp

    make_client("Vani.docx")
    webapp.runs._running = True
    res = client.post("/api/run", json={"phase": "both"})
    assert res.status_code == 409
    assert res.get_json()["ok"] is False
    webapp.runs._running = False
