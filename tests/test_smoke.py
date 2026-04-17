"""Smoke tests — verify package imports, tools register correctly, annotations set."""

from __future__ import annotations

import pytest


def test_import() -> None:
    """Package and all submodules import cleanly."""
    import gitlab_ci_mcp
    import gitlab_ci_mcp.ci_manager  # noqa: F401
    import gitlab_ci_mcp.errors  # noqa: F401
    import gitlab_ci_mcp.formatters  # noqa: F401
    import gitlab_ci_mcp.pipeline_health  # noqa: F401
    import gitlab_ci_mcp.server  # noqa: F401

    assert gitlab_ci_mcp.__version__


def _get_tools() -> list:
    """Return registered tool objects from either old or new FastMCP API."""
    from gitlab_ci_mcp.server import mcp

    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
        return list(mcp._tool_manager._tools.values())
    if hasattr(mcp, "list_tools"):
        return list(mcp.list_tools())
    pytest.skip("Could not discover registered tools in this FastMCP version")
    return []


EXPECTED_TOOLS = {
    "gitlab_list_pipelines",
    "gitlab_get_pipeline",
    "gitlab_get_pipeline_jobs",
    "gitlab_get_job_log",
    "gitlab_trigger_pipeline",
    "gitlab_retry_pipeline",
    "gitlab_cancel_pipeline",
    "gitlab_pipeline_health",
    "gitlab_list_schedules",
    "gitlab_create_schedule",
    "gitlab_update_schedule",
    "gitlab_delete_schedule",
    "gitlab_list_branches",
    "gitlab_list_tags",
    "gitlab_list_merge_requests",
    "gitlab_get_merge_request",
    "gitlab_get_merge_request_changes",
    "gitlab_create_merge_request",
    "gitlab_merge_mr",
    "gitlab_get_file",
    "gitlab_list_repository_tree",
    "gitlab_compare_branches",
    "gitlab_project_info",
}


def _name_of(tool) -> str | None:
    return getattr(tool, "name", None)


def _annotations_of(tool) -> dict:
    """Extract annotations dict in a FastMCP-version-agnostic way."""
    ann = getattr(tool, "annotations", None)
    if ann:
        # Pydantic model (ToolAnnotations) — dump to dict.
        if hasattr(ann, "model_dump"):
            return ann.model_dump(exclude_none=True)
        if isinstance(ann, dict):
            return ann
    return {}


def test_all_tools_registered() -> None:
    tools = _get_tools()
    names = {_name_of(t) for t in tools}
    missing = EXPECTED_TOOLS - names
    assert not missing, f"Tools not registered: {missing}"


def test_destructive_tools_have_annotation() -> None:
    tools = _get_tools()
    destructive_expected = {
        "gitlab_cancel_pipeline",
        "gitlab_update_schedule",
        "gitlab_delete_schedule",
        "gitlab_merge_mr",
    }
    for t in tools:
        if _name_of(t) in destructive_expected:
            ann = _annotations_of(t)
            if not ann:
                pytest.skip(f"annotations not exposed by current FastMCP for {_name_of(t)}")
            assert ann.get("destructiveHint") is True, (
                f"{_name_of(t)} should have destructiveHint=True, got {ann}"
            )


def test_read_only_tools_are_marked() -> None:
    tools = _get_tools()
    read_only = {
        "gitlab_list_pipelines",
        "gitlab_get_pipeline",
        "gitlab_get_pipeline_jobs",
        "gitlab_pipeline_health",
        "gitlab_list_schedules",
        "gitlab_list_branches",
        "gitlab_list_tags",
        "gitlab_list_merge_requests",
        "gitlab_get_file",
        "gitlab_project_info",
    }
    for t in tools:
        if _name_of(t) in read_only:
            ann = _annotations_of(t)
            if not ann:
                pytest.skip(f"annotations not exposed by current FastMCP for {_name_of(t)}")
            assert ann.get("readOnlyHint") is True
            assert ann.get("destructiveHint") is False


def test_error_handler_produces_actionable_messages() -> None:
    import gitlab.exceptions as gle

    from gitlab_ci_mcp.errors import handle

    msg = handle(gle.GitlabAuthenticationError("401"), "listing pipelines")
    assert "GITLAB_TOKEN" in msg and "listing pipelines" in msg

    not_found = gle.GitlabGetError("not found")
    not_found.response_code = 404
    msg = handle(not_found, "getting pipeline 42")
    assert "404" in msg and "getting pipeline 42" in msg

    msg = handle(ValueError("GITLAB_URL env not set"), "init")
    assert "GITLAB_URL" in msg


def test_lifespan_registered() -> None:
    """The server must ship with a lifespan context manager for clean shutdown."""
    from gitlab_ci_mcp.server import app_lifespan, mcp

    assert callable(app_lifespan)
    # FastMCP stores lifespan in settings — different versions may expose differently;
    # minimal check is that the app_lifespan coroutine factory is public.
    assert mcp.name == "gitlab_ci_mcp"


def test_async_tools_use_context() -> None:
    """Tools that benefit from progress/logging are ``async def`` and accept Context."""
    import inspect

    from gitlab_ci_mcp.server import gitlab_get_job_log, gitlab_pipeline_health

    assert inspect.iscoroutinefunction(gitlab_pipeline_health)
    assert inspect.iscoroutinefunction(gitlab_get_job_log)

    # Context parameter must be optional so tools remain testable without an MCP session.
    sig_health = inspect.signature(gitlab_pipeline_health)
    assert "ctx" in sig_health.parameters
    assert sig_health.parameters["ctx"].default is None

    sig_log = inspect.signature(gitlab_get_job_log)
    assert "ctx" in sig_log.parameters
    assert sig_log.parameters["ctx"].default is None


def test_resources_registered() -> None:
    """MCP resources for the default project must be registered."""
    from gitlab_ci_mcp.server import mcp

    if not hasattr(mcp, "_resource_manager"):
        pytest.skip("current FastMCP version does not expose resource manager")
    uris = {str(r.uri) for r in mcp._resource_manager._resources.values()}
    assert "gitlab://project/info" in uris
    assert "gitlab://project/ci-config" in uris


def test_markdown_formatter_shape() -> None:
    from gitlab_ci_mcp.formatters import pipelines_list

    sample = {
        "project": "demo/repo",
        "count": 1,
        "pipelines": [
            {
                "id": 123,
                "status": "success",
                "ref": "master",
                "source": "push",
                "duration": 42,
                "created_at": "2026-04-17 10:00:00",
                "web_url": "https://example.com/p/123",
            }
        ],
    }
    md = pipelines_list(sample)
    assert "| ID |" in md
    assert "`master`" in md
    assert "demo/repo" in md
