"""Mock-based tests for tool happy paths.

These tests stub out the GitLab REST API via ``responses`` so they do not need
network access or a real GitLab instance. They guard against regressions where
a ``python-gitlab`` upgrade silently changes the shape of returned objects or
where a tool accidentally returns raw ``dict`` instead of a serialised string.
"""

from __future__ import annotations

import json
import os
import urllib.parse

import pytest
import responses

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
    from gitlab_ci_mcp import server

    server._managers.clear()


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


@responses.activate
def test_list_pipelines_json_happy_path() -> None:
    from gitlab_ci_mcp.server import ResponseFormat, gitlab_list_pipelines

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

    out = gitlab_list_pipelines(response_format=ResponseFormat.JSON)
    data = json.loads(out)

    assert data["project"] == PROJECT_PATH
    assert data["count"] == 2
    assert data["pagination"]["has_more"] is False
    assert {p["id"] for p in data["pipelines"]} == {100, 99}
    assert data["pipelines"][0]["status"] == "success"


@responses.activate
def test_list_pipelines_markdown_has_table_and_pagination_footer() -> None:
    from gitlab_ci_mcp.server import gitlab_list_pipelines

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

    out = gitlab_list_pipelines()  # default markdown

    assert "| ID |" in out
    assert "| 100 |" in out or "[100]" in out
    assert "master" in out
    # pagination footer shows next-page hint
    assert "page=" in out.lower() or "total" in out.lower()


@responses.activate
def test_get_pipeline_happy_path() -> None:
    from gitlab_ci_mcp.server import ResponseFormat, gitlab_get_pipeline

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

    out = gitlab_get_pipeline(pipeline_id=100, response_format=ResponseFormat.JSON)
    data = json.loads(out)
    assert data["id"] == 100
    assert data["queued_duration"] == 10
    assert data["finished_at"] == "2026-04-17 10:02:00"


@responses.activate
def test_list_pipelines_401_returns_actionable_error() -> None:
    from gitlab_ci_mcp.server import gitlab_list_pipelines

    _mock_project(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/pipelines",
        json={"message": "401 Unauthorized"},
        status=401,
    )

    out = gitlab_list_pipelines()

    assert out.startswith("Error")
    assert "GITLAB_TOKEN" in out or "api" in out.lower()
    assert "listing pipelines" in out


@responses.activate
def test_get_pipeline_404_returns_actionable_error() -> None:
    from gitlab_ci_mcp.server import gitlab_get_pipeline

    _mock_project(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/pipelines/9999",
        json={"message": "404 Not Found"},
        status=404,
    )

    out = gitlab_get_pipeline(pipeline_id=9999)

    assert out.startswith("Error")
    assert "404" in out
    assert "9999" in out


@responses.activate
def test_project_info_markdown_contains_key_fields() -> None:
    from gitlab_ci_mcp.server import gitlab_project_info

    _mock_project(responses)

    out = gitlab_project_info()

    assert PROJECT_PATH in out
    assert "Default branch" in out
    assert "master" in out
    assert "visibility" in out.lower()


def test_missing_env_config_returns_actionable_error(monkeypatch) -> None:
    """When required env vars are absent, the tool must return an error message,
    not raise."""
    from gitlab_ci_mcp import server

    # Drop required config and clear the cache so next call attempts fresh init.
    for v in ("GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT_PATH"):
        monkeypatch.delenv(v, raising=False)
    os.environ.pop(v, None)
    server._managers.clear()

    out = server.gitlab_list_pipelines()
    assert out.startswith("Error")
    assert "GITLAB" in out
