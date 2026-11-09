"""Optional xAI Grok Responses API -> remote OpenMontage MCP test.

Runs only with explicit environment config; Grok calls are billable. Provides
only read-only MCP tools to Grok. This is not the consumer grok.com chat app.
"""
import os
from urllib.parse import urlsplit

import httpx

READ_ONLY_TOOLS = [
    "list_video_pipelines", "get_video_pipeline", "read_production_guide",
    "check_providers", "list_video_projects", "get_video_status", "read_video_artifact",
]


def build_request(prompt: str, endpoint: str, model: str = "grok-4.5", authorization: str | None = None):
    url = urlsplit(endpoint)
    if url.scheme != "https" or url.path != "/mcp" or not url.hostname:
        raise ValueError("Grok requires a public HTTPS MCP endpoint ending in /mcp")
    if not (1 <= len(prompt) <= 2000):
        raise ValueError("Prompt must be 1-2000 characters")
    connector = {"type": "mcp", "server_url": endpoint, "server_label": "openmontage",
                 "allowed_tools": READ_ONLY_TOOLS}
    if authorization:
        connector["authorization"] = authorization
    return {"model": model, "input": [{"role": "user", "content": prompt}], "tools": [connector]}


def main():
    key = os.environ.get("XAI_API_KEY")
    endpoint = os.environ.get("OPENMONTAGE_PUBLIC_MCP_URL")
    token = os.environ.get("OPENMONTAGE_GROK_OAUTH_ACCESS_TOKEN")
    if not key or not endpoint or not token:
        raise SystemExit("Set XAI_API_KEY, OPENMONTAGE_PUBLIC_MCP_URL and a time-limited OPENMONTAGE_GROK_OAUTH_ACCESS_TOKEN")
    data = build_request("List my available video pipelines.", endpoint, authorization=token)
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        response = client.post("https://api.x.ai/v1/responses", headers={"Authorization": "Bearer " + key}, json=data)
    if response.status_code != 200:
        raise SystemExit(f"xAI returned HTTP {response.status_code}; check configuration and model")
    result = response.json()
    # Output only the assistant's reply, not credentials or the full raw tool trace.
    for piece in result.get("output", []):
        if piece.get("type") == "message":
            for item in piece.get("content", []):
                if item.get("type") == "output_text":
                    print(item.get("text", "")[:3000])


if __name__ == "__main__":
    main()
