from __future__ import annotations

import asyncio
import io
import urllib.parse
import zipfile

import pytest
import responses

from gitlab_ci_mcp.ci_manager import GitLabCIManager

GITLAB_URL = "https://gitlab.example.com"
PROJECT_PATH = "demo/repo"
PROJECT_PATH_ENC = urllib.parse.quote(PROJECT_PATH, safe="")
PROJECT_ID = 42
JOB_ID = 91


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test-secret")
    monkeypatch.setenv("GITLAB_PROJECT_PATH", PROJECT_PATH)
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "true")
    monkeypatch.setenv("GITLAB_SSL_VERIFY", "false")
    return GitLabCIManager()


def _project_and_job(rsp: responses.RequestsMock, artifacts_file: dict | None = None) -> None:
    rsp.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_PATH_ENC}",
        json={"id": PROJECT_ID, "name": "repo", "path_with_namespace": PROJECT_PATH},
    )
    rsp.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}",
        json={
            "id": JOB_ID,
            "artifacts_file": (
                artifacts_file if artifacts_file is not None else {"filename": "artifacts.zip", "size": 200}
            ),
        },
    )


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    return buf.getvalue()


@responses.activate
def test_list_job_artifacts_uses_tree_api(manager: GitLabCIManager) -> None:
    _project_and_job(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}/artifacts/tree",
        json=[
            {"name": "report.json", "path": "reports/report.json", "type": "file", "size": 42},
            {"name": "reports", "path": "reports/", "type": "directory"},
        ],
    )

    result = manager.list_job_artifacts(JOB_ID)

    assert result == {
        "artifacts": [
            {"path": "reports/report.json", "size": 42, "type": "file"},
            {"path": "reports/", "size": None, "type": "directory"},
        ],
        "source": "tree_api",
        "unsafe_entries_omitted": 0,
    }
    assert "glpat-test-secret" not in repr(result)


@responses.activate
def test_list_job_artifacts_tool_returns_structured_content(monkeypatch) -> None:
    from gitlab_ci_mcp.tools.pipelines import gitlab_list_job_artifacts

    monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test-secret")
    monkeypatch.setenv("GITLAB_PROJECT_PATH", PROJECT_PATH)
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "true")
    monkeypatch.setenv("GITLAB_SSL_VERIFY", "false")
    _project_and_job(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}/artifacts/tree",
        json=[{"name": "result.json", "path": "result.json", "type": "file", "size": 20}],
    )

    result = asyncio.run(gitlab_list_job_artifacts(job_id=JOB_ID, project_path=PROJECT_PATH))

    assert dict(result.structuredContent) == {
        "project": PROJECT_PATH,
        "job_id": JOB_ID,
        "count": 1,
        "artifacts": [{"path": "result.json", "size": 20, "type": "file"}],
        "source": "tree_api",
        "unsafe_entries_omitted": 0,
    }
    assert "glpat-test-secret" not in repr(result)


@responses.activate
def test_list_job_artifacts_falls_back_to_safe_zip_listing(manager: GitLabCIManager) -> None:
    archive = _zip_bytes({"reports/report.json": b'{"ok":true}', "../escape.txt": b"no"})
    _project_and_job(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}/artifacts/tree",
        status=404,
    )
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}/artifacts",
        body=archive,
        content_type="application/zip",
    )

    result = manager.list_job_artifacts(JOB_ID)

    assert result == {
        "artifacts": [{"path": "reports/report.json", "size": 11, "type": "file"}],
        "source": "zip_archive",
        "unsafe_entries_omitted": 1,
    }


@pytest.mark.parametrize(
    ("artifacts_file", "message"),
    [({}, "no downloadable artifacts archive"), ({"filename": "artifacts.zip"}, "unavailable or expired")],
)
@responses.activate
def test_list_job_artifacts_names_missing_or_unavailable_archive(
    manager: GitLabCIManager, artifacts_file: dict, message: str
) -> None:
    from gitlab_ci_mcp.errors import ArtifactOperationError

    _project_and_job(responses, artifacts_file)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}/artifacts/tree",
        status=404,
    )
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}/artifacts",
        status=404,
    )

    with pytest.raises(ArtifactOperationError, match=message):
        manager.list_job_artifacts(JOB_ID)


@responses.activate
def test_get_job_artifact_reads_utf8_and_reports_truncation(manager: GitLabCIManager) -> None:
    _project_and_job(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}/artifacts/reports/result.txt",
        body="привет".encode(),
        content_type="text/plain; charset=utf-8",
    )

    result = manager.get_job_artifact(JOB_ID, "reports/result.txt", max_bytes=5)

    assert result["status"] == "ok"
    assert result["content"] == "пр"
    assert result["size"] == 12
    assert result["bytes_returned"] == 4
    assert result["truncated"] is True
    assert result["content_type"] == "text/plain"


@pytest.mark.parametrize("path", ["../secret", "/absolute", "C:/absolute", "reports/../secret", "reports\\secret", ""])
def test_get_job_artifact_rejects_unsafe_paths_before_request(manager: GitLabCIManager, path: str) -> None:
    with pytest.raises(ValueError, match="relative artifact path"):
        manager.get_job_artifact(JOB_ID, path)


@pytest.mark.parametrize(
    ("path", "body", "content_type", "expected_status"),
    [
        ("image.png", b"\x89PNG\r\n\x1a\n", "image/png", "binary"),
        ("report.txt", b"\xff\xfe", "text/plain", "invalid_utf8"),
    ],
)
@responses.activate
def test_get_job_artifact_does_not_return_binary_or_invalid_utf8(
    manager: GitLabCIManager, path: str, body: bytes, content_type: str, expected_status: str
) -> None:
    _project_and_job(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}/artifacts/{path}",
        body=body,
        content_type=content_type,
    )

    result = manager.get_job_artifact(JOB_ID, path)

    assert result["status"] == expected_status
    assert result["content"] is None
    assert result["bytes_returned"] == 0


@responses.activate
def test_missing_artifact_file_is_an_error_not_an_empty_success(monkeypatch) -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    from gitlab_ci_mcp.tools.pipelines import gitlab_get_job_artifact

    monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test-secret")
    monkeypatch.setenv("GITLAB_PROJECT_PATH", PROJECT_PATH)
    monkeypatch.setenv("GITLAB_ALLOW_DEFAULT_PROJECT", "true")
    monkeypatch.setenv("GITLAB_SSL_VERIFY", "false")
    _project_and_job(responses)
    responses.add(
        responses.GET,
        f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/jobs/{JOB_ID}/artifacts/missing.json",
        status=404,
    )

    with pytest.raises(ToolError, match="404") as exc:
        asyncio.run(gitlab_get_job_artifact(job_id=JOB_ID, artifact_path="missing.json", project_path=PROJECT_PATH))

    assert "missing.json" in str(exc.value)
    assert "glpat-test-secret" not in str(exc.value)
