"""Local encrypted, multi-account AI provider key vault.

Never returns raw credentials to HTTP/MCP clients. Keys are encrypted at rest
using the operator-supplied Fernet key, which must never enter Git.
"""
from __future__ import annotations

import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

# Fixed upstream HTTPS origins, never configurable through the web UI: no SSRF.
PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY"},
    "gemini": {"name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "env": "GEMINI_API_KEY"},
    "openrouter": {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "env": "OPENROUTER_API_KEY"},
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com", "env": "DEEPSEEK_API_KEY"},
    "grok": {"name": "Grok (xAI)", "base_url": "https://api.x.ai/v1", "env": "XAI_API_KEY"},
    "groq": {"name": "Groq Cloud", "base_url": "https://api.groq.com/openai/v1", "env": "GROQ_API_KEY"},
    "mistral": {"name": "Mistral", "base_url": "https://api.mistral.ai/v1", "env": "MISTRAL_API_KEY"},
    "together": {"name": "Together AI", "base_url": "https://api.together.xyz/v1", "env": "TOGETHER_API_KEY"},
}

# Use host-local .openmontage directory, already in the application's .gitignore
VAULT_PATH = Path(__file__).resolve().parents[1] / ".openmontage" / "provider_keys.sqlite3"
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:+-]{0,127}$")


class VaultConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecretEntry:
    id: str
    provider: str
    label: str
    model: str
    api_key: str


class KeyVault:
    def __init__(self, path: Path | None = None, encryption_key: str | None = None):
        self.path = Path(path or os.getenv("OPENMONTAGE_VAULT_PATH") or VAULT_PATH)
        raw = encryption_key or os.getenv("OPENMONTAGE_VAULT_KEY")
        if not raw:
            raise VaultConfigurationError("Set OPENMONTAGE_VAULT_KEY to a generated Fernet key; never commit it")
        try:
            self.fernet = Fernet(raw.encode() if isinstance(raw, str) else raw)
        except (ValueError, TypeError) as exc:
            raise VaultConfigurationError("OPENMONTAGE_VAULT_KEY must be a valid Fernet key") from exc
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.path.parent, 0o700)
        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def _initialize(self):
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL, label TEXT NOT NULL,
                model TEXT NOT NULL, encrypted_key BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
            db.commit()
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    @staticmethod
    def _validate(provider: str, label: str, model: str, key: str):
        if provider not in PROVIDERS:
            raise ValueError("Unsupported AI provider")
        if not (1 <= len(label.strip()) <= 64) or any(c in label for c in "\r\n\x00"):
            raise ValueError("Label must be 1-64 characters on one line")
        if not MODEL_RE.fullmatch(model):
            raise ValueError("Invalid model ID")
        if not (8 <= len(key) <= 512) or any(c.isspace() for c in key):
            raise ValueError("API key must be 8-512 characters and contain no whitespace")

    def add(self, provider: str, label: str, model: str, key: str) -> dict[str, Any]:
        self._validate(provider, label, model, key)
        entry_id = str(uuid.uuid4())
        encrypted = self.fernet.encrypt(key.encode("utf-8"))
        with self._connect() as db:
            if db.execute("SELECT count(*) FROM api_keys").fetchone()[0] >= 100:
                raise ValueError("Key vault limit reached (100)")
            db.execute("INSERT INTO api_keys(id,provider,label,model,encrypted_key) VALUES (?,?,?,?,?)",
                       (entry_id, provider, label.strip(), model, encrypted))
        return {"id": entry_id, "provider": provider, "label": label.strip(), "model": model}

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT id,provider,label,model,created_at FROM api_keys ORDER BY created_at DESC, id").fetchall()
        return [{"id": row[0], "provider": row[1], "label": row[2], "model": row[3],
                 "created_at": row[4], "configured": True} for row in rows]

    def resolve(self, entry_id: str) -> SecretEntry:
        try:
            entry_id = str(uuid.UUID(entry_id))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid key ID") from exc
        with self._connect() as db:
            row = db.execute("SELECT id,provider,label,model,encrypted_key FROM api_keys WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise LookupError("Key ID not found")
        try:
            value = self.fernet.decrypt(row[4]).decode("utf-8")
        except InvalidToken as exc:
            raise VaultConfigurationError("Cannot decrypt key: check vault encryption key") from exc
        return SecretEntry(id=row[0], provider=row[1], label=row[2], model=row[3], api_key=value)

    def delete(self, entry_id: str) -> bool:
        try:
            entry_id = str(uuid.UUID(entry_id))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid key ID") from exc
        with self._connect() as db:
            result = db.execute("DELETE FROM api_keys WHERE id=?", (entry_id,))
        return result.rowcount == 1


def call_provider(entry_id: str, prompt: str, *, max_tokens: int = 700, vault: KeyVault | None = None) -> str:
    """Explicitly requested paid provider call. Fixed endpoints, no redirects, bounded tokens."""
    if not isinstance(prompt, str) or not (1 <= len(prompt) <= 6000):
        raise ValueError("Prompt must be 1-6000 characters")
    if not (1 <= max_tokens <= 1500):
        raise ValueError("Token cap must be 1-1500")
    secret = (vault or KeyVault()).resolve(entry_id)
    info = PROVIDERS[secret.provider]
    import httpx
    try:
        with httpx.Client(timeout=35, follow_redirects=False) as client:
            response = client.post(info["base_url"] + "/chat/completions",
                                   headers={"Authorization": "Bearer " + secret.api_key, "Content-Type": "application/json"},
                                   json={"model": secret.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens})
        if response.status_code != 200:
            # Never include provider response text; it could echo user keys or private payloads.
            raise RuntimeError(f"{info['name']} returned HTTP {response.status_code}; check the model and account billing")
        data = response.json()
        answer = data["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer:
            raise RuntimeError("Provider did not return text")
        return answer[:16000]
    except httpx.RequestError as exc:
        raise RuntimeError("Provider request failed; check network connectivity") from None
