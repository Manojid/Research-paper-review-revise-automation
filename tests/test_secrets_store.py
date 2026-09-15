"""secrets_store: a thin keyring wrapper — no real OS credential store touched."""

import keyring.errors
import pytest

from paper_automation import secrets_store


class FakeKeyring:
    def __init__(self):
        self._data = {}

    def get_password(self, service, key):
        return self._data.get((service, key))

    def set_password(self, service, key, value):
        self._data[(service, key)] = value

    def delete_password(self, service, key):
        if (service, key) not in self._data:
            raise keyring.errors.PasswordDeleteError("not found")
        del self._data[(service, key)]


@pytest.fixture
def fake(monkeypatch):
    backend = FakeKeyring()
    monkeypatch.setattr(secrets_store.keyring, "get_password", backend.get_password)
    monkeypatch.setattr(secrets_store.keyring, "set_password", backend.set_password)
    monkeypatch.setattr(secrets_store.keyring, "delete_password", backend.delete_password)
    return backend


def test_get_api_key_returns_empty_string_when_unset(fake):
    assert secrets_store.get_api_key("anthropic") == ""


def test_set_then_get_round_trips(fake):
    secrets_store.set_api_key("anthropic", "sk-abc123")
    assert secrets_store.get_api_key("anthropic") == "sk-abc123"


def test_set_api_key_with_blank_value_is_a_no_op(fake):
    secrets_store.set_api_key("openai", "")
    assert secrets_store.get_api_key("openai") == ""


def test_clear_api_key_removes_a_stored_key(fake):
    secrets_store.set_api_key("openai", "sk-xyz")
    secrets_store.clear_api_key("openai")
    assert secrets_store.get_api_key("openai") == ""


def test_clear_api_key_when_already_absent_does_not_raise(fake):
    secrets_store.clear_api_key("openai")  # must not raise


def test_get_api_key_never_raises_on_keyring_errors(monkeypatch):
    def boom(service, key):
        raise keyring.errors.KeyringError("backend unavailable")

    monkeypatch.setattr(secrets_store.keyring, "get_password", boom)
    assert secrets_store.get_api_key("anthropic") == ""


def test_vendors_use_distinct_keys(fake):
    secrets_store.set_api_key("anthropic", "a-key")
    secrets_store.set_api_key("openai", "o-key")
    assert secrets_store.get_api_key("anthropic") == "a-key"
    assert secrets_store.get_api_key("openai") == "o-key"
