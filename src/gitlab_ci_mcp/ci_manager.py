"""GitLab CI/CD manager — thin wrapper around python-gitlab for CI operations."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import gitlab
from gitlab.v4.objects import Project

logger = logging.getLogger(__name__)


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
