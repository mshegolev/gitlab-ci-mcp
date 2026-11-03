"""Explicit, bounded package update check (never performed implicitly)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

import urllib3

from gitlab_ci_mcp import output
from gitlab_ci_mcp._mcp import mcp
from gitlab_ci_mcp.models import UpdateCheckOutput

_TTL = 300.0
_MAX_BYTES = 512 * 1024
_cache: tuple[float, UpdateCheckOutput] | None = None
_lock = threading.Lock()


def _enabled() -> bool:
    return os.environ.get("MCP_GITLAB_UPDATE_CHECK_ENABLED", "").lower() in {"1", "true", "yes"}


def _version(value: str) -> tuple[int, ...] | None:
    """Parse the supported numeric PEP 440 subset without a runtime dependency."""
    match = re.fullmatch(r"(?P<release>\d+(?:\.\d+)*)(?:(?P<pre>a|b|rc)(?P<pre_num>\d+))?", value)
    if not match:
        return None
    release = [int(part) for part in match.group("release").split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    pre = match.group("pre")
    if pre:
        return tuple(release) + ({"a": -3, "b": -2, "rc": -1}[pre], int(match.group("pre_num")))
    return tuple(release) + (0, 0)


def _read_bounded(response: Any) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while size <= _MAX_BYTES:
        chunk = response.read(min(64 * 1024, _MAX_BYTES + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def _check() -> UpdateCheckOutput:
    global _cache
    now = time.monotonic()
    with _lock:
        if _cache and now - _cache[0] < _TTL:
            return {**_cache[1], "cached": True}
    from gitlab_ci_mcp import __version__

    http = urllib3.PoolManager(timeout=urllib3.Timeout(connect=2.0, read=3.0))
    try:
        response = http.request("GET", "https://pypi.org/pypi/gitlab-ci-mcp/json", preload_content=False)
        try:
            body = _read_bounded(response)
        finally:
            response.release_conn()
        if len(body) > _MAX_BYTES:
            return {
                "status": "unavailable", "installed_version": __version__,
                "detail": "PyPI response exceeded 512 KiB", "cached": False,
            }
        if response.status >= 400:
            return {
                "status": "unavailable", "installed_version": __version__,
                "detail": f"PyPI returned HTTP {response.status}", "cached": False,
            }
        payload: Any = json.loads(body)
        latest = payload["info"]["version"]
        current_v, latest_v = _version(__version__), _version(latest)
        if current_v is None or latest_v is None:
            return {
                "status": "comparison_unavailable", "installed_version": __version__,
                "latest_version": latest, "detail": "unsupported version format", "cached": False,
            }
        result: UpdateCheckOutput = {
            "status": "update_available" if latest_v > current_v else "current",
            "installed_version": __version__, "latest_version": latest,
            "update_available": latest_v > current_v,
            "release_url": "https://pypi.org/project/gitlab-ci-mcp/",
            "install_command": "python -m pip install --upgrade gitlab-ci-mcp",
            "cached": False,
        }
    except Exception as exc:
        result = {"status": "unavailable", "installed_version": __version__, "detail": str(exc), "cached": False}
    with _lock:
        _cache = (now, result)
    return result


@mcp.tool(
    name="gitlab_ci_mcp_check_updates",
    annotations={
        "title": "Check gitlab-ci-mcp Updates", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_ci_mcp_check_updates() -> UpdateCheckOutput:
    """Check updates when enabled; defaults off and never installs or runs at startup."""
    if _enabled():
        result = _check()
    else:
        from gitlab_ci_mcp import __version__

        result = {
            "status": "disabled", "installed_version": __version__,
            "detail": "Set MCP_GITLAB_UPDATE_CHECK_ENABLED=true to enable the explicit PyPI check.",
            "cached": False,
        }
    return output.ok(result, f"gitlab-ci-mcp update status: **{result['status']}**")  # type: ignore[return-value]
