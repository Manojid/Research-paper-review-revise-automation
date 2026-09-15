"""ApiProvider: preflight/key handling and the file-based generate() contract.

No real network call and no real keyring access in any of these — the SDKs
are monkeypatched (or left absent, to exercise the "not installed" path) and
secrets_store is monkeypatched so nothing touches the real OS credential
store.
"""

import sys
import types

import pytest

from paper_automation.config import ProviderConfig
from paper_automation.models import FailureKind, ProviderError
from paper_automation.providers.api_provider import (
    AnthropicApiProvider,
    OpenAiApiProvider,
)


@pytest.fixture
def provider_cfg():
    return ProviderConfig()


def test_preflight_fails_without_a_stored_key(monkeypatch, provider_cfg):
    monkeypatch.setattr(
        "paper_automation.providers.api_provider.secrets_store.get_api_key",
        lambda vendor: "",
    )
    provider = AnthropicApiProvider(provider_cfg)

    with pytest.raises(ProviderError) as excinfo:
        provider.preflight()
    assert excinfo.value.kind is FailureKind.AUTH_REQUIRED


def test_preflight_passes_with_a_stored_key(monkeypatch, provider_cfg):
    monkeypatch.setattr(
        "paper_automation.providers.api_provider.secrets_store.get_api_key",
        lambda vendor: "sk-test",
    )
    AnthropicApiProvider(provider_cfg).preflight()  # must not raise


def test_invoke_without_a_key_raises_auth_required(monkeypatch, provider_cfg, tmp_path):
    monkeypatch.setattr(
        "paper_automation.providers.api_provider.secrets_store.get_api_key",
        lambda vendor: "",
    )
    provider = AnthropicApiProvider(provider_cfg)

    with pytest.raises(ProviderError) as excinfo:
        provider.generate(tmp_path, "review this paper")
    assert excinfo.value.kind is FailureKind.AUTH_REQUIRED


def test_invoke_without_the_sdk_installed_raises_binary_missing(
    monkeypatch, provider_cfg, tmp_path
):
    monkeypatch.setattr(
        "paper_automation.providers.api_provider.secrets_store.get_api_key",
        lambda vendor: "sk-test",
    )
    monkeypatch.setitem(sys.modules, "anthropic", None)  # import anthropic -> ImportError
    (tmp_path / "manuscript.md").write_text("Some paper text.", encoding="utf-8")
    provider = AnthropicApiProvider(provider_cfg)

    with pytest.raises(ProviderError) as excinfo:
        provider.generate(tmp_path, "review this paper")
    assert excinfo.value.kind is FailureKind.BINARY_MISSING
    assert "pip install anthropic" in str(excinfo.value)


def _fake_anthropic_module(reply_text: str):
    """A minimal stand-in for the `anthropic` package's public surface."""
    module = types.ModuleType("anthropic")

    class AuthenticationError(Exception):
        pass

    class RateLimitError(Exception):
        pass

    class APIError(Exception):
        pass

    class Block:
        type = "text"
        text = reply_text

    class Response:
        content = [Block()]

    class Messages:
        def create(self, **kwargs):
            return Response()

    class Anthropic:
        def __init__(self, api_key):
            self.messages = Messages()

    module.Anthropic = Anthropic
    module.AuthenticationError = AuthenticationError
    module.RateLimitError = RateLimitError
    module.APIError = APIError
    return module


def test_generate_writes_output_and_reads_manuscript(monkeypatch, provider_cfg, tmp_path):
    monkeypatch.setattr(
        "paper_automation.providers.api_provider.secrets_store.get_api_key",
        lambda vendor: "sk-test",
    )
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("the review text"))
    (tmp_path / "manuscript.md").write_text("Some paper text.", encoding="utf-8")

    text = AnthropicApiProvider(provider_cfg).generate(tmp_path, "review this paper")

    assert text == "the review text"
    assert (tmp_path / "output.md").read_text(encoding="utf-8") == "the review text"


def test_model_label_defaults_when_no_model_configured(provider_cfg):
    assert AnthropicApiProvider(provider_cfg).model_label == "claude-sonnet-5"
    assert OpenAiApiProvider(provider_cfg).model_label == "gpt-5"


def test_model_label_uses_configured_model():
    cfg = ProviderConfig(model="claude-opus-5")
    assert AnthropicApiProvider(cfg).model_label == "claude-opus-5"
