"""The UI-agnostic service layer.

These matter because the web UI shows the user what a run *will* do. If the status
shown here ever disagrees with the pipeline's own decision, the UI is lying.
"""

import time
from pathlib import Path

import pytest

from paper_automation import service
from paper_automation.models import Decision, Phase
from paper_automation.storage import LocalStorage


# --- status derivation --------------------------------------------------------


def test_status_matches_the_pipeline_decision(cfg, storage, make_client):
    """A folder shown as 'ready for review' must actually be processed."""
    make_client("Vani.docx")
    data = service.scan(cfg, storage, "August 2026")

    row = data["rows"][0]
    assert row["status"] == "READY_REVIEW"
    assert data["counts"]["READY_REVIEW"] == 1


def test_folder_with_review_is_ready_to_revise(cfg, storage, make_client):
    make_client("Vani.docx", "Vani_review.docx")
    row = service.scan(cfg, storage, "August 2026")["rows"][0]
    assert row["status"] == "READY_REVISE"


def test_complete_folder_reports_complete(cfg, storage, make_client):
    make_client("Vani.docx", "Vani_review.docx", "Correct_Vani_paper.docx")
    row = service.scan(cfg, storage, "August 2026")["rows"][0]
    assert row["status"] == "COMPLETE"
    assert len(row["files"]) == 3


def test_ambiguous_folder_is_flagged_not_hidden(cfg, storage, make_client):
    make_client("one.docx", "two.docx")
    row = service.scan(cfg, storage, "August 2026")["rows"][0]
    assert row["status"] == "BLOCKED"
    assert "2 papers in this folder" in row["reason"]


def test_empty_folder_reads_as_waiting(cfg, storage, make_client):
    make_client()
    row = service.scan(cfg, storage, "August 2026")["rows"][0]
    assert row["status"] == "EMPTY"


def test_missing_month_is_reported_not_raised(cfg, storage):
    cfg.research_papers_root.mkdir(parents=True, exist_ok=True)
    data = service.scan(cfg, storage, "December 2099")
    assert data["month_exists"] is False
    assert data["rows"] == []


def test_missing_root_is_reported_not_raised(cfg, storage):
    data = service.scan(cfg, storage, "August 2026")
    assert data["root_exists"] is False
    assert data["rows"] == []


def test_ignored_files_are_surfaced(cfg, storage, make_client):
    make_client("Vani.docx", "~$Vani.docx", "notes.txt")
    row = service.scan(cfg, storage, "August 2026")["rows"][0]
    assert row["status"] == "READY_REVIEW"
    assert len(row["ignored"]) == 2


# --- preview ------------------------------------------------------------------


def test_preview_counts_and_estimates(cfg, storage, make_client):
    """A paper still to be checked costs both phases; one already checked, only one."""
    make_client("A.docx", client="A")
    make_client("B.docx", "B_review.docx", client="B")
    preview = service.dry_run_preview(cfg, storage, "August 2026")

    assert len(preview["would_review"]) == 1
    assert len(preview["would_revise"]) == 1

    per = service.FALLBACK_SECONDS[cfg.task_mode]
    assert preview["estimate_seconds"] == round(per * 2 + per)
    assert preview["estimate_measured"] is False


def test_preview_writes_nothing(cfg, storage, make_client):
    folder = make_client("Vani.docx")
    before = sorted(p.name for p in folder.iterdir())
    service.dry_run_preview(cfg, storage, "August 2026")
    assert sorted(p.name for p in folder.iterdir()) == before


# --- config editing -----------------------------------------------------------


def test_editing_config_preserves_comments(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "# keep me\nresearch_papers_root = \"C:/old\"\ntimezone = \"UTC\"\n"
        "\n[providers.codex]\nmodel = \"\"\n",
        encoding="utf-8",
    )
    applied = service.update_config_file(path, {"research_papers_root": "C:/new"})

    text = path.read_text(encoding="utf-8")
    assert applied == ["research_papers_root"]
    assert "# keep me" in text
    assert '"C:/new"' in text
    assert "[providers.codex]" in text


def test_editing_inserts_an_absent_key_before_the_first_table(tmp_path):
    """provider_mode (added after config.example.toml shipped) is absent from
    any config.toml built before that — must still be insertable, not silently
    dropped just because a [table] header exists further down the file."""
    path = tmp_path / "config.toml"
    path.write_text(
        'research_papers_root = "C:/old"\ntimezone = "UTC"\n'
        '\n[providers.codex]\nmodel = ""\n',
        encoding="utf-8",
    )
    applied = service.update_config_file(path, {"provider_mode": "api"})

    text = path.read_text(encoding="utf-8")
    assert applied == ["provider_mode"]
    assert 'provider_mode = "api"' in text
    assert text.index("provider_mode") < text.index("[providers.codex]")


def test_editing_never_touches_keys_inside_a_table(tmp_path):
    """`model` exists under [providers.codex]; a top-level edit must not reach it."""
    path = tmp_path / "config.toml"
    path.write_text(
        'research_papers_root = "C:/x"\nmax_retries = 3\n\n'
        '[providers.codex]\nmax_retries = 99\n',
        encoding="utf-8",
    )
    service.update_config_file(path, {"max_retries": 5})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert "max_retries = 5" in lines
    assert "max_retries = 99" in lines  # the provider one is untouched


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('research_papers_root = "C:/x"\n', encoding="utf-8")
    applied = service.update_config_file(path, {"evil_key": "boom"})
    assert applied == []
    assert "evil_key" not in path.read_text(encoding="utf-8")


def test_backslash_paths_are_normalised(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('research_papers_root = "C:/x"\n', encoding="utf-8")
    service.update_config_file(path, {"research_papers_root": r"C:\Users\me\Papers"})
    assert 'research_papers_root = "C:/Users/me/Papers"' in path.read_text(encoding="utf-8")


def test_list_values_render_as_toml_arrays(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('supported_extensions = [".docx"]\n', encoding="utf-8")
    service.update_config_file(path, {"supported_extensions": ".docx, .pdf"})
    assert 'supported_extensions = [".docx", ".pdf"]' in path.read_text(encoding="utf-8")


# --- file opening is confined ------------------------------------------------


def test_open_refuses_paths_outside_the_configured_tree(cfg, tmp_path):
    outside = tmp_path / "elsewhere" / "secret.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("x", encoding="utf-8")

    result = service.open_in_explorer(outside, cfg)
    assert result["ok"] is False
    assert "outside" in result["message"]


def test_open_reports_a_missing_file_clearly(cfg, make_client):
    folder = make_client()
    result = service.open_in_explorer(folder / "nope.docx", cfg)
    assert result["ok"] is False
    assert "no longer exists" in result["message"]


# --- run manager --------------------------------------------------------------


def test_run_manager_refuses_a_second_concurrent_run(cfg, storage, make_client):
    make_client("Vani.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager._running = True  # simulate a run in flight

    result = manager.start(cfg, storage, {"phase": "both"})
    assert result["ok"] is False
    assert "already in progress" in result["message"]


def test_run_manager_reports_a_missing_month_without_crashing(cfg, storage):
    cfg.research_papers_root.mkdir(parents=True, exist_ok=True)
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "both", "month": "December 2099"})
    manager._thread.join(timeout=10)

    status = manager.status()
    assert status["running"] is False
    assert "not found" in status["error"]


def test_run_manager_completes_a_mock_run(cfg, storage, make_client):
    make_client("Vani.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "review"})
    manager._thread.join(timeout=60)

    status = manager.status()
    assert status["running"] is False
    assert status["error"] == ""
    assert status["done"] == status["total"] == 1
    assert "REVIEW STAGE" in status["summary"]
    assert any("created" in line["text"] for line in status["log"])


def test_progress_counts_skipped_folders_too(cfg, storage, make_client):
    """Otherwise a run of already-complete folders finishes showing 0 of N."""
    make_client("Vani.docx", "Vani_review.docx", "Correct_Vani_paper.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "both"})
    manager._thread.join(timeout=60)

    status = manager.status()
    assert status["total"] > 0
    assert status["done"] == status["total"]


# --- task mode ----------------------------------------------------------------
#
# Grammar mode exists so the pipeline can be built and tested without spending a
# full review's tokens on every run. Picking the wrong prompt set is expensive, so
# the wiring is pinned here.


def test_grammar_mode_selects_the_language_prompts():
    from paper_automation import prompts

    review, revise = prompts.for_mode("grammar")
    assert review is prompts.grammar_review_prompt
    assert revise is prompts.grammar_revision_prompt


def test_full_mode_selects_the_journal_prompts():
    from paper_automation import prompts

    review, revise = prompts.for_mode("full")
    assert review is prompts.review_prompt
    assert revise is prompts.revision_prompt


def test_grammar_prompts_forbid_touching_the_science():
    from paper_automation import prompts

    review = prompts.grammar_review_prompt("Vani", "Vani.docx", "10-Aug-2026")
    revise = prompts.grammar_revision_prompt("Vani", "Vani.docx")

    assert "LANGUAGE" in review
    assert "Do NOT assess methodology" in review
    for text in (review, revise):
        assert "number" in text.lower()
    assert "Change NOTHING else" in revise


def test_a_typo_in_task_mode_is_rejected(tmp_path):
    """Silently falling back to 'full' would run the expensive prompts by accident."""
    from paper_automation import config as config_module

    path = tmp_path / "config.toml"
    path.write_text(
        'research_papers_root = "%s"\ntask_mode = "gramar"\n' % tmp_path.as_posix(),
        encoding="utf-8",
    )
    with pytest.raises(config_module.ConfigError, match="task_mode"):
        config_module.load(path, base_dir=tmp_path)


def test_task_mode_defaults_to_grammar(tmp_path):
    from paper_automation import config as config_module

    path = tmp_path / "config.toml"
    path.write_text(
        'research_papers_root = "%s"\n' % tmp_path.as_posix(), encoding="utf-8"
    )
    assert config_module.load(path, base_dir=tmp_path).task_mode == "grammar"


# --- plain language for non-technical readers ---------------------------------
#
# The dashboard is read by someone who did not build this. Internal wording like
# "expected exactly 1 original" is meaningless to them, and the run view must not
# require reading log output.


def test_internal_reasons_are_rewritten_for_a_reader(cfg, storage, make_client):
    make_client()
    row = service.scan(cfg, storage, "August 2026")["rows"][0]
    assert "expected exactly 1" not in row["reason"]
    assert "empty" in row["reason"].lower()


def test_status_labels_avoid_internal_vocabulary(cfg, storage, make_client):
    make_client("Vani.docx")
    row = service.scan(cfg, storage, "August 2026")["rows"][0]
    assert row["status_label"] == "Waiting to be checked"
    assert "review" not in row["action"].lower()


def test_plain_leaves_ordinary_text_alone():
    assert service.plain("Everything was fine.") == "Everything was fine."
    assert service.plain("") == ""


def test_progress_reports_results_without_log_text(cfg, storage, make_client):
    """The run view is built from events, so it works with no logging at all."""
    make_client("Vani.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "review"})
    manager._thread.join(timeout=60)

    status = manager.status()
    assert status["results"], "there must be a structured result per client"
    item = status["results"][0]
    assert item["client"] == "Vani"
    assert item["tone"] == "done"
    assert item["label"] == "Checked"
    assert status["percent"] == 100


def test_headline_is_a_sentence_a_person_can_read(cfg, storage, make_client):
    make_client("Vani.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "review"})
    manager._thread.join(timeout=60)

    headline = manager.status()["headline"]
    assert headline == "All done — 1 finished successfully."


def test_outcome_counts_group_by_what_the_user_must_do(cfg, storage, make_client):
    make_client("one.docx", "two.docx")  # ambiguous -> skipped
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "both"})
    manager._thread.join(timeout=60)

    counts = manager.status()["outcomes"]
    assert counts["skipped"] > 0
    assert counts["failed"] == 0


def test_idle_manager_has_an_empty_headline():
    assert service.RunManager().status()["headline"] == ""


def test_history_rows_carry_a_friendly_label(cfg, storage, make_client):
    make_client("Vani.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "review"})
    manager._thread.join(timeout=60)

    rows = service.history(cfg)
    assert rows
    assert all("friendly" in r for r in rows)
    assert any(r["friendly"] == "Checked" for r in rows)


def test_each_paper_is_listed_once_not_once_per_phase(cfg, storage, make_client):
    """Two phases per paper would otherwise read as two different papers."""
    make_client("Vani.docx", "Vani_review.docx", "Correct_Vani_paper.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "both"})
    manager._thread.join(timeout=60)

    status = manager.status()
    clients = [r["client"] for r in status["results"]]
    assert clients == ["Vani"], clients
    assert status["done"] == status["total"] == 1


# --- the scheduled time must be read, not assumed ------------------------------
#
# The field used to be hard-coded to 09:00, so after any change it showed a time
# the task was not actually set to.


class _FakeRun:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def test_schtasks_suppresses_the_console_window(monkeypatch):
    """The whole point of _CREATE_NO_WINDOW: schtasks.exe must never flash a
    visible console when called from the windowless web UI process."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append(kwargs)
        return _FakeRun("")

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    service._schtasks("/Query")
    assert calls[0].get("creationflags") == service._CREATE_NO_WINDOW


def test_set_schedule_suppresses_the_console_window(monkeypatch, tmp_path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(kwargs)
        return _FakeRun("", returncode=0)

    (tmp_path / "run.py").write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(service.subprocess, "run", fake_run)
    monkeypatch.setattr(service.shutil, "which", lambda name: "C:/Python/py.exe", raising=False)
    service.set_schedule(True, tmp_path, "09:00")
    assert calls[0].get("creationflags") == service._CREATE_NO_WINDOW


def test_set_schedule_registers_the_task_directly_via_schtasks(monkeypatch, tmp_path):
    """No more scripts/register_task.ps1 dependency — this used to fail with
    "Missing ...\\scripts\\register_task.ps1" in every installed (frozen) app,
    since that dev-only script was never bundled or reachable from base_dir
    there (base_dir in a frozen build is the user's data folder, not the
    source tree)."""
    calls = []
    monkeypatch.setattr(
        service, "_schtasks", lambda *args: calls.append(args) or _FakeRun("", returncode=0)
    )
    (tmp_path / "run.py").write_text("# stub", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda name: "C:/Python/py.exe")

    result = service.set_schedule(True, tmp_path, "06:30")

    assert result["ok"] is True
    args = calls[0]
    assert "/Create" in args
    assert "06:30" in args
    tr_index = args.index("/TR")
    assert "run.py" in args[tr_index + 1]
    assert "py.exe" in args[tr_index + 1]


def test_set_schedule_uses_the_frozen_run_exe_when_frozen(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        service, "_schtasks", lambda *args: calls.append(args) or _FakeRun("", returncode=0)
    )
    monkeypatch.setattr(service.sys, "frozen", True, raising=False)
    fake_exe = tmp_path / "paper-review-run.exe"
    fake_exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(service.sys, "executable", str(tmp_path / "PaperReviewAutomationService.exe"))

    result = service.set_schedule(True, tmp_path, "09:00")

    assert result["ok"] is True
    args = calls[0]
    tr_index = args.index("/TR")
    assert "paper-review-run.exe" in args[tr_index + 1]


def test_set_schedule_reports_a_missing_frozen_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(service.sys, "frozen", True, raising=False)
    monkeypatch.setattr(service.sys, "executable", str(tmp_path / "PaperReviewAutomationService.exe"))

    result = service.set_schedule(True, tmp_path, "09:00")

    assert result["ok"] is False
    assert "paper-review-run.exe" in result["message"]


def test_set_schedule_false_deletes_the_task(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        service, "_schtasks", lambda *args: calls.append(args) or _FakeRun("", returncode=0)
    )

    result = service.set_schedule(False, tmp_path)

    assert result["ok"] is True
    assert calls[0] == ("/Delete", "/F", "/TN", service.SCHEDULED_TASK_NAME)


def test_set_schedule_false_tolerates_an_already_absent_task(monkeypatch, tmp_path):
    monkeypatch.setattr(
        service, "_schtasks",
        lambda *args: _FakeRun("ERROR: The system cannot find the file specified.", returncode=1),
    )

    result = service.set_schedule(False, tmp_path)

    assert result["ok"] is True


def test_scheduled_time_is_read_from_the_task_xml(monkeypatch):
    xml = (
        '<?xml version="1.0"?><Task><Triggers><CalendarTrigger>'
        "<StartBoundary>2026-08-11T06:30:00</StartBoundary>"
        "</CalendarTrigger></Triggers></Task>"
    )
    monkeypatch.setattr(service, "_schtasks", lambda *a: _FakeRun(xml))
    assert service.scheduled_time() == "06:30"


def test_utf16_nul_bytes_in_the_xml_are_tolerated(monkeypatch):
    """schtasks /XML emits UTF-16, which can arrive with interleaved NULs."""
    xml = "<StartBoundary>2026-08-11T21:45:00</StartBoundary>"
    monkeypatch.setattr(
        service, "_schtasks", lambda *a: _FakeRun("\x00".join(xml) )
    )
    assert service.scheduled_time() == "21:45"


def test_falls_back_to_next_run_time_when_xml_is_unavailable(monkeypatch):
    def fake(*args):
        if "/XML" in args:
            return _FakeRun("", returncode=1)
        return _FakeRun("Next Run Time: 12/08/2026 6:30:00 AM\nStatus: Ready\n")

    monkeypatch.setattr(service, "_schtasks", fake)
    assert service.scheduled_time() == "06:30"


def test_afternoon_fallback_time_converts_from_twelve_hour(monkeypatch):
    def fake(*args):
        if "/XML" in args:
            return _FakeRun("", returncode=1)
        return _FakeRun("Next Run Time: 12/08/2026 9:20:00 PM\n")

    monkeypatch.setattr(service, "_schtasks", fake)
    assert service.scheduled_time() == "21:20"


def test_midnight_and_noon_convert_correctly(monkeypatch):
    for text, expected in (("12:05:00 AM", "00:05"), ("12:05:00 PM", "12:05")):
        def fake(*args, _t=text):
            if "/XML" in args:
                return _FakeRun("", returncode=1)
            return _FakeRun(f"Next Run Time: 12/08/2026 {_t}\n")

        monkeypatch.setattr(service, "_schtasks", fake)
        assert service.scheduled_time() == expected, text


def test_status_reports_a_time_even_when_nothing_is_scheduled(monkeypatch):
    monkeypatch.setattr(service, "_schtasks", lambda *a: _FakeRun("", returncode=1))
    monkeypatch.setattr(service.sys, "platform", "win32")
    status = service.schedule_status()
    assert status["enabled"] is False
    assert status["time"] == service.DEFAULT_SCHEDULE_TIME


# --- elapsed time and estimates ----------------------------------------------
#
# The estimate used to be a flat three minutes per paper. It is now measured from
# this installation's own history, per task mode, because a grammar pass and a
# full review differ by an order of magnitude.


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0 seconds"), (1, "1 second"), (45, "45 seconds"),
        (60, "1 min"), (75, "1 min 15 sec"), (200, "3 min 20 sec"),
        (3600, "1 hr"), (3700, "1 hr 1 min"), (5400, "1 hr 30 min"),
    ],
)
def test_format_duration(seconds, expected):
    assert service.format_duration(seconds) == expected


def test_estimate_falls_back_before_any_history(cfg):
    per = service.average_seconds(cfg)
    assert per["measured"] is False
    assert per["review"] == service.FALLBACK_SECONDS[cfg.task_mode]


def test_estimate_uses_measured_history(cfg, storage, make_client):
    """Two completed papers is enough to stop guessing."""
    from paper_automation.models import FolderState, Phase, ProcessingState
    from paper_automation.state import StateStore

    folder = FolderState(employee="E", client="C", folder=cfg.research_papers_root)
    with StateStore(Path(cfg.state_db)) as store:
        for seconds in (100.0, 140.0):
            store.record("August 2026", folder, ProcessingState.REVIEW_COMPLETED,
                         phase=Phase.REVIEW, seconds=seconds, task_mode=cfg.task_mode)

    per = service.average_seconds(cfg)
    assert per["measured"] is True
    assert per["review"] == 120.0
    assert per["samples"] == 2


def test_a_single_sample_is_not_enough_to_trust(cfg):
    from paper_automation.models import FolderState, Phase, ProcessingState
    from paper_automation.state import StateStore

    folder = FolderState(employee="E", client="C", folder=cfg.research_papers_root)
    with StateStore(Path(cfg.state_db)) as store:
        store.record("August 2026", folder, ProcessingState.REVIEW_COMPLETED,
                     phase=Phase.REVIEW, seconds=999.0, task_mode=cfg.task_mode)

    assert service.average_seconds(cfg)["measured"] is False


def test_skipped_folders_do_not_drag_the_estimate_down(cfg):
    """A folder skipped in milliseconds would make every prediction far too low."""
    from paper_automation.models import FolderState, Phase, ProcessingState
    from paper_automation.state import StateStore

    folder = FolderState(employee="E", client="C", folder=cfg.research_papers_root)
    with StateStore(Path(cfg.state_db)) as store:
        for _ in range(5):
            store.record("August 2026", folder, ProcessingState.SKIPPED,
                         phase=Phase.REVIEW, seconds=0.01, task_mode=cfg.task_mode)

    assert service.average_seconds(cfg)["measured"] is False


def test_history_from_another_task_mode_is_not_reused(cfg):
    """Full-review timings must not be applied to a grammar run."""
    from paper_automation.models import FolderState, Phase, ProcessingState
    from paper_automation.state import StateStore

    folder = FolderState(employee="E", client="C", folder=cfg.research_papers_root)
    with StateStore(Path(cfg.state_db)) as store:
        for _ in range(4):
            store.record("August 2026", folder, ProcessingState.COMPLETED,
                         phase=Phase.REVIEW, seconds=600.0, task_mode="full")

    cfg.task_mode = "grammar"
    assert service.average_seconds(cfg)["measured"] is False


def test_a_run_reports_how_long_it_took(cfg, storage, make_client):
    make_client("Vani.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "review"})
    manager._thread.join(timeout=60)

    status = manager.status()
    assert status["elapsed_seconds"] > 0
    assert status["elapsed_label"]
    assert status["results"][0]["duration_label"]


def test_elapsed_stops_counting_once_the_run_ends(cfg, storage, make_client):
    """Otherwise the finished figure keeps climbing while the page is open."""
    make_client("Vani.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "review"})
    manager._thread.join(timeout=60)

    first = manager.status()["elapsed_seconds"]
    time.sleep(0.4)
    assert manager.status()["elapsed_seconds"] == first


def test_no_remaining_estimate_once_finished(cfg, storage, make_client):
    make_client("Vani.docx")
    cfg.provider_mode = "mock"
    manager = service.RunManager()
    manager.start(cfg, storage, {"phase": "review"})
    manager._thread.join(timeout=60)
    assert manager.status()["remaining_label"] == ""


# --- start-up cost ------------------------------------------------------------
#
# Asking a CLI for its version starts the whole app — `claude --version` alone is
# about a second — and it was being paid on every page load.


def test_cli_version_is_only_asked_once(cfg, monkeypatch):
    calls = []

    class FakeProvider:
        def version(self):
            calls.append(1)
            return "1.2.3"

    service.clear_version_cache()
    monkeypatch.setattr(service, "_provider_instance", lambda *a: FakeProvider())

    assert service.cli_version("claude", cfg.claude) == "1.2.3"
    assert service.cli_version("claude", cfg.claude) == "1.2.3"
    assert service.cli_version("claude", cfg.claude) == "1.2.3"
    assert len(calls) == 1


def test_version_cache_can_be_forced_to_refresh(cfg, monkeypatch):
    calls = []

    class FakeProvider:
        def version(self):
            calls.append(1)
            return "1.2.3"

    service.clear_version_cache()
    monkeypatch.setattr(service, "_provider_instance", lambda *a: FakeProvider())

    service.cli_version("claude", cfg.claude)
    service.cli_version("claude", cfg.claude, force=True)
    assert len(calls) == 2


def test_a_missing_app_is_cached_as_unavailable_not_retried(cfg, monkeypatch):
    """A missing CLI must not cost a failed subprocess launch on every page."""
    calls = []

    def boom(*_args):
        calls.append(1)
        raise RuntimeError("not installed")

    service.clear_version_cache()
    monkeypatch.setattr(service, "_provider_instance", boom)

    assert service.cli_version("codex", cfg.codex) == ""
    assert service.cli_version("codex", cfg.codex) == ""
    assert len(calls) == 1


def test_providers_with_different_binaries_cache_separately(cfg, monkeypatch):
    from paper_automation.config import ProviderConfig

    seen = []

    class FakeProvider:
        def __init__(self, label):
            self.label = label

        def version(self):
            seen.append(self.label)
            return self.label

    service.clear_version_cache()
    monkeypatch.setattr(
        service, "_provider_instance", lambda _n, c: FakeProvider(c.binary_path or "auto")
    )

    service.cli_version("claude", ProviderConfig(binary_path="a.exe"))
    service.cli_version("claude", ProviderConfig(binary_path="b.exe"))
    assert seen == ["a.exe", "b.exe"]


# --- CLI sign-in ---------------------------------------------------------------


def test_open_cli_login_spawns_codex_login_in_a_new_console(monkeypatch):
    from pathlib import Path as _Path
    from paper_automation.config import ProviderConfig

    calls = []
    monkeypatch.setattr(
        service.subprocess, "Popen",
        lambda args, **kw: calls.append((args, kw)) or None,
    )

    class FakeBinary:
        def __str__(self):
            return "C:/codex/codex.exe"

    monkeypatch.setattr(
        service, "_provider_instance",
        lambda name, cfg: type("P", (), {"binary": FakeBinary()})(),
    )

    ok, message = service.open_cli_login("codex", ProviderConfig())

    assert ok is True
    args, kwargs = calls[0]
    assert args == ["C:/codex/codex.exe", "login"]
    assert kwargs["creationflags"] == service._CREATE_NEW_CONSOLE
    assert "Codex" in message


def test_open_cli_login_spawns_bare_claude_in_a_new_console(monkeypatch):
    from paper_automation.config import ProviderConfig

    calls = []
    monkeypatch.setattr(
        service.subprocess, "Popen",
        lambda args, **kw: calls.append((args, kw)) or None,
    )

    class FakeBinary:
        def __str__(self):
            return "C:/claude/claude.exe"

    monkeypatch.setattr(
        service, "_provider_instance",
        lambda name, cfg: type("P", (), {"binary": FakeBinary()})(),
    )

    ok, message = service.open_cli_login("claude", ProviderConfig())

    assert ok is True
    args, kwargs = calls[0]
    assert args == ["C:/claude/claude.exe"]  # no "login" subcommand for claude
    assert kwargs["creationflags"] == service._CREATE_NEW_CONSOLE
    assert "Claude" in message


def test_open_cli_login_reports_a_missing_binary_without_raising(monkeypatch):
    from paper_automation.config import ProviderConfig
    from paper_automation.models import FailureKind, ProviderError

    class FakeProvider:
        @property
        def binary(self):
            raise ProviderError(FailureKind.BINARY_MISSING, "Could not find codex.")

    monkeypatch.setattr(service, "_provider_instance", lambda name, cfg: FakeProvider())

    ok, message = service.open_cli_login("codex", ProviderConfig())

    assert ok is False
    assert "Could not find codex" in message


# --- reactive CLI auth-failure signal -------------------------------------------


def test_last_auth_failure_is_false_with_no_jobs(cfg):
    from paper_automation.state import StateStore

    with StateStore(cfg.state_db) as store:
        assert service.last_auth_failure(store) is False


def test_last_auth_failure_is_true_after_a_recorded_auth_failure(cfg):
    from paper_automation.models import ProcessingState
    from paper_automation.state import StateStore

    with StateStore(cfg.state_db) as store:
        job_id = store.enqueue_job("August 2026", "Priya", "Acme", Phase.REVIEW)
        store.start_job(job_id)
        store.finish_job(
            job_id, ProcessingState.FAILED,
            "codex exited 1 (AUTH_REQUIRED): not logged in. Please log in.",
        )
        assert service.last_auth_failure(store) is True


def test_last_auth_failure_ignores_unrelated_failures(cfg):
    from paper_automation.models import ProcessingState
    from paper_automation.state import StateStore

    with StateStore(cfg.state_db) as store:
        job_id = store.enqueue_job("August 2026", "Priya", "Acme", Phase.REVIEW)
        store.start_job(job_id)
        store.finish_job(job_id, ProcessingState.FAILED, "Timed out after 1800s.")
        assert service.last_auth_failure(store) is False


# --- proactive CLI sign-in status ------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_provider_with_binary(monkeypatch, path="C:/tool/tool.exe"):
    monkeypatch.setattr(
        service, "_provider_instance",
        lambda name, cfg: type("P", (), {"binary": path})(),
    )


def test_cli_signed_in_true_for_claude_when_json_says_logged_in(monkeypatch, cfg):
    from paper_automation.config import ProviderConfig

    service.clear_signin_cache()
    _fake_provider_with_binary(monkeypatch)
    monkeypatch.setattr(
        service.subprocess, "run",
        lambda *a, **kw: _FakeCompleted(stdout='{"loggedIn": true, "email": "user@example.com"}'),
    )

    assert service.cli_signed_in("claude", ProviderConfig()) is True


def test_cli_signed_in_false_for_claude_when_json_says_logged_out(monkeypatch, cfg):
    from paper_automation.config import ProviderConfig

    service.clear_signin_cache()
    _fake_provider_with_binary(monkeypatch)
    monkeypatch.setattr(
        service.subprocess, "run", lambda *a, **kw: _FakeCompleted(stdout='{"loggedIn": false}')
    )

    assert service.cli_signed_in("claude", ProviderConfig()) is False


def test_cli_signed_in_none_for_claude_on_unparseable_output(monkeypatch, cfg):
    from paper_automation.config import ProviderConfig

    service.clear_signin_cache()
    _fake_provider_with_binary(monkeypatch)
    monkeypatch.setattr(
        service.subprocess, "run", lambda *a, **kw: _FakeCompleted(stdout="not json")
    )

    assert service.cli_signed_in("claude", ProviderConfig()) is None


def test_cli_signed_in_true_for_codex_reads_stderr(monkeypatch, cfg):
    """Confirmed by hand: `codex login status` writes to stderr, not stdout."""
    from paper_automation.config import ProviderConfig

    service.clear_signin_cache()
    _fake_provider_with_binary(monkeypatch)
    monkeypatch.setattr(
        service.subprocess, "run",
        lambda *a, **kw: _FakeCompleted(stderr="Logged in using ChatGPT\n"),
    )

    assert service.cli_signed_in("codex", ProviderConfig()) is True


def test_cli_signed_in_false_for_codex_on_a_signed_out_phrase(monkeypatch, cfg):
    from paper_automation.config import ProviderConfig

    service.clear_signin_cache()
    _fake_provider_with_binary(monkeypatch)
    monkeypatch.setattr(
        service.subprocess, "run",
        lambda *a, **kw: _FakeCompleted(stderr="Not logged in.\n"),
    )

    assert service.cli_signed_in("codex", ProviderConfig()) is False


def test_cli_signed_in_none_for_codex_on_a_nonzero_exit(monkeypatch, cfg):
    from paper_automation.config import ProviderConfig

    service.clear_signin_cache()
    _fake_provider_with_binary(monkeypatch)
    monkeypatch.setattr(
        service.subprocess, "run", lambda *a, **kw: _FakeCompleted(returncode=1, stderr="boom")
    )

    assert service.cli_signed_in("codex", ProviderConfig()) is None


def test_cli_signed_in_none_when_the_binary_is_missing(monkeypatch, cfg):
    from paper_automation.config import ProviderConfig
    from paper_automation.models import FailureKind, ProviderError

    service.clear_signin_cache()

    class MissingBinaryProvider:
        @property
        def binary(self):
            raise ProviderError(FailureKind.BINARY_MISSING, "Could not find codex.")

    monkeypatch.setattr(service, "_provider_instance", lambda name, cfg: MissingBinaryProvider())

    assert service.cli_signed_in("codex", ProviderConfig()) is None


def test_cli_signed_in_none_on_timeout(monkeypatch, cfg):
    import subprocess as sp
    from paper_automation.config import ProviderConfig

    service.clear_signin_cache()
    _fake_provider_with_binary(monkeypatch)

    def boom(*a, **kw):
        raise sp.TimeoutExpired(cmd="x", timeout=15)

    monkeypatch.setattr(service.subprocess, "run", boom)

    assert service.cli_signed_in("codex", ProviderConfig()) is None


def test_cli_signed_in_is_cached(monkeypatch, cfg):
    from paper_automation.config import ProviderConfig

    service.clear_signin_cache()
    _fake_provider_with_binary(monkeypatch)
    calls = []
    monkeypatch.setattr(
        service.subprocess, "run",
        lambda *a, **kw: calls.append(1) or _FakeCompleted(stderr="Logged in using ChatGPT\n"),
    )

    service.cli_signed_in("codex", ProviderConfig())
    service.cli_signed_in("codex", ProviderConfig())

    assert len(calls) == 1


def test_model_status_includes_signed_in_only_outside_api_mode(monkeypatch, cfg):
    service.clear_version_cache()
    service.clear_signin_cache()
    monkeypatch.setattr(service, "cli_version", lambda *a, **kw: "1.0.0")
    monkeypatch.setattr(service, "cli_signed_in", lambda *a, **kw: True)

    cfg.provider_mode = "real"
    status = service.model_status(cfg, cfg.research_papers_root.parent)
    assert status["signed_in"] == {"codex": True, "claude": True}

    cfg.provider_mode = "api"
    status = service.model_status(cfg, cfg.research_papers_root.parent)
    assert status["signed_in"] == {}


# --- folder browser --------------------------------------------------------


def test_browse_folders_lists_subfolders_sorted(tmp_path):
    (tmp_path / "Zebra").mkdir()
    (tmp_path / "Acme").mkdir()
    (tmp_path / "not_a_folder.txt").write_text("x", encoding="utf-8")

    result = service.browse_folders(str(tmp_path))

    assert result["ok"] is True
    assert result["path"] == str(tmp_path.resolve())
    names = [f["name"] for f in result["folders"]]
    assert names == ["Acme", "Zebra"]  # sorted, files excluded


def test_browse_folders_reports_the_parent(tmp_path):
    child = tmp_path / "sub"
    child.mkdir()
    result = service.browse_folders(str(child))
    assert result["parent"] == str(tmp_path.resolve())


def test_browse_folders_defaults_to_home_when_path_is_blank(monkeypatch, tmp_path):
    monkeypatch.setattr(service.Path, "home", classmethod(lambda cls: tmp_path))
    result = service.browse_folders("")
    assert result["ok"] is True
    assert result["path"] == str(tmp_path.resolve())


def test_browse_folders_falls_back_to_the_parent_of_a_file_path(tmp_path):
    a_file = tmp_path / "manuscript.docx"
    a_file.write_text("x", encoding="utf-8")
    result = service.browse_folders(str(a_file))
    assert result["ok"] is True
    assert result["path"] == str(tmp_path.resolve())


def test_browse_folders_falls_back_to_home_for_a_nonexistent_path(monkeypatch, tmp_path):
    monkeypatch.setattr(service.Path, "home", classmethod(lambda cls: tmp_path))
    result = service.browse_folders(str(tmp_path / "does" / "not" / "exist"))
    assert result["ok"] is True
    assert result["path"] == str(tmp_path.resolve())


def test_browse_folders_survives_an_unreadable_entry(monkeypatch, tmp_path):
    """A single protected/unreadable subfolder must not break the whole
    listing — is_dir() can raise PermissionError on some Windows folders."""
    real_is_dir = Path.is_dir

    def flaky_is_dir(self):
        if self.name == "Protected":
            raise PermissionError("Access is denied")
        return real_is_dir(self)

    (tmp_path / "Protected").mkdir()
    (tmp_path / "Normal").mkdir()
    monkeypatch.setattr(service.Path, "is_dir", flaky_is_dir)

    result = service.browse_folders(str(tmp_path))

    assert result["ok"] is True
    names = [f["name"] for f in result["folders"]]
    assert names == ["Normal"]
