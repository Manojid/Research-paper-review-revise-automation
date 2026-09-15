from .base import CliProvider, MockProvider

__all__ = ["CliProvider", "MockProvider", "build_providers"]


def build_providers(cfg):
    """Return (review_provider, revision_provider).

    provider_mode "auto" means mock in test mode, the real CLIs otherwise.
    "api" swaps the CLI subscriptions for billed API calls (see
    api_provider.py) — same review/revision role split, same config slots.
    """
    mode = (cfg.provider_mode or "auto").lower()
    if mode == "mock" or (mode == "auto" and cfg.test_mode):
        return MockProvider(), MockProvider()

    if mode == "api":
        from .api_provider import AnthropicApiProvider, OpenAiApiProvider

        return AnthropicApiProvider(cfg.codex), OpenAiApiProvider(cfg.claude)

    from .claude_code import ClaudeCodeProvider
    from .codex import CodexProvider

    return CodexProvider(cfg.codex), ClaudeCodeProvider(cfg.claude)
