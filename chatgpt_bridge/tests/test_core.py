import json
import pytest
from chatgpt_bridge import core

def test_slugs_reject_traversal():
    for bad in ("/tmp", "../x", ".env", "X", "a/b"):
        with pytest.raises(ValueError):
            core.check_slug(bad)

def test_pipeline_exists():
    assert "documentary-montage" in core.pipelines()
    assert core.pipeline("documentary-montage")["name"] == "documentary-montage"

def test_guides_are_sandboxed():
    assert "Rule Zero" in core.instructions("AGENT_GUIDE.md")
    with pytest.raises(ValueError):
        core.instructions(".env")
    with pytest.raises(ValueError):
        core.instructions("chatgpt_bridge/core.py")

def test_artifact_schema_and_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "PROJECTS", tmp_path)
    (tmp_path / "sample" / "artifacts").mkdir(parents=True)
    valid = {"version": "1.0", "title": "Earth", "hook": "Why?", "key_points": ["Gravity"], "tone": "educational",
             "style": "motion", "target_platform": "youtube", "target_duration_seconds": 30}
    assert core.save_artifact("sample", "brief", valid)["saved"]
    assert core.read_artifact("sample", "brief")["title"] == "Earth"
    with pytest.raises(FileExistsError):
        core.save_artifact("sample", "brief", valid)
    with pytest.raises(Exception):
        core.save_artifact("sample", "brief", {"invalid": 42}, overwrite=True)

def test_render_off_by_default(monkeypatch):
    monkeypatch.delenv("OPENMONTAGE_MCP_ALLOW_RENDER", raising=False)
    with pytest.raises(PermissionError):
        core.render("sample")

def test_project_listing_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "PROJECTS", tmp_path)
    folder = tmp_path / "sample"
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps({"title": "Demo", "pipeline_type": "animated-explainer"}))
    (folder / "renders").mkdir()
    (folder / "renders" / "preview.mp4").write_bytes(b"test")
    assert core.list_projects()[0]["title"] == "Demo"
    assert core.status("sample")["renders"][0]["file"] == "preview.mp4"
