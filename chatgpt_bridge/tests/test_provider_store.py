import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from chatgpt_bridge.provider_store import KeyVault, PROVIDERS, call_provider


def vault(tmp_path):
    return KeyVault(tmp_path / "vault.db", Fernet.generate_key().decode())


def test_multiple_keys_and_encryption(tmp_path):
    store = vault(tmp_path)
    one = store.add("gemini", "Personal", "gemini-2.5-flash", "exampleGeminiKey123")
    two = store.add("gemini", "Other", "gemini-2.5-pro", "exampleGeminiKey987")
    three = store.add("grok", "xAI", "grok-4.5", "exampleGrokKey123")
    public = store.list()
    assert len(public) == 3
    assert all("api_key" not in item for item in public)
    assert "exampleGeminiKey123" not in (tmp_path / "vault.db").read_bytes().decode("latin1")
    assert store.resolve(one["id"]).api_key == "exampleGeminiKey123"
    assert store.resolve(three["id"]).provider == "grok"
    assert store.delete(two["id"])
    assert len(store.list()) == 2
    assert not store.delete(two["id"])


def test_rejects_bad_inputs(tmp_path):
    store = vault(tmp_path)
    for provider in ("http://evil.test", "unknown", "__class__"):
        with pytest.raises(ValueError):
            store.add(provider, "Name", "good-model", "exampleKey123")
    with pytest.raises(ValueError):
        store.add("openai", "test", "bad model", "exampleKey123")
    with pytest.raises(ValueError):
        store.resolve("../../../secret")
    with pytest.raises(ValueError):
        call_provider("bad", "")


def test_encryption_key_required(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMONTAGE_VAULT_KEY", raising=False)
    with pytest.raises(Exception):
        KeyVault(tmp_path / "vault.db")


def test_fixed_https_provider_endpoints():
    assert {"openai", "gemini", "openrouter", "deepseek", "grok"} <= PROVIDERS.keys()
    assert all(info["base_url"].startswith("https://") for info in PROVIDERS.values())
