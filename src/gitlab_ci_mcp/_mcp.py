"""Shared FastMCP instance, lifespan, and per-project manager cache.

Every tool module imports ``mcp`` from here to attach decorators to the
same server. Kept separate from ``server.py`` so the tool packages don't
import from a module that also defines the entry point.
"""

from __future__ import annotations

import logging
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


# ── Shared parameter annotation ─────────────────────────────────────────────

ProjectPath = Annotated[
    str | None,
    Field(
        default=None,
        description=(
            "GitLab project path (e.g. 'my-org/my-repo'). When omitted, the "
            "default from GITLAB_PROJECT_PATH env var is used."
        ),
    ),
]


# ── Utilities ───────────────────────────────────────────────────────────────


def get_ci(project_path: str | None) -> GitLabCIManager:
    """Return a cached ``GitLabCIManager`` for the given project path.

    ``None`` uses the default from env. Managers are cached per path so the
    python-gitlab HTTP session is reused across tool calls.
    """
    key = project_path or ""
    if key not in _managers:
        _managers[key] = GitLabCIManager(project_path=project_path or None)
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
