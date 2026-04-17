"""Smoke tests — verify package imports and tools are registered."""


def test_import() -> None:
    import gitlab_ci_mcp
    import gitlab_ci_mcp.ci_manager
    import gitlab_ci_mcp.pipeline_health
    import gitlab_ci_mcp.server

    assert gitlab_ci_mcp.__version__


def test_tools_registered() -> None:
    from gitlab_ci_mcp.server import mcp

    # FastMCP exposes a ``_tool_manager`` with registered tools on older SDKs,
    # newer versions use ``list_tools``. Support both.
    names: list[str] = []
    if hasattr(mcp, "_tool_manager"):
        names = list(mcp._tool_manager._tools.keys())  # type: ignore[attr-defined]
    elif hasattr(mcp, "list_tools"):
        names = [t.name for t in mcp.list_tools()]

    expected = {
        "gitlab_list_pipelines",
        "gitlab_get_pipeline",
        "gitlab_trigger_pipeline",
        "gitlab_list_schedules",
        "gitlab_list_merge_requests",
        "gitlab_create_merge_request",
        "gitlab_get_file",
        "gitlab_project_info",
        "gitlab_pipeline_health",
    }
    missing = expected - set(names)
    assert not missing, f"Tools not registered: {missing}"
