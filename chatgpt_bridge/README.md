# ChatGPT MCP bridge for OpenMontage

This bridge exposes the agent-driven OpenMontage pipeline to ChatGPT via the
Streamable HTTP MCP protocol. It does not include an LLM or use OpenAI API
credits. The chat model provides planning; OpenMontage runs on your laptop.

Setup from the repository root (Python 3.11+):

    python -m pip install -r requirements.txt
    python -m pip install -r chatgpt_bridge/requirements.txt
    python -m pytest chatgpt_bridge/tests -q
    python -m chatgpt_bridge.server

Endpoint: http://127.0.0.1:8765/mcp

IMPORTANT: Never publish this unauthenticated localhost endpoint to the public
Internet or use an open reverse proxy. Connect from ChatGPT using OpenAI's
authenticated Secure MCP Tunnel if your plan/workspace permits it. Custom MCP
write access is not guaranteed on ChatGPT Plus. Connecting requires a separate
user action, and source code alone cannot establish the connection.

For local rendering, explicitly set OPENMONTAGE_MCP_ALLOW_RENDER=1 and approve
the exact 'RENDER project-id' phrase. This renders only existing approved
edit_decisions and asset_manifest artifacts; it does not autonomously run the
whole pipeline, spend money on APIs, publish, or execute arbitrary commands.

Read AGENT_GUIDE.md, PROJECT_CONTEXT.md and the selected pipeline stage skills.
OpenMontage enforces stage-by-stage review and approval. Avoid large renders
on thin or old laptops until a short sample works. No automatic uploading.
License: upstream AGPL-3.0.
