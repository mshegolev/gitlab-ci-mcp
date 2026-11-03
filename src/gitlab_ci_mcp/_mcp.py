"""Shared FastMCP instance, lifespan, and per-project manager cache.

Every tool module imports ``mcp`` from here to attach decorators to the
same server. Kept separate from ``server.py`` so the tool packages don't
import from a module that also defines the entry point.
"""

from __future__ import annotations

import logging
import os
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import urllib3
import urllib3.exceptions
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from gitlab_ci_mcp.ci_manager import GitLabCIManager

# Only silence urllib3's InsecureRequestWarning (raised when
# GITLAB_SSL_VERIFY=false against self-signed corp certs). Every other
# warning stays audible so deprecations/misuse surface.
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_managers: dict[str, GitLabCIManager] = {}


@asynccontextmanager
async def app_lifespan(_app: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Server lifespan: managers are lazy-loaded per project; close their
    python-gitlab HTTP sessions on shutdown to avoid leaked sockets."""
    logger.debug("gitlab_ci_mcp: startup — managers lazy-loaded per project")
    try:
        yield {"managers": _managers}
    finally:
        for m in _managers.values():
            try:
                m.gl.session.close()
            except Exception:
                pass
        _managers.clear()
        logger.debug("gitlab_ci_mcp: shutdown — all python-gitlab sessions closed")


mcp = FastMCP("gitlab_ci_mcp", lifespan=app_lifespan)


def configure_project_path_schema() -> None:
    """Make the MCP input schema match strict or legacy scope behavior."""
    allow_default = os.environ.get("GITLAB_ALLOW_DEFAULT_PROJECT", "").lower() in {"1", "true", "yes"}
    for tool in mcp._tool_manager.list_tools():
        schema = tool.parameters
        properties = schema.get("properties", {})
        project_schema = properties.get("project_path")
        if project_schema is None:
            continue
        required = schema.setdefault("required", [])
        if allow_default:
            if "project_path" in required:
                required.remove("project_path")
            project_schema.pop("type", None)
            project_schema["anyOf"] = [{"type": "string"}, {"type": "null"}]
            project_schema["default"] = None
        else:
            if "project_path" not in required:
                required.append("project_path")
            project_schema.pop("anyOf", None)
            project_schema.pop("default", None)
            project_schema["type"] = "string"
            project_schema["minLength"] = 1


# ── Shared parameter annotation ─────────────────────────────────────────────

ProjectPath = Annotated[
    str | None,
    Field(
        default=None,
        min_length=1,
        description=(
            "GitLab project path (e.g. 'my-org/my-repo'). Required by default. "
            "For legacy deployments only, set GITLAB_ALLOW_DEFAULT_PROJECT=true "
            "to use GITLAB_PROJECT_PATH when omitted."
        ),
    ),
]


# ── Utilities ───────────────────────────────────────────────────────────────


def get_ci(project_path: str | None) -> GitLabCIManager:
    """Return a cached ``GitLabCIManager`` for the given project path.

    ``None`` is rejected unless the explicit compatibility flag is enabled.
    Managers are cached per path so the python-gitlab HTTP session is reused
    across tool calls.
    """
    if project_path is not None and not project_path.strip():
        raise ValueError("project_path must not be empty")
    if project_path is None:
        allow_default = os.environ.get("GITLAB_ALLOW_DEFAULT_PROJECT", "").lower() in {"1", "true", "yes"}
        if not allow_default:
            raise ValueError(
                "project_path is required. Set GITLAB_ALLOW_DEFAULT_PROJECT=true only for legacy "
                "GITLAB_PROJECT_PATH fallback."
            )
        project_path = os.environ.get("GITLAB_PROJECT_PATH")
        if not project_path:
            raise ValueError("GITLAB_PROJECT_PATH is required when compatibility fallback is enabled")
    key = project_path
    if key not in _managers:
        _managers[key] = GitLabCIManager(project_path=project_path)
    return _managers[key]


def ts(dt_str: str | None) -> str | None:
    """Trim an ISO timestamp to second-precision, space-separated form."""
    if not dt_str:
        return None
    return dt_str[:19].replace("T", " ")


_SECRET_PATTERNS = ("TOKEN", "PASSWORD", "SECRET", "CREDENTIAL", "PRIVATE_KEY", "API_KEY")


def is_secret_key(key: str) -> bool:
    """Heuristic: CI-variable keys that look like they hold secrets.

    Matches substrings (case-insensitive) against a curated list so common
    names like ``*_TOKEN``, ``GITHUB_API_KEY``, ``AWS_SECRET_ACCESS_KEY``
    are caught without flagging unrelated names that merely contain the
    word ``KEY`` (``MONKEY_REPO`` stays visible).
    """
    k = key.upper()
    return any(p in k for p in _SECRET_PATTERNS)


def mask_variables(variables: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``variables`` with secret-looking values replaced by ``***``.

    Keeps the keys visible so the agent knows which variables exist.
    """
    return {k: ("***" if is_secret_key(k) else v) for k, v in variables.items()}
