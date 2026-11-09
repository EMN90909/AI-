# OpenMontage: remote ChatGPT + Grok MCP and API settings

This is **not a fork** of OpenMontage, and **not a hosted replacement** for the
video engine. Video work runs on your computer. The MCP server is a protected
remote tool endpoint that a compatible AI client can reach over HTTPS.

## 1. Local installation and verification

From the repo root, Python 3.11+, FFmpeg/ffprobe and Node are required for the
underlying OpenMontage pipelines. Follow the upstream README/Makefile to install
Remotion and other optional producers.

```bash
python -m pip install -r requirements.txt -r chatgpt_bridge/requirements.txt
python -m pip install pytest
python -m pytest chatgpt_bridge/tests -q
```

## 2. API settings, inside Backlot

The **API** link in Backlot's Library opens `/settings/api` on the **local,
private Backlot dashboard**. Settings deliberately do not share the remotely
exposed MCP port. You can save multiple entries for OpenAI, Google Gemini,
DeepSeek, OpenRouter, Grok/xAI, Groq Cloud, Mistral and Together AI.

Generate a Fernet encryption key and a random session secret locally:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Set these as **local machine environment variables**, never commit them:

```text
OPENMONTAGE_VAULT_KEY=<Fernet key from above>
OPENMONTAGE_SETTINGS_SECRET=<random session secret 32+ chars>
OPENMONTAGE_SETTINGS_PASSWORD=<your strong local-only password 12+ chars>
```

Start Backlot with `python -m backlot serve`, open the library on your computer
and click **API**. Secret values are encrypted in `.openmontage/provider_keys.sqlite3`,
excluded from Git, and never returned by MCP list tools. The encryption key is
required to decrypt them: losing it means the encrypted keys cannot be recovered.
There is no field for an arbitrary base URL, because allowing arbitrary API
hosts would open a server-side request forgery and key-exfiltration path.

The saved keys are usable for optional short narration drafting through the MCP
`draft_video_narration_with_api` tool. This sends a **billable request** to the
selected provider's fixed HTTPS endpoint, with a bounded output token count.
Before it can run, set `OPENMONTAGE_MCP_ALLOW_PAID_APIS=1` **on your own laptop**
and explicitly approve `PAY <key_id>` when invoking the tool. It will not spend
money, render, or publish automatically.

For provider-specific OpenMontage plugins that require environment variables,
continue to configure those credentials separately in local `.env` / your OS
secret manager. The encrypted vault is deliberately not sprayed into the global
process environment, which would expose keys to other tools and plugins.

## 3. HTTPS domain for ChatGPT/Grok remote MCP

**A registered hostname and OAuth provider are prerequisites.** This repository
cannot buy, choose or configure a domain automatically. Use an HTTPS hostname
you control, for example `https://mcp.YOUR-DOMAIN.example/mcp`.

Run the MCP bridge on the laptop, but do **not** expose its local socket directly:

```bash
python -m chatgpt_bridge.server
```

The service listens only on the machine's loopback interface by design, and
should be published through a **named Cloudflare Tunnel** with a stable HTTPS
hostname. In the Cloudflare dashboard, create a named Tunnel and add a published
hostname pointing to `http://127.0.0.1:8765`. The *public* URL that ChatGPT and
Grok use is your `https://.../mcp`, **not** localhost. The laptop and cloudflared
must remain running for jobs to work. Do not use an unauthenticated quick tunnel.

You MUST configure an external OAuth/OIDC identity provider (such as Auth0 or
Keycloak) to issue RS256/ES256 JWT access tokens containing an `aud`, `iss`, `sub`,
`iat`, `exp` and `scope` or `permissions`. Register a single-user application
and resource scope(s) `video:read` and `video:write` with the provider.

```text
OPENMONTAGE_PUBLIC_MCP_URL=https://mcp.YOUR-DOMAIN.example/mcp
OPENMONTAGE_OAUTH_ISSUER=https://YOUR-OAUTH-ISSUER.example/
OPENMONTAGE_OAUTH_JWKS_URL=https://YOUR-OAUTH-ISSUER.example/.well-known/jwks.json
OPENMONTAGE_OAUTH_AUDIENCE=<your OAuth API audience identifier>
OPENMONTAGE_ALLOWED_SUBJECT=<your exact OAuth subject ID>
```

All five settings are mandatory in domain mode; incomplete configuration fails
closed. The bridge checks JWT signature, algorithm, issuer, audience, expiry,
subject and scopes. **Do not share the vault or settings environment variables
with ChatGPT.** The MCP server supplies the protected-resource discovery metadata
needed by OAuth-capable clients.

In ChatGPT on the web: Plugins → + → Add custom MCP server → enter your HTTPS
`/mcp` URL and configure OAuth. This only works if your ChatGPT account/workspace
currently has the appropriate custom MCP permission. As of Nov 2026, full
write-capable custom MCP remains restricted to eligible workspace plans; Plus
cannot be assumed to have it. A public URL alone does not override product
permissions. No connection is established until **you** install the plugin.

## 4. Grok MCP client

Grok is included as an xAI API key provider. Separately, the **xAI API Responses
endpoint** can access this MCP server by specifying `type: mcp`, `server_url`,
`server_label`, `allowed_tools` and an OAuth bearer token. This is supported by
xAI's developer APIs and should not be confused with configuring the consumer
Grok website. A read-only example is provided:

```bash
# Set XAI_API_KEY, OPENMONTAGE_PUBLIC_MCP_URL and a short-lived
# OPENMONTAGE_GROK_OAUTH_ACCESS_TOKEN in your local environment.
python -m chatgpt_bridge.grok_mcp_demo
```

The Grok example **only exposes read-only tools**. API usage may incur xAI
charges. It does not use or expose the saved vault keys. Do not connect the
Grok API to write/render tools without independently evaluating xAI's approval
semantics and proper OAuth bearer tokens.

## 5. Local rendering

Local rendering is still disabled by default. Configure
`OPENMONTAGE_MCP_ALLOW_RENDER=1` and provide exact confirmation
`RENDER <project_id>` before any render. Rendering requires valid local
`edit_decisions` and `asset_manifest` artifacts. OpenMontage's full creative
workflow remains instruction-driven, with per-stage research, review and
human approval. This bridge does not autonomously create every asset or upload
videos.

See `AGENT_GUIDE.md`, `PROJECT_CONTEXT.md` and `pipeline_defs/` for the
underlying production workflow. Upstream license: AGPL-3.0.
