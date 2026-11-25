"""GitLab CI/CD manager — thin wrapper around python-gitlab for CI operations."""

from __future__ import annotations

import json
import logging
import os
import stat
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import quote

import gitlab
import gitlab.exceptions as gle
import requests
from gitlab.v4.objects import Project
from urllib3.exceptions import ReadTimeoutError

from gitlab_ci_mcp.errors import ArtifactOperationError

logger = logging.getLogger(__name__)

_MAX_JOB_ARTIFACT_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_JOB_ARTIFACT_LIST_BYTES = 256_000
_MAX_JOB_ARTIFACT_READ_BYTES = 2_000_000
_TEXT_ARTIFACT_EXTENSIONS = {
    ".conf", ".csv", ".err", ".html", ".ini", ".js", ".json", ".jsonl", ".log",
    ".md", ".out", ".properties", ".text", ".ts", ".txt", ".xml", ".yaml", ".yml",
}


@dataclass
class PipelineResult:
    pipeline_id: int
    status: str
    web_url: str
    ref: str
    created_at: str


@dataclass
class ScheduleInfo:
    id: int
    description: str
    cron: str
    cron_timezone: str
    ref: str
    active: bool
    variables: dict[str, str]
    next_run_at: str | None
    web_url: str


class GitLabCIManager:
    """GitLab CI/CD operations wrapper."""

    def __init__(
        self,
        token: str | None = None,
        gitlab_url: str | None = None,
        project_path: str | None = None,
        ssl_verify: bool | None = None,
        no_proxy_domains: list[str] | None = None,
    ) -> None:
        """Initialize manager.

        Args:
            token: GitLab Personal Access Token. Falls back to ``GITLAB_TOKEN`` env.
            gitlab_url: Base URL of GitLab server. Falls back to ``GITLAB_URL`` env.
            project_path: Explicit ``namespace/project`` path. Legacy env fallback requires opt-in.
            ssl_verify: Verify SSL certs. Falls back to ``GITLAB_SSL_VERIFY`` env (default ``true``).
            no_proxy_domains: Domains to add to ``NO_PROXY`` (e.g. self-hosted corp domains).
                Falls back to comma-separated ``GITLAB_NO_PROXY_DOMAINS`` env.
        """
        token = token or os.environ.get("GITLAB_TOKEN")
        gitlab_url = gitlab_url or os.environ.get("GITLAB_URL")
        if project_path is not None and not project_path.strip():
            raise ValueError("project_path must not be empty")
        if project_path is None:
            allow_default = os.environ.get("GITLAB_ALLOW_DEFAULT_PROJECT", "").lower() in {"1", "true", "yes"}
            if allow_default:
                project_path = os.environ.get("GITLAB_PROJECT_PATH")

        if not token:
            raise ValueError("GitLab token is required (pass token= or set GITLAB_TOKEN env)")
        if not gitlab_url:
            raise ValueError("GitLab URL is required (pass gitlab_url= or set GITLAB_URL env)")
        if not project_path:
            raise ValueError(
                "project_path is required (pass it explicitly). For legacy fallback, set "
                "GITLAB_ALLOW_DEFAULT_PROJECT=true and GITLAB_PROJECT_PATH."
            )

        if ssl_verify is None:
            env_val = os.environ.get("GITLAB_SSL_VERIFY", "true").lower()
            ssl_verify = env_val not in ("false", "0", "no")

        if no_proxy_domains is None:
            env_domains = os.environ.get("GITLAB_NO_PROXY_DOMAINS", "")
            no_proxy_domains = [d.strip() for d in env_domains.split(",") if d.strip()]

        self.token = token
        self.gitlab_url = gitlab_url
        self.project_path = project_path

        self._configure_no_proxy(no_proxy_domains)

        self.gl = gitlab.Gitlab(gitlab_url, private_token=token, ssl_verify=ssl_verify)
        self._project: Project | None = None

        logger.debug("GitLabCIManager initialised for %s", project_path)

    @staticmethod
    def _configure_no_proxy(domains: list[str]) -> None:
        """Add domains to ``NO_PROXY`` env and clear ``HTTP(S)_PROXY``.

        Useful when the GitLab instance is inside a corporate network behind a
        local proxy that would otherwise intercept internal traffic.
        """
        if not domains:
            return

        current = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
        items = {s.strip() for s in current.split(",") if s.strip()}
        items.update(domains)
        joined = ",".join(sorted(items))
        os.environ["NO_PROXY"] = joined
        os.environ["no_proxy"] = joined

        for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(var, None)

    @property
    def project(self) -> Project:
        if self._project is None:
            self._project = self.gl.projects.get(self.project_path)
            logger.debug("Loaded project: %s", self._project.name)
        return self._project

    # ─── Pipelines ───

    def trigger_pipeline(
        self,
        ref: str = "master",
        variables: dict[str, str] | None = None,
    ) -> PipelineResult:
        vars_list = [{"key": k, "value": v} for k, v in (variables or {}).items()]
        pipeline = self.project.pipelines.create({"ref": ref, "variables": vars_list})
        return PipelineResult(
            pipeline_id=pipeline.id,
            status=pipeline.status,
            web_url=pipeline.web_url,
            ref=pipeline.ref,
            created_at=pipeline.created_at,
        )

    def get_pipeline_status(self, pipeline_id: int) -> str:
        return self.project.pipelines.get(pipeline_id).status

    def get_pipeline_jobs(self, pipeline_id: int) -> list[dict[str, Any]]:
        pipeline = self.project.pipelines.get(pipeline_id)
        jobs = pipeline.jobs.list(all=True)
        return [
            {
                "id": job.id,
                "name": job.name,
                "stage": job.stage,
                "status": job.status,
                "duration": job.duration,
                "web_url": job.web_url,
            }
            for job in jobs
        ]

    def get_job_log_bounded(self, job_id: int, max_bytes: int = 2_000_000) -> tuple[str, bool, int, int]:
        """Stream a trace into a fixed-size tail buffer.

        The response is consumed in chunks so memory stays bounded while tail
        behavior remains useful for large job logs.
        """
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        job = self.project.jobs.get(job_id)
        path = f"{job.manager.path}/{job.encoded_id}/trace"
        response = self.gl.http_get(
            path,
            streamed=True,
            raw=True,
            timeout=30.0,
            retry_transient_errors=False,
        )
        tail = bytearray()
        bytes_read = 0
        line_breaks = 0
        last_byte: int | None = None
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                bytes_read += len(chunk)
                line_breaks += chunk.count(b"\n")
                last_byte = chunk[-1]
                tail.extend(chunk)
                if len(tail) > max_bytes:
                    del tail[: len(tail) - max_bytes]
        finally:
            response.close()
        truncated = bytes_read > len(tail)
        total_lines = line_breaks + int(last_byte is not None and last_byte != ord("\n"))
        return tail.decode("utf-8", errors="replace"), truncated, bytes_read, total_lines

    def get_job_log(self, job_id: int) -> str:
        """Return a bounded trace for callers using the historical string API."""
        return self.get_job_log_bounded(job_id)[0]

    @staticmethod
    def _validate_artifact_path(artifact_path: str) -> list[str]:
        if not isinstance(artifact_path, str) or not artifact_path or "\\" in artifact_path or "\x00" in artifact_path:
            raise ValueError("artifact_path must be a safe relative artifact path")
        parts = artifact_path.split("/")
        if (
            artifact_path.startswith("/")
            or (len(parts[0]) >= 2 and parts[0][0].isalpha() and parts[0][1] == ":")
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("artifact_path must be a safe relative artifact path")
        return parts

    def _get_job_for_artifacts(self, job_id: int) -> Any:
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
            raise ValueError("job_id must be a positive integer")
        return self.project.jobs.get(job_id)

    def _artifact_api_path(self, job_id: int, suffix: str = "") -> str:
        return f"/projects/{self.project.id}/jobs/{job_id}/artifacts{suffix}"

    def _download_artifacts_archive(self, job_id: int, job: Any) -> bytes:
        try:
            response = self.gl.http_get(
                self._artifact_api_path(job_id),
                streamed=True,
                raw=True,
                timeout=30.0,
                retry_transient_errors=False,
            )
        except gle.GitlabError as exc:
            if getattr(exc, "response_code", None) == 404:
                metadata = getattr(job, "artifacts_file", None)
                if metadata:
                    raise ArtifactOperationError(
                        f"Artifacts archive for job {job_id} is unavailable or expired (GitLab returned 404)."
                    ) from exc
                raise ArtifactOperationError(f"Job {job_id} has no downloadable artifacts archive.") from exc
            raise

        try:
            declared_size = response.headers.get("Content-Length")
            if declared_size:
                if not declared_size.isdigit():
                    raise ArtifactOperationError(f"Artifacts archive for job {job_id} has an invalid size header.")
                if int(declared_size) > _MAX_JOB_ARTIFACT_ARCHIVE_BYTES:
                    raise ArtifactOperationError(
                        f"Artifacts archive exceeds the {_MAX_JOB_ARTIFACT_ARCHIVE_BYTES}-byte listing limit."
                    )
            archive = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                if len(archive) + len(chunk) > _MAX_JOB_ARTIFACT_ARCHIVE_BYTES:
                    raise ArtifactOperationError(
                        f"Artifacts archive exceeds the {_MAX_JOB_ARTIFACT_ARCHIVE_BYTES}-byte listing limit."
                    )
                archive.extend(chunk)
            return bytes(archive)
        finally:
            response.close()

    def list_job_artifacts(self, job_id: int) -> dict[str, Any]:
        """List artifact paths and sizes using the GitLab tree API or a bounded ZIP fallback."""
        job = self._get_job_for_artifacts(job_id)
        for attempt in range(2):
            try:
                return self._list_job_artifacts_once(job_id, job)
            except requests.exceptions.ChunkedEncodingError as exc:
                if attempt == 0:
                    continue
                raise ArtifactOperationError(
                    f"Artifact listing for job {job_id} was interrupted twice by an incomplete response."
                ) from exc
            except requests.exceptions.Timeout as exc:
                raise ArtifactOperationError(
                    f"Artifact listing for job {job_id} timed out while reading the response."
                ) from exc
            except requests.exceptions.ConnectionError as exc:
                timed_out = any(isinstance(arg, ReadTimeoutError) for arg in exc.args)
                message = "timed out while reading the response" if timed_out else "failed while reading the response"
                raise ArtifactOperationError(f"Artifact listing for job {job_id} {message}.") from exc

        raise AssertionError("unreachable")

    def _list_job_artifacts_once(self, job_id: int, job: Any) -> dict[str, Any]:
        try:
            entries = self.gl.http_list(
                self._artifact_api_path(job_id, "/tree"),
                query_data={"recursive": True},
                iterator=True,
                per_page=100,
            )
            result: list[dict[str, Any]] = []
            unsafe_entries_omitted = 0
            encoded_artifacts_size = len(b'{"artifacts":[')
            for entry in entries:
                path = entry.get("path")
                entry_type = entry.get("type")
                if not isinstance(path, str) or entry_type not in {"file", "directory"}:
                    continue
                clean_path = path[:-1] if entry_type == "directory" and path.endswith("/") else path
                try:
                    self._validate_artifact_path(clean_path)
                except ValueError:
                    unsafe_entries_omitted += 1
                    continue
                size = entry.get("size") if entry_type == "file" else None
                artifact = {
                    "path": path,
                    "size": size if isinstance(size, int) and size >= 0 else None,
                    "type": entry_type,
                }
                encoded_artifacts_size += (1 if result else 0) + len(
                    json.dumps(artifact, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                )
                self._ensure_artifact_listing_bounded(
                    encoded_artifacts_size, "tree_api", unsafe_entries_omitted, job_id
                )
                result.append(artifact)
            return {"artifacts": result, "source": "tree_api", "unsafe_entries_omitted": unsafe_entries_omitted}
        except gle.GitlabError as exc:
            if getattr(exc, "response_code", None) != 404:
                raise

        archive_data = self._download_artifacts_archive(job_id, job)
        try:
            with zipfile.ZipFile(BytesIO(archive_data)) as archive:
                result = []
                unsafe_entries_omitted = 0
                encoded_artifacts_size = len(b'{"artifacts":[')
                for entry in archive.infolist():
                    path = entry.filename
                    if entry.is_dir():
                        clean_path = path.rstrip("/")
                        entry_type = "directory"
                        size = None
                    else:
                        clean_path = path
                        entry_type = "file"
                        size = entry.file_size
                    try:
                        self._validate_artifact_path(clean_path)
                    except ValueError:
                        unsafe_entries_omitted += 1
                        continue
                    mode = entry.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        continue
                    artifact = {"path": path, "size": size, "type": entry_type}
                    encoded_artifacts_size += (1 if result else 0) + len(
                        json.dumps(artifact, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    )
                    self._ensure_artifact_listing_bounded(
                        encoded_artifacts_size, "zip_archive", unsafe_entries_omitted, job_id
                    )
                    result.append(artifact)
                return {"artifacts": result, "source": "zip_archive", "unsafe_entries_omitted": unsafe_entries_omitted}
        except (zipfile.BadZipFile, EOFError) as exc:
            raise ArtifactOperationError(f"Artifacts archive for job {job_id} is not a valid ZIP archive.") from exc

    @staticmethod
    def _ensure_artifact_listing_bounded(
        encoded_artifacts_size: int, source: str, unsafe_entries_omitted: int, job_id: int
    ) -> None:
        encoded_size = encoded_artifacts_size + len(
            f'],"source":{json.dumps(source)},"unsafe_entries_omitted":{unsafe_entries_omitted}}}'.encode()
        )
        if encoded_size > MAX_JOB_ARTIFACT_LIST_BYTES:
            raise ArtifactOperationError(
                f"Artifact inventory for job {job_id} exceeds the {MAX_JOB_ARTIFACT_LIST_BYTES}-byte listing limit."
            )

    def get_job_artifact(self, job_id: int, artifact_path: str, max_bytes: int = 1_000_000) -> dict[str, Any]:
        """Read one bounded UTF-8 text artifact without extracting it to disk."""
        self._validate_artifact_path(artifact_path)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        max_bytes = min(max_bytes, _MAX_JOB_ARTIFACT_READ_BYTES)
        self._get_job_for_artifacts(job_id)
        endpoint_path = "/".join(quote(part, safe="") for part in artifact_path.split("/"))
        response = self.gl.http_get(
            self._artifact_api_path(job_id, f"/{endpoint_path}"),
            streamed=True,
            raw=True,
            timeout=30.0,
            retry_transient_errors=False,
        )
        try:
            declared_size = response.headers.get("Content-Length")
            total_size = int(declared_size) if declared_size and declared_size.isdigit() else None
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() or None
            prefix = bytearray()
            bytes_seen = 0
            limit_hit = False
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                bytes_seen += len(chunk)
                room = max_bytes - len(prefix)
                if room > 0:
                    prefix.extend(chunk[:room])
                if len(chunk) > room:
                    limit_hit = True
            if total_size is None:
                total_size = bytes_seen
            truncated = limit_hit or total_size > len(prefix)
            basename = artifact_path.rsplit("/", 1)[-1]
            extension = "." + basename.rsplit(".", 1)[-1].lower() if "." in basename else ""
            text_mime = bool(content_type and (content_type.startswith("text/") or content_type in {
                "application/json", "application/ld+json", "application/xml", "application/yaml", "application/x-yaml",
            }))
            if not text_mime and extension not in _TEXT_ARTIFACT_EXTENSIONS:
                return {
                    "status": "binary", "content": None, "size": total_size, "bytes_returned": 0,
                    "truncated": truncated, "content_type": content_type,
                    "message": "Artifact is not a supported text format; content was not returned.",
                }
            if b"\x00" in prefix:
                return {
                    "status": "binary", "content": None, "size": total_size, "bytes_returned": 0,
                    "truncated": truncated, "content_type": content_type,
                    "message": "Artifact contains binary data; content was not returned.",
                }
            while prefix:
                try:
                    content = prefix.decode("utf-8", errors="strict")
                    break
                except UnicodeDecodeError as exc:
                    if not truncated or exc.reason != "unexpected end of data" or exc.end != len(prefix):
                        return {
                            "status": "invalid_utf8", "content": None, "size": total_size, "bytes_returned": 0,
                            "truncated": truncated, "content_type": content_type,
                            "message": "Artifact is not valid UTF-8; content was not returned.",
                        }
                    del prefix[exc.start:]
                    truncated = True
            else:
                content = ""
            return {
                "status": "ok", "content": content, "size": total_size, "bytes_returned": len(prefix),
                "truncated": truncated, "content_type": content_type, "message": None,
            }
        finally:
            response.close()

    # ─── Schedules ───

    def list_schedules(self) -> list[ScheduleInfo]:
        schedules = self.project.pipelineschedules.list(all=True)
        result: list[ScheduleInfo] = []
        for schedule in schedules:
            detail = self.project.pipelineschedules.get(schedule.id)
            variables: dict[str, str] = {}
            if hasattr(detail, "variables"):
                try:
                    variables = {v.key: v.value for v in detail.variables.list(all=True)}
                except Exception as exc:
                    raise RuntimeError(
                        f"schedule {schedule.id} variables read failed ({type(exc).__name__})"
                    ) from exc
            result.append(
                ScheduleInfo(
                    id=schedule.id,
                    description=schedule.description,
                    cron=schedule.cron,
                    cron_timezone=getattr(schedule, "cron_timezone", "UTC"),
                    ref=schedule.ref,
                    active=schedule.active,
                    variables=variables,
                    next_run_at=getattr(schedule, "next_run_at", None),
                    web_url=f"{self.gitlab_url}/{self.project_path}/-/pipeline_schedules/{schedule.id}/edit",
                )
            )
        return result

    def create_schedule(
        self,
        description: str,
        cron: str,
        variables: dict[str, str],
        ref: str = "master",
        timezone: str = "UTC",
        active: bool = True,
    ) -> int:
        schedule = self.project.pipelineschedules.create(
            {
                "description": description,
                "ref": ref,
                "cron": cron,
                "cron_timezone": timezone,
                "active": active,
            }
        )
        try:
            for key, value in variables.items():
                schedule.variables.create({"key": key, "value": value})
        except Exception as exc:
            try:
                schedule.delete()
                cleanup = "rollback succeeded"
            except Exception as rollback_exc:
                cleanup = f"rollback failed ({type(rollback_exc).__name__})"
            raise RuntimeError(
                f"schedule {schedule.id} variable create failed ({type(exc).__name__}); {cleanup}"
            ) from exc
        return schedule.id

    def update_schedule(
        self,
        schedule_id: int,
        description: str | None = None,
        cron: str | None = None,
        ref: str | None = None,
        active: bool | None = None,
        variables: dict[str, str] | None = None,
    ) -> None:
        schedule = self.project.pipelineschedules.get(schedule_id)
        old_variables = []
        if variables is not None:
            try:
                old_variables = [(v.key, v.value) for v in schedule.variables.list(all=True)]
            except Exception as exc:
                raise RuntimeError(
                    f"schedule {schedule_id} update failed during variable read ({type(exc).__name__})"
                ) from exc
        if description is not None:
            schedule.description = description
        if cron is not None:
            schedule.cron = cron
        if ref is not None:
            schedule.ref = ref
        if active is not None:
            schedule.active = active
        try:
            schedule.save()
        except Exception as exc:
            raise RuntimeError(
                f"schedule {schedule_id} update failed during schedule save ({type(exc).__name__}); "
                "schedule fields may be partially updated"
            ) from exc

        if variables is not None:
            def restore_variables() -> str:
                try:
                    for variable in schedule.variables.list(all=True):
                        variable.delete()
                    for key, value in old_variables:
                        schedule.variables.create({"key": key, "value": value})
                    return "rollback succeeded"
                except Exception as rollback_exc:
                    return f"rollback failed ({type(rollback_exc).__name__})"

            try:
                for var in schedule.variables.list(all=True):
                    var.delete()
            except Exception as exc:
                rollback = restore_variables()
                raise RuntimeError(
                    f"schedule {schedule_id} update failed during variable delete ({type(exc).__name__}); "
                    f"schedule fields were saved; {rollback}"
                ) from exc
            try:
                for key, value in variables.items():
                    schedule.variables.create({"key": key, "value": value})
            except Exception as exc:
                rollback = restore_variables()
                raise RuntimeError(
                    f"schedule {schedule_id} variable update failed ({type(exc).__name__}); "
                    f"schedule fields were saved; {rollback}"
                ) from exc

    def delete_schedule(self, schedule_id: int) -> None:
        schedule = self.project.pipelineschedules.get(schedule_id)
        schedule.delete()
