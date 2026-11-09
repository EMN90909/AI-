"""OpenMontage MCP for ChatGPT/Grok via an authenticated HTTPS hostname.

The actual renderer stays on the Spectre. Cloudflare Tunnel can forward a
public HTTPS hostname to this loopback-only service, without opening ports.
OAuth JWT validation is mandatory whenever a public hostname is configured.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import ToolAnnotations

from chatgpt_bridge import core
from chatgpt_bridge.remote_auth import RemoteAuthConfig, auth_kwargs, security_settings
from chatgpt_bridge.provider_store import KeyVault, PROVIDERS, call_provider

remote = RemoteAuthConfig.from_env()
mcp = MCPServer("OpenMontage Video Studio", **auth_kwargs(remote))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
MODIFY = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
pool = ThreadPoolExecutor(max_workers=1)
jobs: dict = {}
lock = Lock()


def _require_write():
    if remote is not None:
        token = get_access_token()
        if token is None or "video:write" not in token.scopes:
            raise PermissionError("The OAuth token requires the video:write scope")


@mcp.tool(annotations=READ)
def list_video_pipelines() -> list[str]:
    """List the official production pipelines available locally."""
    return core.pipelines()


@mcp.tool(annotations=READ)
def get_video_pipeline(name: str) -> dict:
    """Read the selected pipeline manifest and its stage gates."""
    return core.pipeline(name)


@mcp.tool(annotations=READ)
def read_production_guide(path: str) -> str:
    """Read the OpenMontage production skills and pipeline instructions."""
    return core.instructions(path)


@mcp.tool(annotations=READ)
def check_providers() -> dict:
    """Inspect locally configured footage, voice and video providers (no keys)."""
    return core.capabilities()


@mcp.tool(annotations=READ)
def list_video_projects() -> list[dict]:
    """List locally stored OpenMontage projects."""
    return core.list_projects()


@mcp.tool(annotations=READ)
def get_video_status(project: str) -> dict:
    """Read a project's checkpoints and completed video filenames."""
    return core.status(project)


@mcp.tool(annotations=READ)
def read_video_artifact(project: str, artifact: str) -> dict:
    """Read a canonical JSON artifact such as script or scene_plan."""
    return core.read_artifact(project, artifact)


@mcp.tool(annotations=READ)
def list_ai_provider_connections() -> list[dict]:
    """List AI provider connections and model IDs, without ever returning API keys."""
    try:
        return KeyVault().list()
    except Exception:
        return []  # Unconfigured local vault is not a reason to expose secrets.


@mcp.tool(annotations=WRITE)
def create_video_project(project: str, title: str, pipeline: str = "animated-explainer") -> dict:
    """Initialize a new project and standard workspace. Never overwrite one."""
    _require_write()
    return core.create_project(project, title, pipeline)


@mcp.tool(annotations=MODIFY)
def save_video_artifact(project: str, artifact: str, data: dict, overwrite: bool = False) -> dict:
    """Schema-validate and save an artifact; overwrites require human approval."""
    _require_write()
    return core.save_artifact(project, artifact, data, overwrite)


@mcp.tool(annotations=MODIFY)
def draft_video_narration_with_api(key_id: str, topic: str, confirmation: str) -> dict:
    """Optional billable drafting using a saved provider key. Requires operator opt-in and exact 'PAY key-id' approval. Never auto-publish."""
    _require_write()
    if os.environ.get("OPENMONTAGE_MCP_ALLOW_PAID_APIS") != "1":
        raise PermissionError("Paid AI provider calls disabled by operator")
    if confirmation != "PAY " + key_id:
        raise ValueError("Requires explicit confirmation PAY <key_id>")
    entry = KeyVault().resolve(key_id)
    if not (3 <= len(topic) <= 300):
        raise ValueError("Topic must be 3-300 characters")
    prompt = ("Draft an original, compelling but fact-checkable 60-second science mystery narration about: "
              + topic + ". State uncertainty where applicable. Do not invent citations. The draft needs separate factual review.")
    result = call_provider(key_id, prompt, max_tokens=750)
    return {"provider": PROVIDERS[entry.provider]["name"], "model": entry.model,
            "draft": result, "verified": False, "may_have_incurred_api_cost": True}


@mcp.tool(annotations=MODIFY)
def start_local_render(project: str, confirmation: str) -> dict:
    """Render prepared artifacts on the laptop. Needs operator opt-in and exact 'RENDER project' approval; no paid providers or publishing."""
    _require_write()
    if confirmation != "RENDER " + core.check_slug(project):
        raise ValueError("Confirmation must exactly match RENDER project")
    if os.environ.get("OPENMONTAGE_MCP_ALLOW_RENDER") != "1":
        raise PermissionError("Local rendering not enabled by operator")
    core.read_artifact(project, "edit_decisions")
    core.read_artifact(project, "asset_manifest")
    with lock:
        if any(j["project"] == project and not j["future"].done() for j in jobs.values()):
            raise RuntimeError("Render already running")
        key = uuid4().hex
        jobs[key] = {"project": project, "future": pool.submit(core.render, project)}
    return {"job": key, "status": "submitted", "note": "Runs on the connected laptop; check get_local_render_status."}


@mcp.tool(annotations=READ)
def get_local_render_status(job: str) -> dict:
    """Check the status of a local render job without exposing secrets."""
    with lock:
        item = jobs.get(job)
    if item is None:
        return {"status": "unknown", "note": "Jobs reset on server restart"}
    future = item["future"]
    if not future.done():
        return {"status": "rendering" if future.running() else "queued"}
    try:
        return {"status": "completed", "result": future.result()}
    except Exception:
        return {"status": "failed", "error": "Render failed locally; inspect laptop logs"}


if __name__ == "__main__":
    # Tunnel the MCP port to a public *domain*. Bind only to loopback so that
    # untrusted devices on the LAN cannot bypass HTTPS termination.
    mcp.run(transport="streamable-http", host="127.0.0.1",
            port=int(os.environ.get("OPENMONTAGE_MCP_PORT", "8765")),
            stateless_http=True, json_response=True, transport_security=security_settings(remote))
