"""Fail-closed OAuth resource-server configuration for remote ChatGPT/Grok MCP.

An OAuth authorization server (Auth0, Keycloak, Entra, etc.) issues user tokens.
This service only validates those JWTs; it does not invent its own login flow.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt
from jwt import PyJWKClient, PyJWTError
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl


def _https_url(value: str, *, endpoint: bool = False) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError("Remote MCP and OAuth URLs must be valid public HTTPS URLs")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Remote URLs cannot use loopback")
    if endpoint and parsed.path != "/mcp":
        raise ValueError("OPENMONTAGE_PUBLIC_MCP_URL must end in /mcp")
    return value


@dataclass(frozen=True)
class RemoteAuthConfig:
    public_url: str
    issuer: str
    jwks_url: str
    audience: str
    subject: str

    @classmethod
    def from_env(cls):
        variables = ("OPENMONTAGE_PUBLIC_MCP_URL", "OPENMONTAGE_OAUTH_ISSUER",
                     "OPENMONTAGE_OAUTH_JWKS_URL", "OPENMONTAGE_OAUTH_AUDIENCE", "OPENMONTAGE_ALLOWED_SUBJECT")
        present = [bool(os.getenv(key)) for key in variables]
        if not any(present):
            return None  # Local development only; this mode cannot serve a public hostname.
        if not all(present):
            raise ValueError("Public MCP mode requires all five OPENMONTAGE OAuth settings; refusing insecure startup")
        values = [os.environ[key].strip() for key in variables]
        if not values[3] or not values[4]:
            raise ValueError("Audience and allowed subject must be nonempty")
        return cls(_https_url(values[0], endpoint=True), _https_url(values[1]),
                   _https_url(values[2]), values[3], values[4])


class VerifiedJWT(TokenVerifier):
    def __init__(self, config: RemoteAuthConfig):
        self.config = config
        self.jwks = PyJWKClient(config.jwks_url, cache_jwk_set=True, lifespan=300)

    async def verify_token(self, token: str) -> AccessToken | None:
        def _verify():
            key = self.jwks.get_signing_key_from_jwt(token)
            return jwt.decode(token, key.key, algorithms=["RS256", "ES256"],
                              audience=self.config.audience, issuer=self.config.issuer,
                              options={"require": ["exp", "iat", "iss", "sub", "aud"]}, leeway=15)
        try:
            claims = await asyncio.to_thread(_verify)
            if claims.get("sub") != self.config.subject:
                return None
            raw = claims.get("scope", "")
            scopes = raw.split() if isinstance(raw, str) else claims.get("permissions", [])
            if not isinstance(scopes, list) or "video:read" not in scopes:
                return None
            return AccessToken(token=token, client_id=str(claims.get("azp") or claims.get("client_id") or claims["sub"]),
                               subject=claims["sub"], scopes=scopes, expires_at=claims["exp"], resource=self.config.public_url)
        except (PyJWTError, ValueError, KeyError, TypeError, OSError):
            return None


def auth_kwargs(config: RemoteAuthConfig | None):
    if config is None:
        return {}
    return {"token_verifier": VerifiedJWT(config),
            "auth": AuthSettings(issuer_url=AnyHttpUrl(config.issuer),
                                 resource_server_url=AnyHttpUrl(config.public_url),
                                 required_scopes=["video:read"], validate_token_resource=False)}


def security_settings(config: RemoteAuthConfig | None):
    from mcp.server.transport_security import TransportSecuritySettings
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    if config:
        domain = urlsplit(config.public_url).hostname
        hosts.extend([domain, domain + ":*"])
        origins.extend(["https://" + domain, "https://" + domain + ":*"])
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)
