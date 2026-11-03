"""FastMCP server exposing GitLab CI/CD as structured MCP tools.

Thin composition module — the FastMCP instance lives in
:mod:`gitlab_ci_mcp._mcp`, tool implementations are grouped by domain in
:mod:`gitlab_ci_mcp.tools`, and MCP resources in
:mod:`gitlab_ci_mcp.resources`. Importing those packages registers
everything with the shared server.

Design highlights:

* 24 tools, 2 resources, all with input validation (Pydantic ``Field``
  constraints), ``structured_output=True`` + a TypedDict return
  annotation, and tool annotations (``readOnlyHint`` /
  ``destructiveHint`` / ``idempotentHint`` / ``openWorldHint``).
* Every tool response carries *both* a compact markdown text block
  (``content``) and the full typed payload (``structuredContent``) so
  clients can render or process data as they prefer.
* Errors raised as ``ToolError`` carrying actionable messages produced
  by :mod:`gitlab_ci_mcp.errors` (401 / 403 / 404 / 429 / 5xx /
  ``ValueError`` all mapped to next-step hints).
* ``gitlab_pipeline_health`` and ``gitlab_get_job_log`` are async and
  emit ``ctx.info`` / ``ctx.report_progress`` events.
* Lifespan closes cached ``python-gitlab`` HTTP sessions on shutdown.
"""

from __future__ import annotations

import os

# Importing these modules attaches tools / resources to the shared mcp
# instance; the re-exports below are for external consumers (tests,
# notebooks, other packages) that want a single entry point.
from gitlab_ci_mcp import resources as _resources  # noqa: F401
from gitlab_ci_mcp import tools as _tools  # noqa: F401
from gitlab_ci_mcp._mcp import app_lifespan, configure_project_path_schema, mcp

configure_project_path_schema()


def main() -> None:
    """Run the stdio server or an opt-in authenticated Streamable HTTP app.

    **Threading model**: FastMCP automatically runs synchronous tools in a
    worker thread (``anyio.to_thread.run_sync``), so they do not block the
    asyncio event loop. Tools that benefit from MCP ``Context`` (progress /
    logging) are written as ``async def`` and wrap ``python-gitlab`` calls
    with ``asyncio.to_thread`` explicitly.
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport == "streamable-http":
        import uvicorn

        from gitlab_ci_mcp.http_auth import create_http_app

        host = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
        port = int(os.environ.get("MCP_HTTP_PORT", "8000"))
        uvicorn.run(create_http_app(), host=host, port=port)
        return
    raise ValueError("MCP_TRANSPORT must be 'stdio' or 'streamable-http'")


__all__ = ["mcp", "app_lifespan", "main"]


if __name__ == "__main__":
    main()
