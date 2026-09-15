"""API key storage for provider_mode = "api".

Keys are never written to config.toml or held on a Config/ProviderConfig
object — they live only in the OS credential store (Windows Credential
Manager, DPAPI-encrypted per-user, via the `keyring` package) and are
fetched by ApiProvider at the moment of each call. This keeps them out of
logging_setup.py's redaction path entirely, since nothing that logs ever
holds the raw value.
"""

import keyring
import keyring.errors

_SERVICE = "PaperReviewAutomation"
_KEYS = {"anthropic": "anthropic_api_key", "openai": "openai_api_key"}


def get_api_key(vendor: str) -> str:
    """The stored key for `vendor`, or "" if none is set (never raises)."""
    try:
        return keyring.get_password(_SERVICE, _KEYS[vendor]) or ""
    except keyring.errors.KeyringError:
        return ""


def set_api_key(vendor: str, value: str) -> None:
    if value:
        keyring.set_password(_SERVICE, _KEYS[vendor], value)


def clear_api_key(vendor: str) -> None:
    try:
        keyring.delete_password(_SERVICE, _KEYS[vendor])
    except keyring.errors.PasswordDeleteError:
        pass  # already absent
