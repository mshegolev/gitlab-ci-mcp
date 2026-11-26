"""Tool modules. Importing this package registers every tool with the
shared FastMCP instance in :mod:`gitlab_ci_mcp._mcp`.
"""

from __future__ import annotations

import os
from importlib import import_module

# Group ownership follows these module boundaries. These identifiers are a
# stable configuration interface.
TOOL_GROUP_MODULES = {
    "pipelines": "pipelines",
    "schedules": "schedules",
    "branches_tags": "branches_tags",
    "merge_requests": "mrs",
    "repository": "repo",
    "package": "updates",
}


def _disabled_groups() -> set[str]:
    """Parse and validate the comma-separated disabled tool groups."""
    raw = os.environ.get("GITLAB_DISABLED_TOOL_GROUPS", "")
    groups = {token.strip() for token in raw.split(",") if token.strip()}
    unknown = groups - TOOL_GROUP_MODULES.keys()
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(
            "Unknown tool group ID(s) in GITLAB_DISABLED_TOOL_GROUPS: "
            f"{names}. Supported IDs: {', '.join(TOOL_GROUP_MODULES)}"
        )
    return groups


_DISABLED_GROUPS = _disabled_groups()

# Each module's top-level @mcp.tool decorators run at import time and register
# tools with the shared FastMCP instance. Do not import disabled modules: a
# module's decorators are the registration mechanism.
for _group, _module in TOOL_GROUP_MODULES.items():
    if _group not in _DISABLED_GROUPS:
        import_module(f"{__name__}.{_module}")
