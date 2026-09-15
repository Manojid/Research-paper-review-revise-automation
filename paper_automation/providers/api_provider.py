"""API-key-based providers — an alternative to the CLI subscriptions.

Unlike SubprocessProvider, there's no sandboxed working directory the model
can read/write itself: manuscript.md (and review.md, for a revision call) are
read here and folded into the request text, and the response is written to
output.md by hand so CliProvider.generate()'s file-based contract still holds
unchanged (same contract MockProvider follows in base.py).

The SDKs (`anthropic`, `openai`) are optional, lazily imported — an install
that never turns on provider_mode = "api" carries no extra weight. The
`keyring` dependency that stores the actual key is not optional; it's
required regardless of vendor (see secrets_store.py).
"""

import logging
from pathlib import Path

from .. import secrets_store
from ..models import FailureKind, ProviderError
from ..prompts import MANUSCRIPT_FILE, OUTPUT_FILE, REVIEW_FILE
from .base import CliProvider

log = logging.getLogger(__name__)

__all__ = ["AnthropicApiProvider", "OpenAiApiProvider"]


def _read_scratch_files(workdir: Path) -> str:
    """Manuscript, plus the review too when this is a revision call — the
    same is_revision detection MockProvider uses in base.py."""
    manuscript = workdir / MANUSCRIPT_FILE
    text = manuscript.read_text(encoding="utf-8", errors="replace") if manuscript.exists() else ""
    review = workdir / REVIEW_FILE
    if review.exists():
        review_text = review.read_text(encoding="utf-8", errors="replace")
        return (
            f"--- {MANUSCRIPT_FILE} ---\n{text}\n\n"
            f"--- {REVIEW_FILE} ---\n{review_text}"
        )
    return f"--- {MANUSCRIPT_FILE} ---\n{text}"


class _ApiProvider(CliProvider):
    """Shared shape for both vendors. Subclasses supply the SDK call."""

    vendor = ""
    default_model = ""

    def __init__(self, provider_config):
        self.config = provider_config

    @property
    def model_label(self) -> str:
        return self.config.model or self.default_model

    def preflight(self) -> None:
        """No network call here — an API-key check is enough to fail fast,
        and it doesn't spend anything on every startup the way a real
        request would."""
        if not secrets_store.get_api_key(self.vendor):
            raise ProviderError(
                FailureKind.AUTH_REQUIRED,
                f"No {self.vendor} API key is configured. Set it from the "
                "Settings page (Provider mode: API).",
            )

    def _invoke(self, workdir: Path, prompt: str) -> str:
        api_key = secrets_store.get_api_key(self.vendor)
        if not api_key:
            raise ProviderError(
                FailureKind.AUTH_REQUIRED,
                f"No {self.vendor} API key is configured. Set it from the "
                "Settings page (Provider mode: API).",
            )
        message = f"{prompt}\n\n{_read_scratch_files(workdir)}"
        text = self._call(api_key, message)
        (workdir / OUTPUT_FILE).write_text(text, encoding="utf-8")
        return f"{self.vendor} api call completed"

    def _call(self, api_key: str, message: str) -> str:
        raise NotImplementedError


class AnthropicApiProvider(_ApiProvider):
    name = "anthropic-api"
    vendor = "anthropic"
    default_model = "claude-sonnet-5"

    def _call(self, api_key: str, message: str) -> str:
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError(
                FailureKind.BINARY_MISSING,
                "The 'anthropic' package is not installed. Run: "
                "py -m pip install anthropic",
            ) from exc

        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=self.model_label,
                max_tokens=8192,
                messages=[{"role": "user", "content": message}],
            )
        except anthropic.AuthenticationError as exc:
            raise ProviderError(FailureKind.AUTH_REQUIRED, str(exc)) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError(FailureKind.USAGE_LIMIT, str(exc)) from exc
        except anthropic.APIError as exc:
            raise ProviderError(FailureKind.TRANSIENT, str(exc)) from exc

        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )


class OpenAiApiProvider(_ApiProvider):
    name = "openai-api"
    vendor = "openai"
    default_model = "gpt-5"

    def _call(self, api_key: str, message: str) -> str:
        try:
            import openai
        except ImportError as exc:
            raise ProviderError(
                FailureKind.BINARY_MISSING,
                "The 'openai' package is not installed. Run: "
                "py -m pip install openai",
            ) from exc

        try:
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=self.model_label,
                messages=[{"role": "user", "content": message}],
            )
        except openai.AuthenticationError as exc:
            raise ProviderError(FailureKind.AUTH_REQUIRED, str(exc)) from exc
        except openai.RateLimitError as exc:
            raise ProviderError(FailureKind.USAGE_LIMIT, str(exc)) from exc
        except openai.APIError as exc:
            raise ProviderError(FailureKind.TRANSIENT, str(exc)) from exc

        return response.choices[0].message.content or ""
