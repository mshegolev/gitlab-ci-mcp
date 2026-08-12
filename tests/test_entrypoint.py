"""Entry-point smoke tests — the console script must actually start.

The defect class these guard against: the package builds, publishes and
``pip install``s fine, but the ``gitlab-ci-mcp`` console script dies on the
first import (a renamed upstream module, a dropped transitive dependency, a
typo in a tool module that only the facade imports). Unit tests that poke
individual helpers never notice, because they never walk the path the console
script walks:

    console_scripts metadata → gitlab_ci_mcp.server:main → mcp.run() → stdio

That is exactly what 0.5.1 was one ``mcp`` release away from: ``mcp`` 2.0
removed ``mcp.server.fastmcp``, which every tool module imports.

Everything here is offline: no GitLab, no token, no network. Building the
FastMCP server and listing its tools is pure in-process schema work.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import entry_points

import pytest

CONSOLE_SCRIPT = "gitlab-ci-mcp"
DIST = "gitlab-ci-mcp"

# Names the README, server.json and downstream agents rely on. If one of these
# disappears the server still "starts", but clients silently lose a capability.
CORE_TOOLS = {
    "gitlab_list_pipelines",
    "gitlab_get_pipeline",
    "gitlab_get_job_log",
    "gitlab_pipeline_health",
    "gitlab_list_merge_requests",
    "gitlab_get_file",
    "gitlab_project_info",
}
EXPECTED_TOOL_COUNT = 23
EXPECTED_RESOURCES = {"gitlab://project/info", "gitlab://project/ci-config"}


def _console_script_entry_point():
    """Return the ``gitlab-ci-mcp`` console_scripts entry point from installed metadata."""
    eps = [ep for ep in entry_points(group="console_scripts") if ep.name == CONSOLE_SCRIPT]
    assert eps, (
        f"console script {CONSOLE_SCRIPT!r} is not registered in installed metadata — "
        f"either the package is not installed (run `pip install -e '.[dev]'`) or "
        f"[project.scripts] in pyproject.toml no longer declares it"
    )
    return eps[0]


def test_console_script_is_declared_and_resolves() -> None:
    """``[project.scripts]`` points at a real, callable target.

    Loading the entry point imports ``gitlab_ci_mcp.server``, which imports the
    whole tool surface. A broken import anywhere below the facade fails here.
    """
    ep = _console_script_entry_point()
    assert ep.value == "gitlab_ci_mcp.server:main", f"unexpected entry-point target: {ep.value}"

    main = ep.load()  # <- imports the facade; this is where a dead package dies
    assert callable(main), f"entry point {ep.value} resolved to a non-callable: {main!r}"

    from gitlab_ci_mcp.server import main as facade_main

    assert main is facade_main, "console script resolves to a different object than gitlab_ci_mcp.server.main"


def test_console_script_starts_and_exits_cleanly_on_eof() -> None:
    """Run the real entry point in a fresh interpreter and let stdio hit EOF.

    This is the closest offline approximation of "an MCP client launched the
    server": metadata lookup, import, ``main()``, ``mcp.run()`` over stdio, then
    a clean shutdown when the transport closes. An import-time explosion shows
    up as a non-zero exit and a traceback on stderr.
    """
    program = (
        "from importlib.metadata import entry_points\n"
        f"ep = next(e for e in entry_points(group='console_scripts') if e.name == {CONSOLE_SCRIPT!r})\n"
        "ep.load()()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", program],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"console script exited with {proc.returncode} instead of shutting down cleanly on EOF.\n"
        f"--- stderr ---\n{proc.stderr}\n--- stdout ---\n{proc.stdout}"
    )
    assert "Traceback" not in proc.stderr, f"console script printed a traceback:\n{proc.stderr}"


def test_server_builds_and_advertises_tools_over_the_protocol() -> None:
    """``mcp.list_tools()`` is what a client calls first — it must not raise.

    Reading ``_tool_manager._tools`` only proves the decorators ran. Calling
    ``list_tools()`` additionally forces every tool's JSON Schema to be built
    from its Pydantic annotations, so a malformed ``Annotated[...]`` surfaces
    here rather than at the client's first handshake.
    """
    import asyncio

    from gitlab_ci_mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}

    assert len(tools) == EXPECTED_TOOL_COUNT, f"expected {EXPECTED_TOOL_COUNT} tools, got {len(tools)}: {sorted(names)}"
    missing = CORE_TOOLS - names
    assert not missing, f"core tools missing from the advertised surface: {sorted(missing)}"

    for t in tools:
        assert t.description, f"tool {t.name} has no description — agents pick tools by description"
        assert t.inputSchema, f"tool {t.name} has no input schema"


def test_server_advertises_resources_over_the_protocol() -> None:
    """Resources go through a separate registry; a broken one must not be silent."""
    import asyncio

    from gitlab_ci_mcp.server import mcp

    resources = asyncio.run(mcp.list_resources())
    uris = {str(r.uri) for r in resources}
    assert EXPECTED_RESOURCES <= uris, f"missing resources: {sorted(EXPECTED_RESOURCES - uris)}"


@pytest.mark.parametrize(
    "var",
    ["GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT_PATH", "GITLAB_SSL_VERIFY"],
)
def test_server_builds_without_any_credentials(monkeypatch: pytest.MonkeyPatch, var: str) -> None:
    """Startup must not require config — a client launches the server before it has one.

    Credentials are resolved lazily per tool call (``get_ci``), so an unset env
    var may not break importing or listing tools. If someone moves that lookup
    to import time, an MCP client gets a server that refuses to start instead of
    a tool that returns an actionable error.
    """
    monkeypatch.delenv(var, raising=False)

    import asyncio
    import importlib

    import gitlab_ci_mcp.server as server_mod

    importlib.reload(server_mod)
    assert asyncio.run(server_mod.mcp.list_tools())
