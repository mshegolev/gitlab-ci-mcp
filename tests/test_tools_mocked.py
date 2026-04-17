"""Mock-based tests for tool happy paths.

These tests stub out the GitLab REST API via ``responses`` so they do not need
network access or a real GitLab instance. They guard against regressions where
a ``python-gitlab`` upgrade silently changes the shape of returned objects, or
where a tool's structured content diverges from its declared ``outputSchema``.
"""

from __future__ import annotations

import urllib.parse

import pytest
import responses
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult

GITLAB_URL = "https://gitlab.example.com"
PROJECT_PATH = "demo/repo"
PROJECT_PATH_ENC = urllib.parse.quote(PROJECT_PATH, safe="")
PROJECT_ID = 42


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Fresh env vars and clear manager cache between tests."""
    monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-dummy")
    monkeypatch.setenv("GITLAB_PROJECT_PATH", PROJECT_PATH)
    monkeypatch.setenv("GITLAB_SSL_VERIFY", "false")
    # Import late so env is applied before module init code runs.
    from gitlab_ci_mcp import _mcp

    _mcp._managers.clear()


def _mock_project(rsp: responses.RequestsMock) -> None:
    rsp.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_PATH_ENC}",
        json={
            "id": PROJECT_ID,
            "name": "repo",
            "path_with_namespace": PROJECT_PATH,
            "default_branch": "master",
            "web_url": f"{GITLAB_URL}/{PROJECT_PATH}",
            "visibility": "private",
            "created_at": "2025-01-01T00:00:00Z",
            "last_activity_at": "2026-04-17T10:00:00Z",
            "open_issues_count": 3,
            "forks_count": 0,
            "star_count": 5,
        },
    )


def _structured(result: CallToolResult) -> dict:
    """Extract structuredContent — asserts the tool returned a proper result."""
    assert isinstance(result, CallToolResult), f"expected CallToolResult, got {type(result).__name__}"
    assert result.structuredContent is not None, "tool must populate structuredContent"
    return dict(result.structuredContent)


def _markdown(result: CallToolResult) -> str:
    """Concatenate all text content blocks — the markdown rendering."""
    assert isinstance(result, CallToolResult)
    return "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")


@responses.activate
def test_list_pipelines_structured_and_markdown() -> None:
    from gitlab_ci_mcp.tools.pipelines import gitlab_list_pipelines

    _mock_project(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/pipelines",
        json=[
            {
                "id": 100,
                "status": "success",
                "ref": "master",
                "source": "schedule",
                "created_at": "2026-04-17T10:00:00Z",
                "duration": 123,
                "web_url": f"{GITLAB_URL}/{PROJECT_PATH}/-/pipelines/100",
            },
            {
                "id": 99,
                "status": "failed",
                "ref": "master",
                "source": "push",
                "created_at": "2026-04-16T09:00:00Z",
                "duration": 45,
                "web_url": f"{GITLAB_URL}/{PROJECT_PATH}/-/pipelines/99",
            },
        ],
        headers={
            "X-Total": "2",
            "X-Total-Pages": "1",
            "X-Per-Page": "20",
            "X-Page": "1",
            "X-Next-Page": "",
        },
    )

    result = gitlab_list_pipelines()

    # structuredContent exposes the typed payload
    data = _structured(result)
    assert data["project"] == PROJECT_PATH
    assert data["count"] == 2
    assert data["pagination"]["has_more"] is False
    assert {p["id"] for p in data["pipelines"]} == {100, 99}
    assert data["pipelines"][0]["status"] == "success"

    # content block carries a readable markdown summary
    md = _markdown(result)
    assert "| ID |" in md
    assert "master" in md


@responses.activate
def test_list_pipelines_markdown_has_pagination_footer() -> None:
    from gitlab_ci_mcp.tools.pipelines import gitlab_list_pipelines

    _mock_project(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/pipelines",
        json=[
            {
                "id": 100,
                "status": "success",
                "ref": "master",
                "source": "schedule",
                "created_at": "2026-04-17T10:00:00Z",
                "duration": 123,
                "web_url": f"{GITLAB_URL}/{PROJECT_PATH}/-/pipelines/100",
            }
        ],
        headers={"X-Total": "97", "X-Total-Pages": "5", "X-Page": "1", "X-Next-Page": "2", "X-Per-Page": "20"},
    )

    md = _markdown(gitlab_list_pipelines())
    assert "| ID |" in md
    assert "master" in md
    assert "page=" in md.lower() or "total" in md.lower()


@responses.activate
def test_get_pipeline_happy_path() -> None:
    from gitlab_ci_mcp.tools.pipelines import gitlab_get_pipeline

    _mock_project(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/pipelines/100",
        json={
            "id": 100,
            "status": "success",
            "ref": "master",
            "source": "push",
            "created_at": "2026-04-17T10:00:00Z",
            "updated_at": "2026-04-17T10:02:00Z",
            "started_at": "2026-04-17T10:00:10Z",
            "finished_at": "2026-04-17T10:02:00Z",
            "duration": 110,
            "queued_duration": 10,
            "web_url": f"{GITLAB_URL}/{PROJECT_PATH}/-/pipelines/100",
        },
    )

    data = _structured(gitlab_get_pipeline(pipeline_id=100))
    assert data["id"] == 100
    assert data["queued_duration"] == 10
    assert data["finished_at"] == "2026-04-17 10:02:00"


@responses.activate
def test_list_pipelines_401_raises_actionable_error() -> None:
    from gitlab_ci_mcp.tools.pipelines import gitlab_list_pipelines

    _mock_project(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/pipelines",
        json={"message": "401 Unauthorized"},
        status=401,
    )

    with pytest.raises(ToolError) as excinfo:
        gitlab_list_pipelines()

    msg = str(excinfo.value)
    assert "GITLAB_TOKEN" in msg or "api" in msg.lower()
    assert "listing pipelines" in msg


@responses.activate
def test_get_pipeline_404_raises_actionable_error() -> None:
    from gitlab_ci_mcp.tools.pipelines import gitlab_get_pipeline

    _mock_project(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/pipelines/9999",
        json={"message": "404 Not Found"},
        status=404,
    )

    with pytest.raises(ToolError) as excinfo:
        gitlab_get_pipeline(pipeline_id=9999)

    msg = str(excinfo.value)
    assert "404" in msg
    assert "9999" in msg


@responses.activate
def test_project_info_markdown_contains_key_fields() -> None:
    from gitlab_ci_mcp.tools.repo import gitlab_project_info

    _mock_project(responses)

    result = gitlab_project_info()
    data = _structured(result)
    assert data["path_with_namespace"] == PROJECT_PATH
    assert data["default_branch"] == "master"

    md = _markdown(result)
    assert PROJECT_PATH in md
    assert "Default branch" in md
    assert "master" in md
    assert "visibility" in md.lower()


def test_missing_env_config_raises_actionable_error(monkeypatch) -> None:
    """When required env vars are absent, the tool must raise ToolError with an
    actionable message, not a raw traceback."""
    from gitlab_ci_mcp import _mcp
    from gitlab_ci_mcp.tools.pipelines import gitlab_list_pipelines

    for v in ("GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT_PATH"):
        monkeypatch.delenv(v, raising=False)
    _mcp._managers.clear()

    with pytest.raises(ToolError) as excinfo:
        gitlab_list_pipelines()

    msg = str(excinfo.value)
    assert "GITLAB" in msg
