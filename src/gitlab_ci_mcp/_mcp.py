"""Shared FastMCP instance, lifespan, and per-project manager cache.

Every tool module imports ``mcp`` from here to attach decorators to the
same server. Kept separate from ``server.py`` so the tool packages don't
import from a module that also defines the entry point.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
import warnings
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any

import urllib3
import urllib3.exceptions
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from gitlab_ci_mcp.ci_manager import GitLabCIManager

# Only silence urllib3's InsecureRequestWarning (raised when
# GITLAB_SSL_VERIFY=false against self-signed corp certs). Every other
# warning stays audible so deprecations/misuse surface.
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 1800
_CACHE_MAX_ENTRIES = 128
_cache_hmac_key = secrets.token_bytes(32)
_managers_lock = threading.RLock()
# Static FastMCP resources cannot take Context without becoming templates. The HTTP
# boundary scopes their PAT with this task-local value instead.
_http_request_token: ContextVar[str | None] = ContextVar("gitlab_ci_mcp_http_token", default=None)


@dataclass
class _ManagerCacheEntry:
    manager: GitLabCIManager
    last_used: float


_managers: OrderedDict[tuple[str, str, str], _ManagerCacheEntry] = OrderedDict()


def _close_manager(manager: GitLabCIManager) -> None:
    try:
        manager.gl.session.close()
    except Exception:
        logger.debug("gitlab_ci_mcp: failed to close an evicted GitLab session")


@asynccontextmanager
async def app_lifespan(_app: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Server lifespan: managers are lazy-loaded per project; close their
    python-gitlab HTTP sessions on shutdown to avoid leaked sockets."""
    logger.debug("gitlab_ci_mcp: startup — managers lazy-loaded per project")
    try:
        yield {"managers": _managers}
    finally:
        with _managers_lock:
            for entry in _managers.values():
                _close_manager(entry.manager)
            _managers.clear()
        logger.debug("gitlab_ci_mcp: shutdown — all python-gitlab sessions closed")


mcp = FastMCP("gitlab_ci_mcp", lifespan=app_lifespan, stateless_http=True)


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


def _request_gitlab_token(ctx: Context | None) -> str:
    """Get the GitLab credential for this HTTP call or stdio process."""
    request = ctx.request_context.request if ctx is not None else None
    headers = getattr(request, "headers", None)
    request_token = headers.get("x-gitlab-token") if headers is not None else None
    scoped_token = request_token or _http_request_token.get()
    http_mode = (
        os.environ.get("MCP_TRANSPORT", "stdio").strip().lower() == "streamable-http"
        or scoped_token is not None
    )
    if http_mode:
        if not isinstance(scoped_token, str) or not scoped_token.strip():
            raise ValueError("X-GitLab-Token header is required for remote GitLab requests")
        return scoped_token.strip()

    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        raise ValueError("GitLab token is required (set GITLAB_TOKEN for stdio mode)")
    return token


def _prune_manager_cache(now: float) -> None:
    expired = [key for key, entry in _managers.items() if now - entry.last_used >= _CACHE_TTL_SECONDS]
    for key in expired:
        entry = _managers.pop(key)
        _close_manager(entry.manager)


def get_ci(project_path: str | None, *, ctx: Context | None = None) -> GitLabCIManager:
    """Return a cached ``GitLabCIManager`` for the given project path.

    ``None`` is rejected unless the explicit compatibility flag is enabled.
    Managers are cached per GitLab URL, project, and process-keyed PAT
    fingerprint. Raw PAT values are never cache keys.
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
    token = _request_gitlab_token(ctx)
    gitlab_url = (os.environ.get("GITLAB_URL") or "").rstrip("/")
    token_fingerprint = hmac.new(_cache_hmac_key, token.encode(), hashlib.sha256).hexdigest()
    key = (gitlab_url, project_path, token_fingerprint)
    now = time.monotonic()
    with _managers_lock:
        _prune_manager_cache(now)
        entry = _managers.get(key)
        if entry is not None:
            entry.last_used = now
            _managers.move_to_end(key)
            return entry.manager

        manager = GitLabCIManager(project_path=project_path, token=token)
        _managers[key] = _ManagerCacheEntry(manager=manager, last_used=now)
        while len(_managers) > _CACHE_MAX_ENTRIES:
            _old_key, old_entry = _managers.popitem(last=False)
            _close_manager(old_entry.manager)
        return manager


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
