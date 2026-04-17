"""Tool modules. Importing this package registers every tool with the
shared FastMCP instance in :mod:`gitlab_ci_mcp._mcp`.
"""

from __future__ import annotations

# noqa imports are intentional: each module's top-level @mcp.tool
# decorators run at import time and register tools with the shared
# FastMCP instance.
from gitlab_ci_mcp.tools import (  # noqa: F401
    branches_tags,
    mrs,
    pipelines,
    repo,
    schedules,
)
