"""Backlot /settings/api: local-only credential manager for OpenMontage.

The Backlot server already binds to loopback and validates Host. This router
also checks the *actual socket peer* and requires an operator password; it must
never be included in the remotely exposed MCP ASGI application.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from chatgpt_bridge.provider_store import PROVIDERS, KeyVault, VaultConfigurationError

router = APIRouter()
COOKIE = "openmontage_settings_session"
MAX_AGE = 3600
_ATTEMPTS: dict[str, list[float]] = {}


def _local(request: Request) -> bool:
    # Only allow direct local connections. Proxies and X-Forwarded-For ignored.
    host = (request.client.host if request.client else "")
    return host in ("127.0.0.1", "::1", "testclient") and request.url.hostname in ("localhost", "127.0.0.1", "testserver", "::1")


def _secret() -> str:
    secret = os.environ.get("OPENMONTAGE_SETTINGS_SECRET", "")
    if len(secret) < 32:
        raise VaultConfigurationError("OPENMONTAGE_SETTINGS_SECRET must be 32+ random characters")
    return secret


def _password() -> str:
    value = os.environ.get("OPENMONTAGE_SETTINGS_PASSWORD", "")
    if len(value) < 12:
        raise VaultConfigurationError("Set OPENMONTAGE_SETTINGS_PASSWORD to a strong 12+ character password")
    return value


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="openmontage-settings-v1")


def _session(request: Request) -> str | None:
    value = request.cookies.get(COOKIE)
    if not value:
        return None
    try:
        payload = _signer().loads(value, max_age=MAX_AGE)
        if payload.get("v") == 1:
            return value
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        pass
    return None


def _csrf(session: str) -> str:
    return hmac.new(_secret().encode(), session.encode(), hashlib.sha256).hexdigest()


def _page(title: str, content: str, status: int = 200) -> HTMLResponse:
    style = """
    body{font:15px system-ui;background:#0b0e14;color:#f4f5fa;max-width:870px;margin:3rem auto;padding:1rem}
    a{color:#a7baff}section{background:#171c27;padding:1.4rem;border:1px solid #343d52;border-radius:16px;margin:1rem 0}
    input,select{box-sizing:border-box;max-width:100%;background:#0f1520;color:#fff;padding:.8rem;border:1px solid #526078;border-radius:8px}
    input{width:100%}label{display:block;margin:.8rem 0}button{background:#8fa6ff;color:#101625;border:0;border-radius:8px;padding:.75rem 1rem;cursor:pointer;font-weight:700}
    .row{display:flex;align-items:center;gap:1rem;justify-content:space-between;flex-wrap:wrap}
    .muted{color:#b8c0ce}.tag{background:#27334b;padding:.3rem .6rem;border-radius:7px;font-size:.8rem}
    .danger{background:#e9a4ab}.message{padding:1rem;background:#202e47;border-radius:8px}small{color:#aeb6c2}
    """
    return HTMLResponse("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                        + "<title>" + html.escape(title) + "</title><style>" + style + "</style></head><body><header class='row'>"
                        + "<div><a href='/'>← Backlot</a><h1>" + html.escape(title) + "</h1></div>"
                        + "<div class='tag'>Private local settings</div></header>" + content + "</body></html>",
                        status_code=status, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                                                     "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"})


async def _form(request: Request) -> dict[str, str]:
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
        raise ValueError("Unsupported form")
    if int(request.headers.get("content-length", "0")) > 4096:
        raise ValueError("Form too large")
    raw = await request.body()
    if len(raw) > 4096:
        raise ValueError("Form too large")
    values = parse_qs(raw.decode("utf-8"), strict_parsing=True, max_num_fields=12)
    return {key: value[-1] for key, value in values.items()}


def _logged_in(request: Request) -> str | None:
    return _session(request) if _local(request) else None


def _authorized_form(request: Request, data: dict[str, str]) -> bool:
    session = _logged_in(request)
    return bool(session and hmac.compare_digest(data.get("csrf", ""), _csrf(session)))


def _redirect(message: str = ""):
    url = "/settings/api" + ("?message=" + message if message else "")
    return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store"})


@router.get("/settings/api")
async def api_settings(request: Request):
    if not _local(request):
        return _page("Access denied", "<p>Settings are accessible only directly on this laptop.</p>", 403)
    try:
        _password()
        session = _session(request)
        if not session:
            return _page("API settings login", "<section><form method='post' action='/settings/api/login'>"
                         "<label>Local admin password<input name='password' type='password' autocomplete='current-password' required></label>"
                         "<button type='submit'>Unlock API settings</button></form></section>")
        vault = KeyVault()
        csrf = _csrf(session)
    except VaultConfigurationError as exc:
        return _page("Setup required", "<section><p>Configure the vault encryption key, session secret and password in your local environment before using API settings.</p>"
                     "<p>See <code>chatgpt_bridge/README.md</code>.</p></section>", 503)
    message = request.query_params.get("message", "")[:70]
    notes = "<p class='message'>" + html.escape(message) + "</p>" if message else ""
    choices = "".join(f"<option value='{html.escape(provider)}'>{html.escape(info['name'])}</option>" for provider, info in PROVIDERS.items())
    items = []
    for entry in vault.list():
        eid = html.escape(entry["id"])
        items.append("<section class='row'><div><b>" + html.escape(entry["label"]) + "</b> <span class='tag'>"
                     + html.escape(PROVIDERS[entry["provider"]]["name"]) + "</span><p class='muted'>"
                     + html.escape(entry["model"]) + " · Key stored encrypted · Added " + html.escape(entry["created_at"])
                     + "</p></div><form method='post' action='/settings/api/delete'><input type='hidden' name='csrf' value='" + csrf
                     + "'><input type='hidden' name='id' value='" + eid + "'><button class='danger'>Remove</button></form></section>")
    body = notes + "<section><h2>Connect an API key</h2><p class='muted'>Multiple keys per provider supported. Only enter a provider API key, not a domain or ChatGPT password.</p>"
    body += "<form method='post' action='/settings/api/add'><input type='hidden' name='csrf' value='" + csrf + "'>"
    body += "<label>Provider<select name='provider'>" + choices + "</select></label>"
    body += "<label>Label<input name='label' required maxlength='64' placeholder='Personal Gemini'></label>"
    body += "<label>Model ID<input name='model' required maxlength='128' placeholder='Enter a model offered by this provider'></label>"
    body += "<label>API key<input name='api_key' type='password' required autocomplete='off' minlength='8' maxlength='512'></label>"
    body += "<button type='submit'>Save encrypted key</button></form><small>Keys never appear in MCP tool responses or browser source after saving.</small></section>"
    body += "<h2>Connected accounts</h2>" + ("".join(items) if items else "<p class='muted'>No API keys saved yet.</p>")
    body += "<section><h3>Grok MCP</h3><p>Grok is available as an xAI provider. Its Responses API can also connect to this studio's remote MCP endpoint with OAuth-compatible access tokens. See the setup guide.</p></section>"
    body += "<form method='post' action='/settings/api/logout'><input type='hidden' name='csrf' value='" + csrf + "'><button>Lock settings</button></form>"
    return _page("API settings", body)


@router.post("/settings/api/login")
async def api_login(request: Request):
    if not _local(request):
        return _page("Access denied", "", 403)
    try:
        form = await _form(request)
        expected = _password()
        _secret()
    except (ValueError, VaultConfigurationError):
        return _page("Login failed", "<p>Invalid configuration or form.</p>", 400)
    peer = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = [t for t in _ATTEMPTS.get(peer, []) if now - t < 300]
    if len(attempts) >= 5:
        return _page("Too many attempts", "<p>Try later.</p>", 429)
    if not hmac.compare_digest(form.get("password", ""), expected):
        _ATTEMPTS[peer] = attempts + [now]
        return _page("Login failed", "<p>Invalid password.</p>", 401)
    _ATTEMPTS.pop(peer, None)
    ticket = _signer().dumps({"v": 1, "nonce": secrets.token_hex(12)})
    response = _redirect()
    response.set_cookie(COOKIE, ticket, httponly=True, samesite="strict", secure=False, max_age=MAX_AGE, path="/settings/api")
    return response


@router.post("/settings/api/add")
async def api_add(request: Request):
    if not _logged_in(request):
        return _page("Unauthorized", "", 401)
    try:
        form = await _form(request)
        if not _authorized_form(request, form):
            return _page("Forbidden", "<p>Invalid CSRF token.</p>", 403)
        KeyVault().add(form.get("provider", ""), form.get("label", ""), form.get("model", ""), form.get("api_key", ""))
        return _redirect("API key saved")
    except (ValueError, VaultConfigurationError):
        return _page("Invalid input", "<p>Check provider, label, model and key. No key was saved.</p>", 400)


@router.post("/settings/api/delete")
async def api_delete(request: Request):
    if not _logged_in(request):
        return _page("Unauthorized", "", 401)
    try:
        form = await _form(request)
        if not _authorized_form(request, form):
            return _page("Forbidden", "", 403)
        KeyVault().delete(form.get("id", ""))
        return _redirect("Key removed")
    except (ValueError, VaultConfigurationError):
        return _page("Invalid input", "", 400)


@router.post("/settings/api/logout")
async def api_logout(request: Request):
    if not _logged_in(request):
        return _page("Unauthorized", "", 401)
    try:
        form = await _form(request)
        if not _authorized_form(request, form):
            return _page("Forbidden", "", 403)
    except ValueError:
        return _page("Invalid input", "", 400)
    response = _redirect("Signed out")
    response.delete_cookie(COOKIE, path="/settings/api")
    return response
