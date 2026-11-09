from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chatgpt_bridge import settings_ui
from chatgpt_bridge.provider_store import KeyVault


def build_client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMONTAGE_VAULT_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OPENMONTAGE_VAULT_PATH", str(tmp_path / "keys.sqlite"))
    monkeypatch.setenv("OPENMONTAGE_SETTINGS_PASSWORD", "exampleVeryStrongPassword")
    monkeypatch.setenv("OPENMONTAGE_SETTINGS_SECRET", "s" * 60)
    app = FastAPI()
    app.include_router(settings_ui.router)
    return TestClient(app)


def test_login_csrf_add_delete_no_key_exposure(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    assert "API settings login" in client.get("/settings/api").text
    result = client.post("/settings/api/login", data={"password": "exampleVeryStrongPassword"}, follow_redirects=False)
    assert result.status_code == 303
    page = client.get("/settings/api").text
    csrf = page.split("name='csrf' value='")[1].split("'")[0]
    denied = client.post("/settings/api/add", data={"provider": "grok", "label": "Grok", "model": "grok-4.5",
                                                        "api_key": "exampleGrokKeyXYZ"})
    assert denied.status_code == 403
    accepted = client.post("/settings/api/add", data={"csrf": csrf, "provider": "grok", "label": "Grok",
                                                          "model": "grok-4.5", "api_key": "exampleGrokKeyXYZ"}, follow_redirects=False)
    assert accepted.status_code == 303
    assert "exampleGrokKeyXYZ" not in client.get("/settings/api").text
    assert len(KeyVault().list()) == 1
    key_id = KeyVault().list()[0]["id"]
    deleted = client.post("/settings/api/delete", data={"csrf": csrf, "id": key_id}, follow_redirects=False)
    assert deleted.status_code == 303
    assert KeyVault().list() == []


def test_external_client_denied(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    with patch.object(settings_ui, "_local", return_value=False):
        assert client.get("/settings/api").status_code == 403
