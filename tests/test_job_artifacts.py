from __future__ import annotations

import asyncio
import io
import urllib.parse
import zipfile

import gitlab.exceptions as gle
import pytest
import requests
import responses
from urllib3.exceptions import ReadTimeoutError

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


def test_list_job_artifacts_retries_chunked_tree_from_the_beginning(manager, monkeypatch) -> None:
    calls = 0

    def http_list(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield {"path": "partial.txt", "type": "file", "size": 7}
            raise requests.exceptions.ChunkedEncodingError("incomplete response")
        yield {"path": "complete.txt", "type": "file", "size": 8}

    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(manager.gl, "http_list", http_list)

    result = manager.list_job_artifacts(JOB_ID)

    assert calls == 2
    assert result["artifacts"] == [{"path": "complete.txt", "size": 8, "type": "file"}]


def test_list_job_artifacts_repeated_chunked_tree_fails_without_partial_result(manager, monkeypatch) -> None:
    calls = 0

    def http_list(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield {"path": "partial.txt", "type": "file", "size": 7}
        raise requests.exceptions.ChunkedEncodingError("incomplete response")

    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(manager.gl, "http_list", http_list)

    from gitlab_ci_mcp.errors import ArtifactOperationError

    with pytest.raises(ArtifactOperationError, match="incomplete"):
        manager.list_job_artifacts(JOB_ID)
    assert calls == 2


def test_list_job_artifacts_retries_interrupted_zip_and_closes_each_response(manager, monkeypatch) -> None:
    archive_bytes = _zip_bytes({"complete.txt": b"ok"})
    responses_seen = []

    class StreamResponse:
        headers = {"Content-Length": str(len(archive_bytes))}

        def __init__(self, interrupted: bool):
            self.interrupted = interrupted
            self.closed = False

        def iter_content(self, chunk_size):
            if self.interrupted:
                yield b"PK\x03\x04partial"
                raise requests.exceptions.ChunkedEncodingError("incomplete ZIP response")
            yield archive_bytes

        def close(self):
            self.closed = True

    def http_list(*args, **kwargs):
        raise gle.GitlabGetError("not found", response_code=404)

    def http_get(*args, **kwargs):
        response = StreamResponse(interrupted=not responses_seen)
        responses_seen.append(response)
        return response

    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(manager.gl, "http_list", http_list)
    monkeypatch.setattr(manager.gl, "http_get", http_get)

    result = manager.list_job_artifacts(JOB_ID)

    assert result["source"] == "zip_archive"
    assert result["artifacts"] == [{"path": "complete.txt", "size": 2, "type": "file"}]
    assert len(responses_seen) == 2
    assert all(response.closed for response in responses_seen)


def test_list_job_artifacts_does_not_retry_forbidden_tree(manager, monkeypatch) -> None:
    calls = 0

    def http_list(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise gle.GitlabGetError("forbidden", response_code=403)

    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(manager.gl, "http_list", http_list)

    with pytest.raises(gle.GitlabGetError):
        manager.list_job_artifacts(JOB_ID)
    assert calls == 1


def test_list_job_artifacts_rejects_inventory_over_output_limit(manager, monkeypatch) -> None:
    from gitlab_ci_mcp.errors import ArtifactOperationError

    def http_list(*args, **kwargs):
        yield {"path": "x" * 256_001, "type": "file", "size": 1}

    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(manager.gl, "http_list", http_list)

    with pytest.raises(ArtifactOperationError, match="listing limit"):
        manager.list_job_artifacts(JOB_ID)


def test_list_job_artifacts_reports_corrupt_zip(manager, monkeypatch) -> None:
    from gitlab_ci_mcp.errors import ArtifactOperationError

    class StreamResponse:
        headers = {"Content-Length": "7"}

        def iter_content(self, chunk_size):
            yield b"not zip"

        def close(self):
            pass

    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(
        manager.gl,
        "http_list",
        lambda *args, **kwargs: (_ for _ in ()).throw(gle.GitlabGetError("not found", response_code=404)),
    )
    monkeypatch.setattr(manager.gl, "http_get", lambda *args, **kwargs: StreamResponse())

    with pytest.raises(ArtifactOperationError, match="not a valid ZIP"):
        manager.list_job_artifacts(JOB_ID)


def test_list_job_artifacts_reports_timeout_without_retry(manager, monkeypatch) -> None:
    calls = 0

    def http_list(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise requests.Timeout("timeout detail")

    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(manager.gl, "http_list", http_list)

    from gitlab_ci_mcp.errors import ArtifactOperationError

    with pytest.raises(ArtifactOperationError, match="timed out") as exc:
        manager.list_job_artifacts(JOB_ID)
    assert calls == 1
    assert "timeout detail" not in str(exc.value)


def test_list_job_artifacts_normalizes_stream_read_timeout_without_retry(manager, monkeypatch) -> None:
    calls = 0

    def http_list(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise requests.ConnectionError(ReadTimeoutError(None, None, "private timeout detail"))

    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(manager.gl, "http_list", http_list)

    from gitlab_ci_mcp.errors import ArtifactOperationError

    with pytest.raises(ArtifactOperationError, match="timed out") as exc:
        manager.list_job_artifacts(JOB_ID)
    assert calls == 1
    assert "private timeout detail" not in str(exc.value)


def test_list_job_artifacts_rejects_oversized_archive_and_closes_response(manager, monkeypatch) -> None:
    import gitlab.exceptions as gle

    from gitlab_ci_mcp.ci_manager import _MAX_JOB_ARTIFACT_ARCHIVE_BYTES
    from gitlab_ci_mcp.errors import ArtifactOperationError

    class StreamResponse:
        headers = {"Content-Length": str(_MAX_JOB_ARTIFACT_ARCHIVE_BYTES + 1)}
        closed = False

        def iter_content(self, chunk_size):
            raise AssertionError("oversized archive must be rejected before reading")

        def close(self):
            self.closed = True

    response = StreamResponse()
    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(
        manager.gl,
        "http_list",
        lambda *args, **kwargs: (_ for _ in ()).throw(gle.GitlabGetError("not found", response_code=404)),
    )
    monkeypatch.setattr(manager.gl, "http_get", lambda *args, **kwargs: response)

    with pytest.raises(ArtifactOperationError, match="archive exceeds"):
        manager.list_job_artifacts(JOB_ID)
    assert response.closed is True


def test_list_job_artifacts_rejects_malformed_archive_size_header(manager, monkeypatch) -> None:
    import gitlab.exceptions as gle

    from gitlab_ci_mcp.errors import ArtifactOperationError

    class StreamResponse:
        headers = {"Content-Length": "unknown"}
        closed = False

        def iter_content(self, chunk_size):
            raise AssertionError("malformed size header must fail before reading")

        def close(self):
            self.closed = True

    response = StreamResponse()
    monkeypatch.setattr(manager, "_get_job_for_artifacts", lambda job_id: object())
    monkeypatch.setattr(manager, "_artifact_api_path", lambda job_id, suffix="": f"/jobs/{job_id}{suffix}")
    monkeypatch.setattr(
        manager.gl,
        "http_list",
        lambda *args, **kwargs: (_ for _ in ()).throw(gle.GitlabGetError("not found", response_code=404)),
    )
    monkeypatch.setattr(manager.gl, "http_get", lambda *args, **kwargs: response)

    with pytest.raises(ArtifactOperationError, match="invalid size header"):
        manager.list_job_artifacts(JOB_ID)
    assert response.closed is True


def test_list_job_artifacts_caps_the_complete_mcp_response(monkeypatch) -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    from gitlab_ci_mcp.tools import pipelines

    class FakeManager:
        project_path = PROJECT_PATH

        def list_job_artifacts(self, job_id):
            return {
                "artifacts": [
                    {"path": f"reports/{index:04d}-{'x' * 115}.json", "size": 10, "type": "file"}
                    for index in range(1_500)
                ],
                "source": "tree_api",
                "unsafe_entries_omitted": 0,
            }

    monkeypatch.setattr(pipelines, "get_ci", lambda project_path, ctx=None: FakeManager())

    with pytest.raises(ToolError, match="response.*listing limit"):
        asyncio.run(pipelines.gitlab_list_job_artifacts(job_id=JOB_ID, project_path=PROJECT_PATH))


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
