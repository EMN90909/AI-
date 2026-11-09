import pytest
from chatgpt_bridge.remote_auth import RemoteAuthConfig, security_settings
from chatgpt_bridge.grok_mcp_demo import build_request, READ_ONLY_TOOLS


def test_remote_requires_complete_oauth(monkeypatch):
    keys = ["OPENMONTAGE_PUBLIC_MCP_URL", "OPENMONTAGE_OAUTH_ISSUER", "OPENMONTAGE_OAUTH_JWKS_URL",
            "OPENMONTAGE_OAUTH_AUDIENCE", "OPENMONTAGE_ALLOWED_SUBJECT"]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    assert RemoteAuthConfig.from_env() is None
    monkeypatch.setenv(keys[0], "https://mcp.example.org/mcp")
    with pytest.raises(ValueError):
        RemoteAuthConfig.from_env()
    monkeypatch.setenv(keys[1], "https://auth.example.org/")
    monkeypatch.setenv(keys[2], "https://auth.example.org/keys.json")
    monkeypatch.setenv(keys[3], "urn:openmontage")
    monkeypatch.setenv(keys[4], "operator-123")
    data = RemoteAuthConfig.from_env()
    assert data.issuer == "https://auth.example.org/"
    assert "mcp.example.org" in security_settings(data).allowed_hosts
    monkeypatch.setenv(keys[0], "http://localhost:8765/mcp")
    with pytest.raises(ValueError):
        RemoteAuthConfig.from_env()


def test_grok_client_uses_read_only_allowlist():
    req = build_request("List video pipelines", "https://mcp.example.org/mcp")
    assert req["tools"][0]["allowed_tools"] == READ_ONLY_TOOLS
    assert "start_local_render" not in READ_ONLY_TOOLS
    with pytest.raises(ValueError):
        build_request("Hello", "http://localhost:8765/mcp")
