"""Helpers that produce the dual-channel tool result.

Every tool returns a ``CallToolResult`` carrying:

* ``content``         — a pre-rendered markdown block (compact, human-readable).
* ``structuredContent`` — the full typed payload, validated by FastMCP against
  the tool's output TypedDict and exposed to MCP clients that support
  structured data.

Keeping markdown as the text channel preserves the context-efficient
rendering tuned in v0.2+; adding ``structuredContent`` closes the last
MCP-spec alignment gap.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from gitlab_ci_mcp import errors


def ok(data: Mapping[str, Any], markdown: str) -> CallToolResult:
    """Wrap ``data`` + a markdown rendering into a non-error tool result."""
    return CallToolResult(
        content=[TextContent(type="text", text=markdown)],
        structuredContent=dict(data),
    )


def fail(exc: Exception, action: str) -> None:
    """Raise a ``ToolError`` carrying the actionable error message.

    FastMCP converts raised ``ToolError`` into an error result with
    ``isError=True``, so we don't need to synthesise a dummy structured
    payload just to satisfy the output schema.
    """
    raise ToolError(errors.handle(exc, action)) from exc
