"""config.load()'s validated fields — provider_mode in particular, which was
previously not read from config.toml at all (it silently stayed at the
dataclass default). Mirrors the existing pattern for task_mode/storage_backend
validation in config.py, but as tests since none existed yet for those either.
"""

import pytest

from paper_automation import config as config_module


def _write_config(tmp_path, **extra_lines):
    lines = [f'research_papers_root = "{(tmp_path / "Research Papers").as_posix()}"']
    lines.extend(f"{key} = {value}" for key, value in extra_lines.items())
    path = tmp_path / "config.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_provider_mode_defaults_to_auto(tmp_path):
    path = _write_config(tmp_path)
    cfg = config_module.load(path=path, base_dir=tmp_path)
    assert cfg.provider_mode == "auto"


@pytest.mark.parametrize("mode", ["auto", "mock", "real", "api"])
def test_provider_mode_accepts_every_valid_value(tmp_path, mode):
    path = _write_config(tmp_path, provider_mode=f'"{mode}"')
    cfg = config_module.load(path=path, base_dir=tmp_path)
    assert cfg.provider_mode == mode


def test_provider_mode_rejects_a_typo(tmp_path):
    path = _write_config(tmp_path, provider_mode='"apiii"')
    with pytest.raises(config_module.ConfigError) as excinfo:
        config_module.load(path=path, base_dir=tmp_path)
    assert "provider_mode" in str(excinfo.value)


def test_provider_mode_is_case_insensitive(tmp_path):
    path = _write_config(tmp_path, provider_mode='"API"')
    cfg = config_module.load(path=path, base_dir=tmp_path)
    assert cfg.provider_mode == "api"
