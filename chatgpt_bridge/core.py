"""Bounded access to an OpenMontage checkout. No arbitrary shell or paid calls."""
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
SLUG = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
ARTIFACT_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

def check_slug(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ValueError("Invalid project/pipeline slug")
    return value

def project_path(project):
    return PROJECTS / check_slug(project)

def pipelines():
    return sorted(p.stem for p in (ROOT / "pipeline_defs").glob("*.yaml"))

def pipeline(name):
    from lib.pipeline_loader import load_pipeline
    if check_slug(name) not in pipelines():
        raise ValueError("Unknown pipeline")
    return load_pipeline(name)

def instructions(path):
    if not isinstance(path, str) or len(path) > 200:
        raise ValueError("Invalid instructions path")
    full = (ROOT / path).resolve()
    roots = [ROOT / "skills", ROOT / "docs", ROOT / "pipeline_defs", ROOT / ".agents" / "skills"]
    specials = [ROOT / "AGENT_GUIDE.md", ROOT / "PROJECT_CONTEXT.md"]
    if full not in specials and not any(full.is_relative_to(r.resolve()) for r in roots):
        raise ValueError("Only production documentation may be read")
    if full.suffix not in (".md", ".yaml", ".yml") or not full.is_file():
        raise ValueError("Guide not found")
    if full.stat().st_size > 64000:
        raise ValueError("Guide exceeds size limit")
    return full.read_text(encoding="utf-8")

def capabilities():
    from tools.tool_registry import ToolRegistry
    return ToolRegistry().provider_menu_summary()

def create_project(project, title, kind="animated-explainer"):
    from lib.checkpoint import init_project
    path = project_path(project)
    if path.exists():
        raise FileExistsError("Project already exists")
    if check_slug(kind) not in pipelines():
        raise ValueError("Unsupported pipeline")
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= 160):
        raise ValueError("Title must be 1-160 characters")
    created = init_project(project, title=title.strip(), pipeline_type=kind)
    return {"project": project, "pipeline": kind, "directory": str(created)}

def list_projects():
    if not PROJECTS.is_dir():
        return []
    result = []
    for p in sorted(PROJECTS.iterdir()):
        if not p.is_dir() or p.is_symlink() or not SLUG.fullmatch(p.name):
            continue
        meta = p / "project.json"
        if meta.is_file():
            try:
                item = json.loads(meta.read_text(encoding="utf-8"))
                result.append({"id": p.name, "title": item.get("title"), "pipeline": item.get("pipeline_type")})
            except (OSError, ValueError):
                pass
    return result

def status(project):
    p = project_path(project)
    if not p.is_dir() or p.is_symlink():
        raise FileNotFoundError("Unknown project")
    stages = []
    for f in sorted(p.glob("checkpoint_*.json")):
        if f.is_symlink():
            continue
        try:
            item = json.loads(f.read_text(encoding="utf-8"))
            stages.append({"stage": item.get("stage", f.stem), "status": item.get("status")})
        except (OSError, ValueError):
            continue
    renders = [{"file": f.name, "bytes": f.stat().st_size} for f in sorted((p / "renders").glob("*.mp4")) if f.is_file() and not f.is_symlink()]
    return {"project": project, "stages": stages, "renders": renders}

def artifact_path(project, name):
    if not isinstance(name, str) or not ARTIFACT_NAME.fullmatch(name):
        raise ValueError("Invalid artifact name")
    schema = ROOT / "schemas" / "artifacts" / (name + ".schema.json")
    if not schema.is_file():
        raise ValueError("Only canonical schema-backed artifacts are supported")
    path = project_path(project) / "artifacts" / (name + ".json")
    if path.is_symlink():
        raise ValueError("Symlink artifacts are forbidden")
    return path, schema

def read_artifact(project, name):
    path, _ = artifact_path(project, name)
    if not path.is_file() or path.stat().st_size > 1048576:
        raise FileNotFoundError("Artifact not found or exceeds limit")
    return json.loads(path.read_text(encoding="utf-8"))

def save_artifact(project, name, data, overwrite=False):
    path, schema = artifact_path(project, name)
    if not project_path(project).is_dir():
        raise FileNotFoundError("Create a project first")
    if path.exists() and not overwrite:
        raise FileExistsError("Existing artifact requires explicit overwrite")
    if not isinstance(data, dict):
        raise ValueError("Artifact must be an object")
    import jsonschema
    jsonschema.validate(data, json.loads(schema.read_text(encoding="utf-8")))
    raw = json.dumps(data, indent=2, ensure_ascii=False)
    if len(raw.encode()) > 1048576:
        raise ValueError("Artifact too large")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".new-artifact-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return {"saved": True, "project": project, "artifact": name, "overwritten": bool(overwrite)}

def render(project):
    """Use only the local FFmpeg/Remotion composer on prepared project artifacts."""
    if os.environ.get("OPENMONTAGE_MCP_ALLOW_RENDER") != "1":
        raise PermissionError("Operator must enable local rendering")
    p = project_path(project)
    if not p.is_dir() or p.is_symlink():
        raise FileNotFoundError("Project not found")
    edit = read_artifact(project, "edit_decisions")
    assets = read_artifact(project, "asset_manifest")
    out = p / "renders" / "chatgpt-preview.mp4"
    out.parent.mkdir(exist_ok=True)
    from tools.video.video_compose import VideoCompose
    result = VideoCompose().execute({"operation": "render", "edit_decisions": edit, "asset_manifest": assets,
                                     "output_path": str(out), "project_dir": str(p), "fps": 24})
    if not result.success:
        raise RuntimeError(result.error or "Compose failed")
    return {"project": project, "output": str(out), "exists": out.is_file()}
