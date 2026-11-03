"""Regression tests for explicit scope and update-check boundaries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_project_scope_is_strict_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp import _mcp

    monkeypatch.setenv("GITLAB_PROJECT_PATH", "demo/repo")
    monkeypatch.delenv("GITLAB_ALLOW_DEFAULT_PROJECT", raising=False)
    _mcp._managers.clear()
    with pytest.raises(ValueError, match="project_path is required"):
        _mcp.get_ci(None)


def test_project_scope_legacy_fallback_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp import _mcp

    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")
    monkeypatch.setenv("GITLAB_PROJECT_PATH", "demo/repo")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "true")
    _mcp._managers.clear()
    manager = _mcp.get_ci(None)
    assert manager.project_path == "demo/repo"


def test_manager_rejects_explicit_empty_scope_even_in_legacy_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp.ci_manager import GitLabCIManager

    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")
    monkeypatch.setenv("GITLAB_PROJECT_PATH", "demo/repo")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "true")

    with pytest.raises(ValueError, match="project_path must not be empty"):
        GitLabCIManager(project_path="")


def test_gitlab_clients_are_isolated_by_request_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp import _mcp

    class FakeManager:
        def __init__(self, *, project_path: str, token: str | None = None) -> None:
            self.project_path = project_path
            self.token = token
            self.gl = SimpleNamespace(session=SimpleNamespace(close=lambda: None))

    def request_context(token: str):
        request = SimpleNamespace(headers={"x-gitlab-token": token})
        return SimpleNamespace(request_context=SimpleNamespace(request=request))

    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "shared-process-token")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "false")
    monkeypatch.setattr(_mcp, "GitLabCIManager", FakeManager)
    _mcp._managers.clear()

    first = _mcp.get_ci("demo/repo", ctx=request_context("pat-user-a"))
    second = _mcp.get_ci("demo/repo", ctx=request_context("pat-user-b"))
    first_again = _mcp.get_ci("demo/repo", ctx=request_context("pat-user-a"))

    assert first is not second
    assert first is first_again
    assert first.token == "pat-user-a"
    assert second.token == "pat-user-b"
    assert all("pat-user" not in str(key) for key in _mcp._managers)


@pytest.mark.parametrize("headers", [None, {}, {"x-gitlab-token": "  "}])
def test_http_request_requires_pat_without_process_token_fallback(monkeypatch, headers) -> None:
    from gitlab_ci_mcp import _mcp

    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("GITLAB_TOKEN", "shared-process-token")
    request = SimpleNamespace(headers=headers) if headers is not None else None
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=request))

    with pytest.raises(ValueError, match="X-GitLab-Token header is required"):
        _mcp._request_gitlab_token(ctx)


def test_stdio_request_uses_process_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp import _mcp

    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("GITLAB_TOKEN", "stdio-personal-token")

    assert _mcp._request_gitlab_token(None) == "stdio-personal-token"


def test_get_ci_http_mode_does_not_fall_back_to_process_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp import _mcp

    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("GITLAB_TOKEN", "shared-process-token")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "false")
    _mcp._managers.clear()

    with pytest.raises(ValueError, match="X-GitLab-Token header is required"):
        _mcp.get_ci("demo/repo")

    assert not _mcp._managers


def test_manager_cache_evicts_lru_and_closes_evicted_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp import _mcp

    now = {"value": 100.0}
    created = []

    class FakeManager:
        def __init__(self, *, project_path: str, token: str | None = None) -> None:
            self.project_path = project_path
            self.token = token
            self.closed = 0
            self.gl = SimpleNamespace(session=SimpleNamespace(close=lambda: setattr(self, "closed", self.closed + 1)))
            created.append(self)

    def context(token: str):
        return SimpleNamespace(
            request_context=SimpleNamespace(request=SimpleNamespace(headers={"x-gitlab-token": token}))
        )

    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "false")
    monkeypatch.setattr(_mcp, "GitLabCIManager", FakeManager)
    monkeypatch.setattr(_mcp, "_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(_mcp, "_CACHE_TTL_SECONDS", 1800)
    monkeypatch.setattr(_mcp.time, "monotonic", lambda: now["value"])
    _mcp._managers.clear()

    first = _mcp.get_ci("demo/repo", ctx=context("token-a"))
    second = _mcp.get_ci("demo/repo", ctx=context("token-b"))
    assert _mcp.get_ci("demo/repo", ctx=context("token-a")) is first
    third = _mcp.get_ci("demo/repo", ctx=context("token-c"))

    assert second.closed == 1
    assert first.closed == 0
    assert len(_mcp._managers) == 2
    assert third.token == "token-c"


def test_manager_cache_expires_idle_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp import _mcp

    now = {"value": 100.0}
    created = []

    class FakeManager:
        def __init__(self, *, project_path: str, token: str | None = None) -> None:
            self.project_path = project_path
            self.token = token
            self.closed = 0
            self.gl = SimpleNamespace(session=SimpleNamespace(close=lambda: setattr(self, "closed", self.closed + 1)))
            created.append(self)

    def context(token: str):
        return SimpleNamespace(
            request_context=SimpleNamespace(request=SimpleNamespace(headers={"x-gitlab-token": token}))
        )

    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "false")
    monkeypatch.setattr(_mcp, "GitLabCIManager", FakeManager)
    monkeypatch.setattr(_mcp, "_CACHE_TTL_SECONDS", 10)
    monkeypatch.setattr(_mcp.time, "monotonic", lambda: now["value"])
    _mcp._managers.clear()

    expired = _mcp.get_ci("demo/repo", ctx=context("old-token"))
    now["value"] = 111.0
    current = _mcp.get_ci("demo/repo", ctx=context("new-token"))

    assert expired.closed == 1
    assert len(_mcp._managers) == 1
    assert current is not expired


def test_manager_cache_is_thread_safe_for_concurrent_same_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from gitlab_ci_mcp import _mcp

    created = []
    start = threading.Barrier(3)

    class FakeManager:
        def __init__(self, *, project_path: str, token: str | None = None) -> None:
            time.sleep(0.02)
            self.project_path = project_path
            self.token = token
            self.gl = SimpleNamespace(session=SimpleNamespace(close=lambda: None))
            created.append(self)

    context = SimpleNamespace(
        request_context=SimpleNamespace(
            request=SimpleNamespace(headers={"x-gitlab-token": "same-user-token"})
        )
    )
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "false")
    monkeypatch.setattr(_mcp, "GitLabCIManager", FakeManager)
    _mcp._managers.clear()

    def load_manager():
        start.wait()
        return _mcp.get_ci("demo/repo", ctx=context)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(load_manager)
        second = pool.submit(load_manager)
        start.wait()
        first_result, second_result = first.result(), second.result()

    assert first_result is second_result
    assert len(created) == 1


def test_app_shutdown_closes_cached_gitlab_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from gitlab_ci_mcp import _mcp

    class FakeManager:
        def __init__(self, *, project_path: str, token: str | None = None) -> None:
            self.project_path = project_path
            self.token = token
            self.closed = 0
            self.gl = SimpleNamespace(session=SimpleNamespace(close=lambda: setattr(self, "closed", self.closed + 1)))

    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("GITLAB_TOKEN", "stdio-token")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "false")
    monkeypatch.setattr(_mcp, "GitLabCIManager", FakeManager)
    _mcp._managers.clear()
    manager = _mcp.get_ci("demo/repo")

    async def shutdown() -> None:
        async with _mcp.app_lifespan(_mcp.mcp):
            pass

    asyncio.run(shutdown())

    assert manager.closed == 1
    assert not _mcp._managers


def test_update_tool_is_explicitly_registered() -> None:
    import asyncio

    from gitlab_ci_mcp.server import mcp

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert "gitlab_ci_mcp_check_updates" in names


def test_update_check_is_disabled_by_default_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp.tools import updates

    monkeypatch.delenv("MCP_GITLAB_UPDATE_CHECK_ENABLED", raising=False)
    monkeypatch.setattr(updates, "_check", lambda: pytest.fail("disabled update check must not query PyPI"))

    result = updates.gitlab_ci_mcp_check_updates()

    assert result.structuredContent["status"] == "disabled"


def test_update_check_can_be_enabled_and_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from gitlab_ci_mcp.tools import updates

    monkeypatch.setenv("MCP_GITLAB_UPDATE_CHECK_ENABLED", "false")
    monkeypatch.setattr(updates, "_check", lambda: pytest.fail("false must disable update checking"))
    disabled = updates.gitlab_ci_mcp_check_updates()
    assert disabled.structuredContent["status"] == "disabled"

    expected = {"status": "current", "installed_version": "0.5.4", "cached": False}
    calls = []
    monkeypatch.setenv("MCP_GITLAB_UPDATE_CHECK_ENABLED", "true")
    monkeypatch.setattr(updates, "_check", lambda: calls.append(True) or expected)
    enabled = updates.gitlab_ci_mcp_check_updates()

    assert enabled.structuredContent == expected
    assert calls == [True]


def _pipeline(status: str, created_at: str) -> SimpleNamespace:
    return SimpleNamespace(status=status, created_at=created_at)


def test_health_fetches_every_page_and_ignores_bad_or_old_dates() -> None:
    from datetime import datetime, timedelta, timezone

    from gitlab_ci_mcp.pipeline_health import PipelineHealthCollector

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    previous = (now - timedelta(days=10)).isoformat()

    class Pipelines:
        def list(self, **kwargs):
            assert kwargs["get_all"] is True
            return [_pipeline("success", recent) for _ in range(105)] + [
                _pipeline("failed", previous),
                _pipeline("success", "not-a-date"),
                _pipeline("success", (now - timedelta(days=31)).isoformat()),
            ]

    ci = SimpleNamespace(project=SimpleNamespace(pipelines=Pipelines()))
    report = PipelineHealthCollector(ci).collect()

    assert report.total_30d == 106
    assert report.total_7d == 105
    assert report.invalid_timestamps == 1
    assert report.rate_7d == 100


def test_health_api_failure_reaches_mcp_as_named_error(monkeypatch) -> None:
    import asyncio

    from mcp.server.fastmcp.exceptions import ToolError

    from gitlab_ci_mcp.tools import pipelines

    class PipelineList:
        def list(self, **kwargs):
            raise RuntimeError("GitLab unavailable")

    ci = SimpleNamespace(project_path="demo/repo", project=SimpleNamespace(pipelines=PipelineList()))
    monkeypatch.setattr(pipelines, "get_ci", lambda _path: ci)

    with pytest.raises(ToolError, match="pipeline health API request failed"):
        asyncio.run(pipelines.gitlab_pipeline_health(project_path="demo/repo"))


def test_health_mcp_tool_returns_structured_no_data_report(monkeypatch) -> None:
    import asyncio

    from gitlab_ci_mcp.tools import pipelines

    ci = SimpleNamespace(
        project_path="demo/repo",
        project=SimpleNamespace(pipelines=SimpleNamespace(list=lambda **_kwargs: [])),
    )
    monkeypatch.setattr(pipelines, "get_ci", lambda _path: ci)

    result = asyncio.run(pipelines.gitlab_pipeline_health(project_path="demo/repo"))

    assert result.structuredContent["status"] == "no_data"
    assert result.structuredContent["rate_7d"] is None
    assert result.structuredContent["trend"] == "insufficient_data"


def test_health_without_completed_runs_has_no_false_zero_or_flat_trend() -> None:
    from datetime import datetime, timedelta, timezone

    from gitlab_ci_mcp.pipeline_health import PipelineHealthCollector

    now = datetime.now(timezone.utc)
    rows = [
        _pipeline("running", (now - timedelta(days=1)).isoformat()),
        _pipeline("pending", (now - timedelta(days=10)).isoformat()),
    ]
    ci = SimpleNamespace(project=SimpleNamespace(pipelines=SimpleNamespace(list=lambda **_kwargs: rows)))

    report = PipelineHealthCollector(ci).collect()

    assert report.status == "insufficient_data"
    assert report.rate_7d is None
    assert report.trend == "insufficient_data"


def test_health_empty_history_is_no_data_not_zero_rate() -> None:
    from gitlab_ci_mcp.pipeline_health import PipelineHealthCollector

    ci = SimpleNamespace(project=SimpleNamespace(pipelines=SimpleNamespace(list=lambda **_kwargs: [])))

    report = PipelineHealthCollector(ci).collect()

    assert report.status == "no_data"
    assert report.rate_7d is None
    assert report.trend == "insufficient_data"


def test_health_zero_success_rate_is_distinct_from_missing_data() -> None:
    from datetime import datetime, timedelta, timezone

    from gitlab_ci_mcp.pipeline_health import PipelineHealthCollector

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    previous = (now - timedelta(days=10)).isoformat()
    rows = [_pipeline("failed", recent), _pipeline("failed", previous)]
    ci = SimpleNamespace(project=SimpleNamespace(pipelines=SimpleNamespace(list=lambda **_kwargs: rows)))

    report = PipelineHealthCollector(ci).collect()

    assert report.status == "ok"
    assert report.rate_7d == 0
    assert report.trend == "flat"


def test_health_denominator_excludes_non_completed_statuses() -> None:
    from datetime import datetime, timedelta, timezone

    from gitlab_ci_mcp.pipeline_health import PipelineHealthCollector

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    previous = (now - timedelta(days=10)).isoformat()
    rows = [
        _pipeline("success", recent),
        _pipeline("failed", recent),
        _pipeline("running", recent),
        _pipeline("pending", recent),
        _pipeline("manual", recent),
        _pipeline("canceled", recent),
        _pipeline("skipped", recent),
        _pipeline("failed", previous),
    ]
    ci = SimpleNamespace(project=SimpleNamespace(pipelines=SimpleNamespace(list=lambda **_kwargs: rows)))

    report = PipelineHealthCollector(ci).collect()

    assert report.rate_7d == 50
    assert report.completed_7d == 2
    assert report.total_7d == 7
    assert report.rate_basis == "completed pipelines only: success and failed"


def test_health_api_error_includes_request_failure_not_empty_report() -> None:
    from gitlab_ci_mcp.pipeline_health import PipelineHealthCollector

    ci = SimpleNamespace(
        project=SimpleNamespace(
            pipelines=SimpleNamespace(list=lambda **_kwargs: (_ for _ in ()).throw(OSError("offline")))
        )
    )
    with pytest.raises(RuntimeError, match="pipeline health API request failed: offline"):
        PipelineHealthCollector(ci).collect()


def test_schedule_variable_read_error_names_schedule_and_phase() -> None:
    from gitlab_ci_mcp.ci_manager import GitLabCIManager

    schedule = SimpleNamespace(
        id=44,
        description="daily",
        cron="0 0 * * *",
        ref="main",
        active=True,
        variables=SimpleNamespace(list=lambda **_kwargs: (_ for _ in ()).throw(OSError("offline"))),
    )
    project = SimpleNamespace(
        pipelineschedules=SimpleNamespace(
            list=lambda **_kwargs: [schedule], get=lambda _schedule_id: schedule
        )
    )
    manager = SimpleNamespace(
        project=project, gitlab_url="https://gitlab.example", project_path="demo/repo"
    )

    with pytest.raises(RuntimeError, match="schedule 44 variables read failed"):
        GitLabCIManager.list_schedules(manager)


def test_schedule_create_rolls_back_and_names_partial_failure() -> None:
    from gitlab_ci_mcp.ci_manager import GitLabCIManager

    state = {"deleted": False}
    schedule = SimpleNamespace(
        id=55,
        variables=SimpleNamespace(create=lambda _attrs: (_ for _ in ()).throw(OSError("write failed"))),
        delete=lambda: state.update(deleted=True),
    )
    manager = SimpleNamespace(
        project=SimpleNamespace(pipelineschedules=SimpleNamespace(create=lambda _attrs: schedule))
    )

    with pytest.raises(RuntimeError, match="schedule 55.*rollback succeeded"):
        GitLabCIManager.create_schedule(manager, "daily", "0 0 * * *", {"A": "value"})
    assert state["deleted"] is True


def test_schedule_create_names_failed_rollback_without_echoing_variable_value() -> None:
    from gitlab_ci_mcp.ci_manager import GitLabCIManager

    schedule = SimpleNamespace(
        id=56,
        variables=SimpleNamespace(
            create=lambda _attrs: (_ for _ in ()).throw(OSError("SECRET_VALUE"))
        ),
        delete=lambda: (_ for _ in ()).throw(OSError("delete failed")),
    )
    manager = SimpleNamespace(
        project=SimpleNamespace(pipelineschedules=SimpleNamespace(create=lambda _attrs: schedule))
    )

    with pytest.raises(RuntimeError) as error:
        GitLabCIManager.create_schedule(manager, "daily", "0 0 * * *", {"TOKEN": "SECRET_VALUE"})

    assert "schedule 56" in str(error.value)
    assert "rollback failed" in str(error.value)
    assert "SECRET_VALUE" not in str(error.value)


def test_schedule_update_recreates_old_variables_after_write_failure() -> None:
    from gitlab_ci_mcp.ci_manager import GitLabCIManager

    state = {"current": [("OLD", "safe")], "created": 0}

    class Variables:
        def list(self, **_kwargs):
            result = []
            for key, value in list(state["current"]):
                def delete(key=key, value=value):
                    state["current"].remove((key, value))

                result.append(SimpleNamespace(key=key, value=value, delete=delete))
            return result

        def create(self, attrs):
            state["created"] += 1
            if attrs["key"] == "NEW":
                state["current"].append((attrs["key"], attrs["value"]))
                raise OSError("write failed")
            state["current"].append((attrs["key"], attrs["value"]))

    schedule = SimpleNamespace(variables=Variables(), save=lambda: None)
    manager = SimpleNamespace(project=SimpleNamespace(pipelineschedules=SimpleNamespace(get=lambda _id: schedule)))

    with pytest.raises(RuntimeError, match="schedule 66 variable update failed") as error:
        GitLabCIManager.update_schedule(manager, 66, variables={"NEW": "value"})

    assert "schedule fields were saved" in str(error.value)
    assert ("OLD", "safe") in state["current"]
    assert not any(key == "NEW" for key, _value in state["current"])


def test_schedule_update_reports_failed_rollback_without_variable_values() -> None:
    from gitlab_ci_mcp.ci_manager import GitLabCIManager

    state = {"current": [("OLD", "OLD_SECRET")], "writes": 0}

    class Variables:
        def list(self, **_kwargs):
            result = []
            for key, value in list(state["current"]):
                def delete(key=key, value=value):
                    if key == "NEW":
                        raise OSError("cleanup failed")
                    state["current"].remove((key, value))

                result.append(SimpleNamespace(key=key, value=value, delete=delete))
            return result

        def create(self, attrs):
            state["writes"] += 1
            state["current"].append((attrs["key"], attrs["value"]))
            if attrs["key"] == "NEW":
                raise OSError("write failed")

    schedule = SimpleNamespace(variables=Variables(), save=lambda: None)
    manager = SimpleNamespace(project=SimpleNamespace(pipelineschedules=SimpleNamespace(get=lambda _id: schedule)))

    with pytest.raises(RuntimeError) as error:
        GitLabCIManager.update_schedule(manager, 67, variables={"NEW": "NEW_SECRET"})

    assert "rollback failed" in str(error.value)
    assert "schedule fields were saved" in str(error.value)
    assert "OLD_SECRET" not in str(error.value)
    assert "NEW_SECRET" not in str(error.value)


def test_schedule_without_variables_is_distinct_from_read_failure() -> None:
    from gitlab_ci_mcp.ci_manager import GitLabCIManager

    schedule = SimpleNamespace(
        id=44,
        description="daily",
        cron="0 0 * * *",
        ref="main",
        active=True,
        variables=SimpleNamespace(list=lambda **_kwargs: []),
    )
    project = SimpleNamespace(
        pipelineschedules=SimpleNamespace(list=lambda **_kwargs: [schedule], get=lambda _id: schedule)
    )
    manager = SimpleNamespace(
        project=project,
        gitlab_url="https://gitlab.example",
        project_path="demo/repo",
    )

    result = GitLabCIManager.list_schedules(manager)

    assert result[0].variables == {}


def test_merge_request_reports_file_and_api_diff_truncation(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import mrs

    change = {"old_path": "a", "new_path": "a", "diff": "x" * 2500}
    mr = SimpleNamespace(changes=lambda: {"changes": [change], "overflow": True, "changes_count": "150"})
    ci = SimpleNamespace(project=SimpleNamespace(mergerequests=SimpleNamespace(get=lambda _iid: mr)))
    monkeypatch.setattr(mrs, "get_ci", lambda _path: ci)

    result = mrs.gitlab_get_merge_request_changes(mr_iid=3, project_path="demo/repo")
    data = dict(result.structuredContent)

    assert data["files"][0]["diff_truncated"] is True
    assert data["api_overflow"] is True
    assert "diff truncated" in result.content[0].text
    assert "incomplete" in result.content[0].text


def test_merge_request_does_not_treat_string_false_as_overflow(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import mrs

    mr = SimpleNamespace(changes=lambda: {"changes": [], "overflow": "false", "changes_count": "2"})
    ci = SimpleNamespace(project=SimpleNamespace(mergerequests=SimpleNamespace(get=lambda _iid: mr)))
    monkeypatch.setattr(mrs, "get_ci", lambda _path: ci)

    result = mrs.gitlab_get_merge_request_changes(mr_iid=3, project_path="demo/repo")

    assert result.structuredContent["api_overflow"] is False


def test_merge_request_count_suffix_marks_overflow(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import mrs

    mr = SimpleNamespace(changes=lambda: {"changes": [], "changes_count": "1000+"})
    ci = SimpleNamespace(project=SimpleNamespace(mergerequests=SimpleNamespace(get=lambda _iid: mr)))
    monkeypatch.setattr(mrs, "get_ci", lambda _path: ci)

    result = mrs.gitlab_get_merge_request_changes(mr_iid=3, project_path="demo/repo")

    assert result.structuredContent["api_overflow"] is True


def test_branch_listing_applies_search_and_formats_commit(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import branches_tags

    captured = {}
    branch = SimpleNamespace(
        name="release/1.2",
        merged=False,
        protected=True,
        default=False,
        commit={"short_id": "abc123", "title": "Release", "committed_date": "2026-10-01T12:00:00Z"},
    )

    def list_branches(**kwargs):
        captured.update(kwargs)
        return [branch]

    ci = SimpleNamespace(
        project_path="demo/repo",
        project=SimpleNamespace(branches=SimpleNamespace(list=list_branches)),
    )
    monkeypatch.setattr(branches_tags, "get_ci", lambda _path: ci)

    result = branches_tags.gitlab_list_branches(search="release", project_path="demo/repo")

    assert captured["search"] == "release"
    assert result.structuredContent["branches"][0]["commit_short_id"] == "abc123"
    assert "release/1.2" in result.content[0].text


def test_tag_listing_orders_and_formats_tags(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import branches_tags

    captured = {}
    tag = SimpleNamespace(name="v1.2.0", message="release", commit={"short_id": "def456", "committed_date": None})

    def list_tags(**kwargs):
        captured.update(kwargs)
        return [tag]

    ci = SimpleNamespace(project_path="demo/repo", project=SimpleNamespace(tags=SimpleNamespace(list=list_tags)))
    monkeypatch.setattr(branches_tags, "get_ci", lambda _path: ci)

    result = branches_tags.gitlab_list_tags(search="v1", project_path="demo/repo")

    assert captured["order_by"] == "updated"
    assert captured["sort"] == "desc"
    assert result.structuredContent["tags"][0]["name"] == "v1.2.0"


def test_repository_file_is_limited_to_500_lines(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import repo

    contents = "\n".join(f"line {i}" for i in range(510)).encode()
    file_obj = SimpleNamespace(decode=lambda: contents, size=len(contents))
    ci = SimpleNamespace(project=SimpleNamespace(files=SimpleNamespace(get=lambda **_kwargs: file_obj)))
    monkeypatch.setattr(repo, "get_ci", lambda _path: ci)

    result = repo.gitlab_get_file(file_path="README.md", project_path="demo/repo")

    assert result.structuredContent["total_lines"] == 510
    assert result.structuredContent["truncated"] is True
    assert len(result.structuredContent["content"].splitlines()) == 500


def test_repository_tree_passes_paging_and_renders_root(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import repo

    captured = {}

    def tree(**kwargs):
        captured.update(kwargs)
        return [{"name": "src", "type": "tree", "path": "src"}]

    ci = SimpleNamespace(project_path="demo/repo", project=SimpleNamespace(repository_tree=tree))
    monkeypatch.setattr(repo, "get_ci", lambda _path: ci)

    result = repo.gitlab_list_repository_tree(path="", project_path="demo/repo")

    assert captured["page"] == 1
    assert result.structuredContent["path"] == "/"
    assert result.structuredContent["items"][0]["path"] == "src"


@pytest.mark.parametrize("project_path", ["", "   "])
@pytest.mark.parametrize("compatibility", ["false", "true"])
def test_empty_project_scope_never_enables_legacy_fallback(monkeypatch, project_path, compatibility) -> None:
    from gitlab_ci_mcp import _mcp

    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")
    monkeypatch.setenv("GITLAB_PROJECT_PATH", "demo/repo")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", compatibility)
    _mcp._managers.clear()

    with pytest.raises(ValueError, match="project_path must not be empty"):
        _mcp.get_ci(project_path)


def test_project_path_is_required_in_strict_mcp_schemas(monkeypatch) -> None:
    import asyncio

    from gitlab_ci_mcp import _mcp
    from gitlab_ci_mcp.server import mcp

    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "false")
    _mcp.configure_project_path_schema()
    tools = asyncio.run(mcp.list_tools())
    project_tools = [tool for tool in tools if "project_path" in tool.inputSchema.get("properties", {})]

    assert project_tools
    for tool in project_tools:
        schema = tool.inputSchema
        assert "project_path" in schema["required"]
        assert schema["properties"]["project_path"]["type"] == "string"
        assert schema["properties"]["project_path"]["minLength"] == 1


def test_project_path_schema_is_optional_only_in_legacy_mode(monkeypatch) -> None:
    import asyncio

    from gitlab_ci_mcp import _mcp
    from gitlab_ci_mcp.server import mcp

    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "true")
    _mcp.configure_project_path_schema()
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "gitlab_list_pipelines")

    assert "project_path" not in tool.inputSchema.get("required", [])
    assert {schema["type"] for schema in tool.inputSchema["properties"]["project_path"]["anyOf"]} == {
        "string",
        "null",
    }
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "false")
    _mcp.configure_project_path_schema()


def test_resource_fails_clearly_when_strict_scope_has_no_project(monkeypatch) -> None:
    from gitlab_ci_mcp import _mcp
    from gitlab_ci_mcp.resources import project_info_resource

    monkeypatch.setenv("GITLAB_PROJECT_PATH", "demo/repo")
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "false")
    _mcp._managers.clear()

    result = project_info_resource()
    assert "project_path is required" in result


def test_job_log_reader_streams_and_caps_bytes() -> None:
    from gitlab_ci_mcp.ci_manager import GitLabCIManager

    state = {"read_chunks": 0, "closed": False}

    class Response:
        status_code = 200

        def iter_content(self, chunk_size):
            for chunk in (b"abcd\n", b"efgh\n", b"ijkl"):
                state["read_chunks"] += 1
                yield chunk

        def close(self):
            state["closed"] = True

    job = SimpleNamespace(
        manager=SimpleNamespace(
            path="/projects/42/jobs",
            gitlab=SimpleNamespace(http_get=lambda *_a, **_kw: Response()),
        ),
        encoded_id="91",
    )
    fake = SimpleNamespace(
        gl=job.manager.gitlab,
        project=SimpleNamespace(jobs=SimpleNamespace(get=lambda _job_id: job)),
    )

    log, truncated, bytes_read, total_lines = GitLabCIManager.get_job_log_bounded(fake, 91, max_bytes=6)

    assert log == "h\nijkl"
    assert truncated is True
    assert bytes_read == 14
    assert total_lines == 3
    assert state["read_chunks"] == 3
    assert state["closed"] is True


def test_job_log_response_output_is_bounded() -> None:
    from gitlab_ci_mcp.tools.pipelines import _bounded_log_output

    text, truncated = _bounded_log_output(["x" * 300_000])

    assert truncated is True
    assert len(text.encode("utf-8")) <= 256_000
    assert text.endswith("[output truncated; showing tail]")


def test_job_log_tool_exposes_output_truncation(monkeypatch) -> None:
    import asyncio

    from gitlab_ci_mcp.tools import pipelines

    ci = SimpleNamespace(
        get_job_log_bounded=lambda _job_id, _max_bytes: ("x" * 300_000, False, 300_000, 1)
    )
    monkeypatch.setattr(pipelines, "get_ci", lambda _path: ci)

    result = asyncio.run(pipelines.gitlab_get_job_log(job_id=91, project_path="demo/repo"))
    data = dict(result.structuredContent)

    assert data["output_truncated"] is True
    assert len(data["log"].encode("utf-8")) <= 256_000
    assert "output was truncated" in result.content[0].text


def test_regex_matcher_kills_work_past_timeout() -> None:
    import time

    from gitlab_ci_mcp.tools.pipelines import _regex_match_indexes

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        _regex_match_indexes("(a+)+$", ["a" * 100_000 + "!"], timeout=0.2)
    assert time.monotonic() - started < 3


def test_regex_matcher_caps_matches() -> None:
    from gitlab_ci_mcp.tools.pipelines import _regex_match_indexes

    indexes, truncated = _regex_match_indexes("hit", ["hit"] * 1_100)

    assert len(indexes) == 1_000
    assert truncated is True


def test_update_version_comparison_normalizes_trailing_zeroes() -> None:
    from gitlab_ci_mcp.tools.updates import _version

    assert _version("1.0") == _version("1.0.0")
    assert _version("1.2.0rc1") < _version("1.2")


def test_publish_workflow_runs_checks_before_pypi_publish() -> None:
    from pathlib import Path

    workflow = Path(".github/workflows/publish.yml").read_text()
    publish_step = workflow.index("- name: Publish to PyPI")
    assert workflow.index("- name: Test exact tag commit") < publish_step
    assert workflow.index("- name: Lint exact tag commit") < publish_step
    assert "    needs: build" in workflow


def test_update_check_uses_fixed_pypi_url_and_caches_valid_result(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import updates

    state = {"calls": 0}

    class Response:
        status = 200

        def __init__(self):
            self.body = b'{"info":{"version":"0.5.4"}}'

        def read(self, size):
            assert size <= updates._MAX_BYTES + 1
            body, self.body = self.body, b""
            return body

        def release_conn(self):
            pass

    class Http:
        def request(self, method, url, **kwargs):
            state["calls"] += 1
            assert method == "GET"
            assert url == "https://pypi.org/pypi/gitlab-ci-mcp/json"
            assert kwargs["preload_content"] is False
            return Response()

    monkeypatch.setattr(updates.urllib3, "PoolManager", lambda **_kwargs: Http())
    monkeypatch.setattr(updates, "_cache", None)

    first = updates._check()
    second = updates._check()

    assert first["status"] == "current"
    assert second["cached"] is True
    assert state["calls"] == 1


def test_update_check_reads_valid_json_across_response_chunks(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import updates

    class Response:
        status = 200

        def __init__(self):
            self.chunks = [b'{"info":{"', b'version":"0.5.4"}}']

        def read(self, _size):
            return self.chunks.pop(0) if self.chunks else b""

        def release_conn(self):
            pass

    monkeypatch.setattr(
        updates.urllib3, "PoolManager", lambda **_kwargs: SimpleNamespace(request=lambda *_a, **_kw: Response())
    )
    monkeypatch.setattr(updates, "_cache", None)

    result = updates._check()

    assert result["status"] == "current"


def test_update_check_expired_cache_fetches_fresh_metadata(monkeypatch) -> None:
    import time

    from gitlab_ci_mcp.tools import updates

    state = {"calls": 0}

    class Response:
        status = 200

        def __init__(self):
            self.body = b'{"info":{"version":"0.5.4"}}'

        def read(self, _size):
            body, self.body = self.body, b""
            return body

        def release_conn(self):
            pass

    def request(*_args, **_kwargs):
        state["calls"] += 1
        return Response()

    monkeypatch.setattr(updates.urllib3, "PoolManager", lambda **_kwargs: SimpleNamespace(request=request))
    monkeypatch.setattr(
        updates,
        "_cache",
        (time.monotonic() - updates._TTL - 1, {"status": "current", "cached": False}),
    )

    result = updates._check()

    assert result["status"] == "current"
    assert result["cached"] is False
    assert state["calls"] == 1


def test_update_check_network_failure_is_not_reported_as_current(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import updates

    def request_offline(*_args, **_kwargs):
        raise TimeoutError("offline")

    monkeypatch.setattr(
        updates.urllib3,
        "PoolManager",
        lambda **_kwargs: SimpleNamespace(request=request_offline),
    )
    monkeypatch.setattr(updates, "_cache", None)

    result = updates._check()

    assert result["status"] == "unavailable"
    assert "latest_version" not in result


def test_update_check_oversized_response_is_unavailable(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import updates

    class Response:
        status = 200

        def read(self, size):
            return b"x" * size

        def release_conn(self):
            pass

    monkeypatch.setattr(
        updates.urllib3, "PoolManager", lambda **_kwargs: SimpleNamespace(request=lambda *_a, **_kw: Response())
    )
    monkeypatch.setattr(updates, "_cache", None)

    result = updates._check()

    assert result["status"] == "unavailable"
    assert "exceeded" in result["detail"]


def test_update_check_unsupported_version_is_named(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import updates

    class Response:
        status = 200

        def __init__(self):
            self.body = b'{"info":{"version":"0.5.5.post1"}}'

        def read(self, _size):
            body, self.body = self.body, b""
            return body

        def release_conn(self):
            pass

    monkeypatch.setattr(
        updates.urllib3, "PoolManager", lambda **_kwargs: SimpleNamespace(request=lambda *_a, **_kw: Response())
    )
    monkeypatch.setattr(updates, "_cache", None)

    result = updates._check()

    assert result["status"] == "comparison_unavailable"
    assert result["latest_version"] == "0.5.5.post1"


def test_update_check_malformed_json_is_unavailable(monkeypatch) -> None:
    from gitlab_ci_mcp.tools import updates

    class Response:
        status = 200

        def read(self, _size):
            return b"not json"

        def release_conn(self):
            pass

    monkeypatch.setattr(
        updates.urllib3, "PoolManager", lambda **_kwargs: SimpleNamespace(request=lambda *_a, **_kw: Response())
    )
    monkeypatch.setattr(updates, "_cache", None)

    result = updates._check()

    assert result["status"] == "unavailable"
    assert "latest_version" not in result


def test_update_check_is_not_called_during_server_import() -> None:
    import subprocess
    import sys

    script = (
        "import urllib3; "
        "urllib3.PoolManager=lambda **kwargs: (_ for _ in ()).throw(AssertionError('network on import')); "
        "import gitlab_ci_mcp.server"
    )
    subprocess.run([sys.executable, "-c", script], check=True, timeout=5)
