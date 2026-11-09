"""Private MCP Streamable HTTP adapter. Bind only to localhost and use a secure tunnel."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from chatgpt_bridge import core

mcp = MCPServer("OpenMontage Video Studio")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
MODIFY = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
pool = ThreadPoolExecutor(max_workers=1)
jobs = {}
lock = Lock()

@mcp.tool(annotations=READ)
def list_video_pipelines() -> list[str]:
    """List the official production pipelines available locally."""
    return core.pipelines()

@mcp.tool(annotations=READ)
def get_video_pipeline(name: str) -> dict:
    """Read the selected pipeline manifest and all of its stage gates."""
    return core.pipeline(name)

@mcp.tool(annotations=READ)
def read_production_guide(path: str) -> str:
    """Read a specific official guide or stage skill before producing content."""
    return core.instructions(path)

@mcp.tool(annotations=READ)
def check_providers() -> dict:
    """Inspect which free or configured providers actually work on this machine."""
    return core.capabilities()

@mcp.tool(annotations=READ)
def list_video_projects() -> list[dict]:
    """List locally stored OpenMontage projects."""
    return core.list_projects()

@mcp.tool(annotations=READ)
def get_video_status(project: str) -> dict:
    """Read a project's checkpoints and completed video file names."""
    return core.status(project)

@mcp.tool(annotations=READ)
def read_video_artifact(project: str, artifact: str) -> dict:
    """Read a canonical JSON artifact, such as script, brief or scene_plan."""
    return core.read_artifact(project, artifact)

@mcp.tool(annotations=WRITE)
def create_video_project(project: str, title: str, pipeline: str = "animated-explainer") -> dict:
    """Initialize a new project and its standard workspace."""
    return core.create_project(project, title, pipeline)

@mcp.tool(annotations=MODIFY)
def save_video_artifact(project: str, artifact: str, data: dict, overwrite: bool = False) -> dict:
    """Schema-validate and persist a canonical artifact. Overwrites need approval."""
    return core.save_artifact(project, artifact, data, overwrite)

@mcp.tool(annotations=MODIFY)
def start_local_render(project: str, confirmation: str) -> dict:
    """Render prepared artifacts locally. Requires explicit RENDER project confirmation and operator opt-in; no paid API or publishing."""
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
    return {"job": key, "status": "submitted", "note": "Runs on your laptop. Poll get_local_render_status."}

@mcp.tool(annotations=READ)
def get_local_render_status(job: str) -> dict:
    """Get the status of a local render job."""
    with lock:
        item = jobs.get(job)
    if item is None:
        return {"status": "unknown", "note": "Jobs reset when the server restarts"}
    future = item["future"]
    if not future.done():
        return {"status": "rendering" if future.running() else "queued"}
    try:
        return {"status": "completed", "result": future.result()}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)[:500]}

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1",
            port=int(os.environ.get("OPENMONTAGE_MCP_PORT", "8765")),
            stateless_http=True, json_response=True)
