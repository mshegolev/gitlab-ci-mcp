"""FastMCP server exposing GitLab CI/CD operations as MCP tools.

The server speaks the Model Context Protocol over stdio and exposes 22 tools
covering pipelines, schedules, branches, tags, merge requests, repository files
and a pipeline health report. All tools share a common set of design choices:

* **Input validation** via Pydantic ``Field(...)`` constraints on every argument.
* **Tool annotations** (``readOnlyHint``, ``destructiveHint``, ``idempotentHint``,
  ``openWorldHint``) so MCP clients can classify the operation.
* **Structured error messages** that tell the agent *why* the call failed and
  *what to do next* (e.g. "Check GITLAB_TOKEN scope").
* **Dual response format** — ``markdown`` (default) gives a compact table or
  summary; ``json`` returns the raw dict for programmatic consumers.
"""

from __future__ import annotations

import json
import logging
import warnings
from enum import Enum
from typing import Annotated, Any, Literal

import urllib3
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from gitlab_ci_mcp import errors, formatters, pagination
from gitlab_ci_mcp.ci_manager import GitLabCIManager

warnings.filterwarnings("ignore")
urllib3.disable_warnings()

logger = logging.getLogger(__name__)

mcp = FastMCP("gitlab_ci_mcp")

_managers: dict[str, GitLabCIManager] = {}


class ResponseFormat(str, Enum):
    """Output format of tool responses."""

    MARKDOWN = "markdown"
    JSON = "json"


# ── Shared annotated parameter types ────────────────────────────────────────

ProjectPath = Annotated[
    str | None,
    Field(
        default=None,
        description=(
            "GitLab project path (e.g. 'my-org/my-repo'). When omitted, the "
            "default from GITLAB_PROJECT_PATH env var is used."
        ),
    ),
]

ResponseFormatParam = Annotated[
    ResponseFormat,
    Field(
        default=ResponseFormat.MARKDOWN,
        description=(
            "Output format: 'markdown' for a compact human-readable summary "
            "(default) or 'json' for the full raw structure."
        ),
    ),
]


# ── Utilities ────────────────────────────────────────────────────────────────


def _get_ci(project_path: str | None) -> GitLabCIManager:
    """Return a cached ``GitLabCIManager`` for the given project path.

    ``None`` uses the default from env. Managers are cached per path so the
    python-gitlab HTTP session is reused across tool calls.
    """
    key = project_path or ""
    if key not in _managers:
        _managers[key] = GitLabCIManager(project_path=project_path or None)
    return _managers[key]


def _ts(dt_str: str | None) -> str | None:
    """Trim an ISO timestamp to second-precision, space-separated form."""
    if not dt_str:
        return None
    return dt_str[:19].replace("T", " ")


def _render(data: dict, fmt: ResponseFormat, md_fn) -> str:
    """Serialise a dict to markdown (via ``md_fn``) or pretty-printed JSON."""
    if fmt == ResponseFormat.MARKDOWN:
        return md_fn(data)
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def _json(data: dict) -> str:
    """Pretty-print JSON without a markdown formatter (used by write tools)."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Pipelines                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝


PipelineStatus = Literal[
    "created", "waiting_for_resource", "preparing", "pending", "running",
    "success", "failed", "canceled", "skipped", "manual", "scheduled",
]
PipelineSource = Literal[
    "push", "web", "trigger", "schedule", "api", "external", "pipeline",
    "chat", "webide", "merge_request_event", "external_pull_request_event",
    "parent_pipeline", "ondemand_dast_scan", "ondemand_dast_validation",
]


@mcp.tool(
    name="gitlab_list_pipelines",
    annotations={
        "title": "List GitLab Pipelines",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_list_pipelines(
    ref: Annotated[
        str | None,
        Field(default=None, description="Filter by branch or tag name (e.g. 'master').", max_length=255),
    ] = None,
    status: Annotated[
        PipelineStatus | None, Field(default=None, description="Filter by pipeline status.")
    ] = None,
    source: Annotated[
        PipelineSource | None, Field(default=None, description="Filter by pipeline trigger source.")
    ] = None,
    per_page: Annotated[
        int, Field(default=20, ge=1, le=100, description="Items per page (1–100).")
    ] = 20,
    page: Annotated[int, Field(default=1, ge=1, description="1-based page number.")] = 1,
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """List recent pipelines of a project, newest first.

    Use for triage ("show failed pipelines on master"), release readiness checks,
    or feeding pipeline IDs into follow-up calls. Read-only and idempotent.

    Returns:
        Markdown table or JSON with keys ``project``, ``count``, ``pagination`` and
        ``pipelines[]`` (each with ``id``, ``status``, ``ref``, ``source``, ``duration``,
        ``created_at``, ``web_url``).

    Examples:
        - "Show failed pipelines on master" → ``status='failed'``, ``ref='master'``
        - "Last nightly schedule runs" → ``source='schedule'``
        - "Second page of pipelines" → ``page=2``
        - Don't use when you have a specific pipeline ID — use ``gitlab_get_pipeline`` instead.
    """
    try:
        ci = _get_ci(project_path)
        kwargs: dict[str, Any] = {"per_page": per_page, "page": page, "get_all": False}
        if ref:
            kwargs["ref"] = ref
        if status:
            kwargs["status"] = status
        if source:
            kwargs["source"] = source
        pipelines = ci.project.pipelines.list(**kwargs)
        data = {
            "project": ci.project_path,
            "count": len(pipelines),
            "pagination": pagination.extract(pipelines),
            "pipelines": [
                {
                    "id": p.id,
                    "status": p.status,
                    "ref": p.ref,
                    "source": getattr(p, "source", None),
                    "created_at": _ts(p.created_at),
                    "duration": getattr(p, "duration", None),
                    "web_url": p.web_url,
                }
                for p in pipelines
            ],
        }
        return _render(data, response_format, formatters.pipelines_list)
    except Exception as exc:
        return errors.handle(exc, "listing pipelines")


@mcp.tool(
    name="gitlab_get_pipeline",
    annotations={
        "title": "Get GitLab Pipeline",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_get_pipeline(
    pipeline_id: Annotated[int, Field(description="Numeric pipeline ID (not ``iid``).", gt=0)],
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Get a single pipeline with full timing details.

    Useful right after ``gitlab_list_pipelines`` — lists only return summaries.
    Returns status, ref, source, durations (queued/total), and started/finished timestamps.

    Examples:
        - "Why was pipeline 123 slow" → check ``queued_duration`` and ``duration`` fields
        - "Is pipeline 456 still running" → look at ``status``
        - Don't use to see individual jobs — use ``gitlab_get_pipeline_jobs``.
    """
    try:
        ci = _get_ci(project_path)
        p = ci.project.pipelines.get(pipeline_id)
        data = {
            "id": p.id,
            "status": p.status,
            "ref": p.ref,
            "source": getattr(p, "source", None),
            "created_at": _ts(p.created_at),
            "updated_at": _ts(getattr(p, "updated_at", None)),
            "started_at": _ts(getattr(p, "started_at", None)),
            "finished_at": _ts(getattr(p, "finished_at", None)),
            "duration": getattr(p, "duration", None),
            "queued_duration": getattr(p, "queued_duration", None),
            "web_url": p.web_url,
        }
        return _render(data, response_format, formatters.pipeline_detail)
    except Exception as exc:
        return errors.handle(exc, f"getting pipeline {pipeline_id}")


@mcp.tool(
    name="gitlab_get_pipeline_jobs",
    annotations={
        "title": "List Pipeline Jobs",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_get_pipeline_jobs(
    pipeline_id: Annotated[int, Field(description="Numeric pipeline ID.", gt=0)],
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """List jobs of a pipeline with stage, status, duration and web URL.

    Use after noticing a failed pipeline to drill down into which specific job
    broke and fetch its log via ``gitlab_get_job_log``.

    Examples:
        - "What jobs are in pipeline 123" → ``pipeline_id=123``
        - "Which job failed in pipeline 456" → filter result by ``status='failed'`` client-side
        - Don't use for overall pipeline status — use ``gitlab_get_pipeline`` instead.
    """
    try:
        ci = _get_ci(project_path)
        jobs = ci.get_pipeline_jobs(pipeline_id)
        data = {"pipeline_id": pipeline_id, "jobs_count": len(jobs), "jobs": jobs}
        return _render(data, response_format, formatters.pipeline_jobs)
    except Exception as exc:
        return errors.handle(exc, f"listing jobs of pipeline {pipeline_id}")


@mcp.tool(
    name="gitlab_get_job_log",
    annotations={
        "title": "Get Job Log",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_get_job_log(
    job_id: Annotated[int, Field(description="Numeric job ID (from ``gitlab_get_pipeline_jobs``).", gt=0)],
    tail: Annotated[
        int,
        Field(default=100, ge=1, le=5000, description="Return only the last N lines (1–5000, default 100)."),
    ] = 100,
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Fetch the trace/log of a job, limited to the last ``tail`` lines.

    Long logs are truncated to save context. Start with the default 100 lines
    and ask for more if you need older context.

    Examples:
        - "Why did job 789 fail" → default tail=100, look at the end of the log
        - "Show me the first stage output of job 789" → ``tail=5000`` and scan for stage separator
    """
    try:
        ci = _get_ci(project_path)
        log = ci.get_job_log(job_id)
        lines = log.splitlines()
        total = len(lines)
        if tail and tail < total:
            lines = lines[-tail:]
        data = {
            "job_id": job_id,
            "total_lines": total,
            "showing_last": len(lines),
            "log": "\n".join(lines),
        }
        return _render(data, response_format, formatters.job_log)
    except Exception as exc:
        return errors.handle(exc, f"getting log of job {job_id}")


@mcp.tool(
    name="gitlab_trigger_pipeline",
    annotations={
        "title": "Trigger Pipeline",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
def gitlab_trigger_pipeline(
    ref: Annotated[
        str, Field(default="master", description="Branch or tag to run the pipeline on.", min_length=1, max_length=255)
    ] = "master",
    variables: Annotated[
        dict[str, str] | None,
        Field(default=None, description="Optional CI variables to pass to the pipeline (``{key: value}``)."),
    ] = None,
    project_path: ProjectPath = None,
) -> str:
    """Create a new pipeline on the given ref, optionally with CI variables.

    **Not idempotent**: each call creates a new pipeline. Consumes minutes on
    your runners — avoid calling in loops.

    Returns JSON with ``pipeline_id``, ``status``, ``ref``, ``web_url``, ``created_at``.

    Examples:
        - "Run the pipeline on master" → default (``ref='master'``)
        - "Run the pipeline on feature/x with DEBUG=1" → ``ref='feature/x'``, ``variables={'DEBUG': '1'}``
        - Don't call to retry — use ``gitlab_retry_pipeline`` which keeps the same pipeline ID.
    """
    try:
        ci = _get_ci(project_path)
        result = ci.trigger_pipeline(ref=ref, variables=variables)
        return _json(
            {
                "pipeline_id": result.pipeline_id,
                "status": result.status,
                "ref": result.ref,
                "web_url": result.web_url,
                "created_at": result.created_at,
                "status_note": "pipeline created — poll gitlab_get_pipeline for progress",
            }
        )
    except Exception as exc:
        return errors.handle(exc, f"triggering pipeline on {ref}")


@mcp.tool(
    name="gitlab_retry_pipeline",
    annotations={
        "title": "Retry Failed Jobs of Pipeline",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
def gitlab_retry_pipeline(
    pipeline_id: Annotated[int, Field(description="Pipeline ID to retry failed jobs for.", gt=0)],
    project_path: ProjectPath = None,
) -> str:
    """Retry all failed jobs of an existing pipeline.

    Creates new job runs (new history entries). Safe to call when the pipeline
    has at least one failed/canceled job; has no effect if everything already
    passed.
    """
    try:
        ci = _get_ci(project_path)
        pipeline = ci.project.pipelines.get(pipeline_id)
        pipeline.retry()
        pipeline.refresh()
        return _json({"pipeline_id": pipeline.id, "status": pipeline.status, "web_url": pipeline.web_url})
    except Exception as exc:
        return errors.handle(exc, f"retrying pipeline {pipeline_id}")


@mcp.tool(
    name="gitlab_cancel_pipeline",
    annotations={
        "title": "Cancel Running Pipeline",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_cancel_pipeline(
    pipeline_id: Annotated[int, Field(description="Pipeline ID to cancel.", gt=0)],
    project_path: ProjectPath = None,
) -> str:
    """Cancel a running pipeline. In-flight jobs will be interrupted.

    Destructive for *in-progress* work. Cancelling an already-finished pipeline
    is a no-op.
    """
    try:
        ci = _get_ci(project_path)
        pipeline = ci.project.pipelines.get(pipeline_id)
        pipeline.cancel()
        pipeline.refresh()
        return _json({"pipeline_id": pipeline.id, "status": pipeline.status, "web_url": pipeline.web_url})
    except Exception as exc:
        return errors.handle(exc, f"cancelling pipeline {pipeline_id}")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Pipeline health                                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝


@mcp.tool(
    name="gitlab_pipeline_health",
    annotations={
        "title": "Pipeline Health Report",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_pipeline_health(
    ref: Annotated[
        str, Field(default="master", description="Branch to analyse.", min_length=1, max_length=255)
    ] = "master",
    source: Annotated[
        PipelineSource,
        Field(default="schedule", description="Pipeline source to include (typically 'schedule' or 'push')."),
    ] = "schedule",
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Aggregate success rate over 7 and 30 days with a trend indicator.

    Great for stand-ups and on-call hand-offs: "How healthy is our nightly
    schedule on ``master``?". Returns success rate %, totals, last-10 statuses
    and a trend (``up``/``down``/``flat``).

    Examples:
        - "How stable is master" → default (``ref='master'``, ``source='schedule'``)
        - "Push-driven pipeline health" → ``source='push'``
        - Don't use for a single pipeline — use ``gitlab_get_pipeline``.
    """
    from gitlab_ci_mcp.pipeline_health import PipelineHealthCollector

    try:
        ci = _get_ci(project_path)
        report = PipelineHealthCollector(ci).collect(ref=ref, source=source)
        data = {
            "project": ci.project_path,
            "ref": ref,
            "source": source,
            "rate_7d": round(report.rate_7d, 1),
            "rate_30d": round(report.rate_30d, 1),
            "trend": report.trend,
            "total_7d": report.total_7d,
            "success_7d": report.success_7d,
            "failed_7d": report.failed_7d,
            "total_30d": report.total_30d,
            "success_30d": report.success_30d,
            "failed_30d": report.failed_30d,
            "last_10_statuses": report.last_10_statuses,
            "generated_at": report.generated_at,
        }
        return _render(data, response_format, formatters.pipeline_health)
    except Exception as exc:
        return errors.handle(exc, f"computing pipeline health for {ref}")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Schedules                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝


@mcp.tool(
    name="gitlab_list_schedules",
    annotations={
        "title": "List CI/CD Schedules",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_list_schedules(
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """List all CI/CD schedules of a project.

    Variables whose key contains ``TOKEN`` or ``PASSWORD`` are returned without
    their values as a safety measure.
    """
    try:
        ci = _get_ci(project_path)
        schedules = ci.list_schedules()
        data = {
            "project": ci.project_path,
            "schedules_count": len(schedules),
            "active_count": sum(1 for s in schedules if s.active),
            "schedules": [
                {
                    "id": s.id,
                    "description": s.description,
                    "cron": s.cron,
                    "cron_timezone": s.cron_timezone,
                    "ref": s.ref,
                    "active": s.active,
                    "next_run_at": s.next_run_at,
                    "variables": {
                        k: v
                        for k, v in s.variables.items()
                        if "TOKEN" not in k.upper() and "PASSWORD" not in k.upper()
                    },
                    "web_url": s.web_url,
                }
                for s in schedules
            ],
        }
        return _render(data, response_format, formatters.schedules_list)
    except Exception as exc:
        return errors.handle(exc, "listing schedules")


@mcp.tool(
    name="gitlab_create_schedule",
    annotations={
        "title": "Create CI/CD Schedule",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
def gitlab_create_schedule(
    description: Annotated[str, Field(description="Human-readable description.", min_length=1, max_length=255)],
    cron: Annotated[str, Field(description="Cron expression in 5 fields (e.g. '0 2 * * *').", min_length=5)],
    variables: Annotated[
        dict[str, str],
        Field(description="CI variables to attach to the schedule (key -> value)."),
    ],
    ref: Annotated[
        str, Field(default="master", description="Branch or tag to run.", min_length=1, max_length=255)
    ] = "master",
    timezone: Annotated[
        str,
        Field(default="UTC", description="IANA timezone for the cron (e.g. 'Europe/Berlin')."),
    ] = "UTC",
    active: Annotated[bool, Field(default=True, description="Activate the schedule immediately.")] = True,
    project_path: ProjectPath = None,
) -> str:
    """Create a new CI/CD schedule with the given cron and variables.

    **Not idempotent**: duplicate calls create duplicate schedules with
    auto-incrementing IDs.
    """
    try:
        ci = _get_ci(project_path)
        schedule_id = ci.create_schedule(
            description=description,
            cron=cron,
            variables=variables,
            ref=ref,
            timezone=timezone,
            active=active,
        )
        return _json(
            {
                "schedule_id": schedule_id,
                "description": description,
                "cron": cron,
                "ref": ref,
                "active": active,
                "status": "created",
            }
        )
    except Exception as exc:
        return errors.handle(exc, f"creating schedule '{description}'")


@mcp.tool(
    name="gitlab_update_schedule",
    annotations={
        "title": "Update CI/CD Schedule",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_update_schedule(
    schedule_id: Annotated[int, Field(description="Schedule ID to update.", gt=0)],
    description: Annotated[str | None, Field(default=None, description="New description.")] = None,
    cron: Annotated[str | None, Field(default=None, description="New cron expression.")] = None,
    ref: Annotated[str | None, Field(default=None, description="New ref (branch/tag).")] = None,
    active: Annotated[bool | None, Field(default=None, description="New active state.")] = None,
    variables: Annotated[
        dict[str, str] | None,
        Field(
            default=None,
            description=(
                "New variable set. If provided, **replaces all existing variables** — pre-existing "
                "ones are deleted first. Omit to leave variables untouched."
            ),
        ),
    ] = None,
    project_path: ProjectPath = None,
) -> str:
    """Update an existing schedule. Only provided fields change.

    Destructive when ``variables`` is set: the entire variable set is replaced,
    so ensure the caller sends a full list.
    """
    try:
        ci = _get_ci(project_path)
        ci.update_schedule(
            schedule_id=schedule_id,
            description=description,
            cron=cron,
            ref=ref,
            active=active,
            variables=variables,
        )
        return _json({"schedule_id": schedule_id, "status": "updated"})
    except Exception as exc:
        return errors.handle(exc, f"updating schedule {schedule_id}")


@mcp.tool(
    name="gitlab_delete_schedule",
    annotations={
        "title": "Delete CI/CD Schedule",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_delete_schedule(
    schedule_id: Annotated[int, Field(description="Schedule ID to delete.", gt=0)],
    project_path: ProjectPath = None,
) -> str:
    """Delete a schedule by ID. Cannot be undone."""
    try:
        ci = _get_ci(project_path)
        ci.delete_schedule(schedule_id)
        return _json({"schedule_id": schedule_id, "status": "deleted"})
    except Exception as exc:
        return errors.handle(exc, f"deleting schedule {schedule_id}")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Branches & tags                                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝


@mcp.tool(
    name="gitlab_list_branches",
    annotations={
        "title": "List Branches",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_list_branches(
    search: Annotated[
        str | None,
        Field(default=None, description="Substring match on branch name (case-insensitive).", max_length=255),
    ] = None,
    per_page: Annotated[int, Field(default=20, ge=1, le=100, description="Items per page (1–100).")] = 20,
    page: Annotated[int, Field(default=1, ge=1, description="1-based page number.")] = 1,
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """List branches of a project, optionally filtered by substring.

    Includes ``default``, ``protected`` and ``merged`` flags, and the short id
    of the tip commit with its title and date.

    Examples:
        - "List all branches with 'release' in name" → ``search='release'``
        - "Next page of branches" → ``page=2``
        - Don't use when you want to check if a specific branch exists by exact name —
          use ``gitlab_get_file`` on that ref and look at the error instead.
    """
    try:
        ci = _get_ci(project_path)
        kwargs: dict[str, Any] = {"per_page": per_page, "page": page, "get_all": False}
        if search:
            kwargs["search"] = search
        branches = ci.project.branches.list(**kwargs)
        data = {
            "project": ci.project_path,
            "count": len(branches),
            "pagination": pagination.extract(branches),
            "branches": [
                {
                    "name": b.name,
                    "merged": getattr(b, "merged", None),
                    "protected": getattr(b, "protected", None),
                    "default": getattr(b, "default", None),
                    "commit_short_id": b.commit["short_id"] if b.commit else None,
                    "commit_title": b.commit.get("title", "")[:80] if b.commit else None,
                    "committed_date": _ts(b.commit.get("committed_date")) if b.commit else None,
                }
                for b in branches
            ],
        }
        return _render(data, response_format, formatters.branches_list)
    except Exception as exc:
        return errors.handle(exc, "listing branches")


@mcp.tool(
    name="gitlab_list_tags",
    annotations={
        "title": "List Tags",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_list_tags(
    search: Annotated[
        str | None, Field(default=None, description="Substring match on tag name.", max_length=255)
    ] = None,
    per_page: Annotated[int, Field(default=20, ge=1, le=100, description="Items per page (1–100).")] = 20,
    page: Annotated[int, Field(default=1, ge=1, description="1-based page number.")] = 1,
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """List tags of a project, newest first.

    Useful for release-note generation or checking the last shipped version.

    Examples:
        - "What was the last release tag" → default call, take the first item
        - "All v2.x releases" → ``search='v2.'``
    """
    try:
        ci = _get_ci(project_path)
        kwargs: dict[str, Any] = {
            "per_page": per_page,
            "page": page,
            "order_by": "updated",
            "sort": "desc",
            "get_all": False,
        }
        if search:
            kwargs["search"] = search
        tags = ci.project.tags.list(**kwargs)
        data = {
            "project": ci.project_path,
            "count": len(tags),
            "pagination": pagination.extract(tags),
            "tags": [
                {
                    "name": t.name,
                    "message": getattr(t, "message", None),
                    "commit_short_id": t.commit["short_id"] if t.commit else None,
                    "committed_date": _ts(t.commit.get("committed_date")) if t.commit else None,
                }
                for t in tags
            ],
        }
        return _render(data, response_format, formatters.tags_list)
    except Exception as exc:
        return errors.handle(exc, "listing tags")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Merge requests                                                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝


MRState = Literal["opened", "closed", "merged", "locked", "all"]


@mcp.tool(
    name="gitlab_list_merge_requests",
    annotations={
        "title": "List Merge Requests",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_list_merge_requests(
    state: Annotated[MRState, Field(default="opened", description="Filter by MR state.")] = "opened",
    per_page: Annotated[int, Field(default=20, ge=1, le=100, description="Items per page (1–100).")] = 20,
    page: Annotated[int, Field(default=1, ge=1, description="1-based page number.")] = 1,
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """List merge requests of a project, optionally filtered by state.

    Examples:
        - "What MRs are open right now" → default (state='opened')
        - "What merged last week" → ``state='merged'`` then filter by ``updated_at`` client-side
        - "Everything regardless of state" → ``state='all'``
        - Don't use when you have an MR IID — use ``gitlab_get_merge_request`` for detail.
    """
    try:
        ci = _get_ci(project_path)
        mrs = ci.project.mergerequests.list(state=state, per_page=per_page, page=page, get_all=False)
        data = {
            "project": ci.project_path,
            "state": state,
            "count": len(mrs),
            "pagination": pagination.extract(mrs),
            "merge_requests": [
                {
                    "iid": mr.iid,
                    "title": mr.title,
                    "state": mr.state,
                    "source_branch": mr.source_branch,
                    "target_branch": mr.target_branch,
                    "author": mr.author.get("username") if mr.author else None,
                    "merge_status": getattr(mr, "merge_status", None),
                    "created_at": _ts(mr.created_at),
                    "updated_at": _ts(getattr(mr, "updated_at", None)),
                    "web_url": mr.web_url,
                }
                for mr in mrs
            ],
        }
        return _render(data, response_format, formatters.mrs_list)
    except Exception as exc:
        return errors.handle(exc, f"listing merge requests (state={state})")


@mcp.tool(
    name="gitlab_get_merge_request",
    annotations={
        "title": "Get Merge Request",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_get_merge_request(
    mr_iid: Annotated[
        int, Field(description="Merge request IID (project-local number shown as '!42').", gt=0)
    ],
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Get full information about a merge request by internal ID (``iid``).

    Includes state, branches, author, assignees, reviewers, labels, conflict
    status, description and timestamps.
    """
    try:
        ci = _get_ci(project_path)
        mr = ci.project.mergerequests.get(mr_iid)
        data = {
            "iid": mr.iid,
            "title": mr.title,
            "description": mr.description,
            "state": mr.state,
            "source_branch": mr.source_branch,
            "target_branch": mr.target_branch,
            "author": mr.author.get("username") if mr.author else None,
            "assignees": [a.get("username") for a in (getattr(mr, "assignees", None) or [])],
            "reviewers": [r.get("username") for r in (getattr(mr, "reviewers", None) or [])],
            "labels": getattr(mr, "labels", []),
            "merge_status": getattr(mr, "merge_status", None),
            "has_conflicts": getattr(mr, "has_conflicts", None),
            "changes_count": getattr(mr, "changes_count", None),
            "created_at": _ts(mr.created_at),
            "updated_at": _ts(getattr(mr, "updated_at", None)),
            "merged_at": _ts(getattr(mr, "merged_at", None)),
            "web_url": mr.web_url,
        }
        return _render(data, response_format, formatters.mr_detail)
    except Exception as exc:
        return errors.handle(exc, f"getting MR !{mr_iid}")


@mcp.tool(
    name="gitlab_get_merge_request_changes",
    annotations={
        "title": "Get Merge Request Changes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_get_merge_request_changes(
    mr_iid: Annotated[int, Field(description="Merge request IID.", gt=0)],
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """List changed files in a merge request with truncated diffs (2KB per file).

    Useful for code-review-style queries ("what changed in !42?"). Diffs beyond
    2KB are truncated — fetch the raw file via ``gitlab_get_file`` for full
    content.
    """
    try:
        ci = _get_ci(project_path)
        mr = ci.project.mergerequests.get(mr_iid)
        changes = mr.changes()
        files = [
            {
                "old_path": change.get("old_path"),
                "new_path": change.get("new_path"),
                "new_file": change.get("new_file"),
                "renamed_file": change.get("renamed_file"),
                "deleted_file": change.get("deleted_file"),
                "diff": change.get("diff", "")[:2000],
            }
            for change in changes.get("changes", [])
        ]
        data = {
            "mr_iid": mr_iid,
            "title": changes.get("title"),
            "files_count": len(files),
            "files": files,
        }
        return _render(data, response_format, formatters.mr_changes)
    except Exception as exc:
        return errors.handle(exc, f"getting changes of MR !{mr_iid}")


@mcp.tool(
    name="gitlab_create_merge_request",
    annotations={
        "title": "Create Merge Request",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
def gitlab_create_merge_request(
    source_branch: Annotated[str, Field(description="Source branch.", min_length=1, max_length=255)],
    target_branch: Annotated[
        str, Field(default="master", description="Target branch (default 'master').", min_length=1, max_length=255)
    ] = "master",
    title: Annotated[
        str | None, Field(default=None, description="MR title. Auto-generated if omitted.", max_length=255)
    ] = None,
    description: Annotated[str | None, Field(default=None, description="MR description (markdown supported).")] = None,
    labels: Annotated[list[str] | None, Field(default=None, description="Labels to apply.")] = None,
    remove_source_branch: Annotated[
        bool, Field(default=True, description="Delete source branch after merge.")
    ] = True,
    project_path: ProjectPath = None,
) -> str:
    """Create a merge request from ``source_branch`` into ``target_branch``.

    **Not idempotent**: creates a new MR each call. Check existing MRs first
    via ``gitlab_list_merge_requests`` if you want to avoid duplicates.
    """
    try:
        ci = _get_ci(project_path)
        mr_data: dict[str, Any] = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title or f"Merge {source_branch} into {target_branch}",
            "remove_source_branch": remove_source_branch,
        }
        if description:
            mr_data["description"] = description
        if labels:
            mr_data["labels"] = labels

        mr = ci.project.mergerequests.create(mr_data)
        return _json(
            {
                "iid": mr.iid,
                "title": mr.title,
                "state": mr.state,
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
                "merge_status": getattr(mr, "merge_status", None),
                "web_url": mr.web_url,
                "status": "created",
            }
        )
    except Exception as exc:
        return errors.handle(exc, f"creating MR from {source_branch} into {target_branch}")


@mcp.tool(
    name="gitlab_merge_mr",
    annotations={
        "title": "Merge an MR",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_merge_mr(
    mr_iid: Annotated[int, Field(description="Merge request IID to merge.", gt=0)],
    project_path: ProjectPath = None,
) -> str:
    """Perform the actual merge if GitLab reports the MR can be merged.

    **Destructive**: writes to the target branch. Checks ``merge_status`` first
    and returns ``status='cannot_merge'`` if conflicts exist or pipelines are
    required.

    Examples:
        - "Merge !42" → ``mr_iid=42``
        - Don't call without checking ``gitlab_get_merge_request`` first when you suspect conflicts.
    """
    try:
        ci = _get_ci(project_path)
        mr = ci.project.mergerequests.get(mr_iid)
        if getattr(mr, "merge_status", "") != "can_be_merged":
            return _json(
                {
                    "iid": mr.iid,
                    "merge_status": getattr(mr, "merge_status", None),
                    "has_conflicts": getattr(mr, "has_conflicts", None),
                    "status": "cannot_merge",
                    "web_url": mr.web_url,
                    "hint": (
                        "Resolve conflicts, wait for required pipelines to pass, or approve "
                        "according to project merge rules, then call again."
                    ),
                }
            )
        mr.merge()
        return _json({"iid": mr.iid, "status": "merged", "web_url": mr.web_url})
    except Exception as exc:
        return errors.handle(exc, f"merging MR !{mr_iid}")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Repository files & tree                                                  ║
# ╚══════════════════════════════════════════════════════════════════════════╝


@mcp.tool(
    name="gitlab_get_file",
    annotations={
        "title": "Get Repository File",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_get_file(
    file_path: Annotated[
        str,
        Field(description="Path to the file from the repo root (e.g. 'src/app.py').", min_length=1, max_length=1024),
    ],
    ref: Annotated[
        str, Field(default="master", description="Branch, tag or commit SHA.", min_length=1, max_length=255)
    ] = "master",
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Read a text file from the repository, truncated to 500 lines.

    For binaries, gets decoded as UTF-8 with errors replaced — you will likely
    get garbage; use for text content only.

    Examples:
        - "Show me .gitlab-ci.yml on master" → ``file_path='.gitlab-ci.yml'``
        - "Read src/app.py from the release-1.2 tag" → ``file_path='src/app.py'``, ``ref='release-1.2'``
        - Don't use for listings — use ``gitlab_list_repository_tree``.
    """
    try:
        ci = _get_ci(project_path)
        f = ci.project.files.get(file_path=file_path, ref=ref)
        content = f.decode().decode("utf-8", errors="replace")
        lines = content.splitlines()
        truncated = len(lines) > 500
        if truncated:
            content = "\n".join(lines[:500])
        data = {
            "file_path": file_path,
            "ref": ref,
            "size": f.size,
            "total_lines": len(lines),
            "truncated": truncated,
            "content": content,
        }
        return _render(data, response_format, formatters.file_content)
    except Exception as exc:
        return errors.handle(exc, f"getting file {file_path}@{ref}")


@mcp.tool(
    name="gitlab_list_repository_tree",
    annotations={
        "title": "List Repository Tree",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_list_repository_tree(
    path: Annotated[str, Field(default="", description="Directory path (empty for root).", max_length=1024)] = "",
    ref: Annotated[
        str, Field(default="master", description="Branch, tag or SHA.", min_length=1, max_length=255)
    ] = "master",
    recursive: Annotated[bool, Field(default=False, description="Recurse into subdirectories.")] = False,
    per_page: Annotated[int, Field(default=50, ge=1, le=100, description="Items per page (1–100).")] = 50,
    page: Annotated[int, Field(default=1, ge=1, description="1-based page number.")] = 1,
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """List files and directories at a given path in the repository.

    Examples:
        - "Show top-level files" → default call
        - "All .py files recursively" → ``recursive=True`` then filter on ``.py`` in path
        - Don't use for full-text content — use ``gitlab_get_file`` for that.
    """
    try:
        ci = _get_ci(project_path)
        items = ci.project.repository_tree(
            path=path, ref=ref, recursive=recursive, per_page=per_page, page=page, get_all=False
        )
        data = {
            "project": ci.project_path,
            "path": path or "/",
            "ref": ref,
            "count": len(items),
            "pagination": pagination.extract(items),
            "items": [{"name": item["name"], "type": item["type"], "path": item["path"]} for item in items],
        }
        return _render(data, response_format, formatters.repo_tree)
    except Exception as exc:
        return errors.handle(exc, f"listing tree {path or '/'}@{ref}")


@mcp.tool(
    name="gitlab_compare_branches",
    annotations={
        "title": "Compare Branches",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_compare_branches(
    source: Annotated[str, Field(description="Source branch/tag/SHA.", min_length=1, max_length=255)],
    target: Annotated[
        str, Field(default="master", description="Target branch (default 'master').", min_length=1, max_length=255)
    ] = "master",
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Compare two branches — returns up to 30 commits and the list of changed files.

    Use for "what's in ``release/x.y`` vs ``master``?" or for release-note drafting.

    Examples:
        - "What's new in release/1.5 vs master" → ``source='release/1.5'``, ``target='master'``
        - Don't use to fetch full diffs of an MR — use ``gitlab_get_merge_request_changes``.
    """
    try:
        ci = _get_ci(project_path)
        comparison = ci.project.repository_compare(source, target)
        commits = comparison.get("commits", [])
        diffs = comparison.get("diffs", [])
        data = {
            "source": source,
            "target": target,
            "commits_count": len(commits),
            "diffs_count": len(diffs),
            "commits": [
                {
                    "short_id": c.get("short_id"),
                    "title": c.get("title", "")[:120],
                    "author_name": c.get("author_name"),
                    "created_at": _ts(c.get("created_at")),
                }
                for c in commits[:30]
            ],
            "changed_files": [
                {
                    "old_path": d.get("old_path"),
                    "new_path": d.get("new_path"),
                    "new_file": d.get("new_file"),
                    "deleted_file": d.get("deleted_file"),
                }
                for d in diffs
            ],
        }
        return _render(data, response_format, formatters.compare)
    except Exception as exc:
        return errors.handle(exc, f"comparing {source} with {target}")


@mcp.tool(
    name="gitlab_project_info",
    annotations={
        "title": "Get Project Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def gitlab_project_info(
    project_path: ProjectPath = None,
    response_format: ResponseFormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Return basic metadata about a project: ID, default branch, visibility, counts."""
    try:
        ci = _get_ci(project_path)
        p = ci.project
        data = {
            "id": p.id,
            "name": p.name,
            "path_with_namespace": p.path_with_namespace,
            "default_branch": p.default_branch,
            "web_url": p.web_url,
            "visibility": getattr(p, "visibility", None),
            "created_at": _ts(getattr(p, "created_at", None)),
            "last_activity_at": _ts(getattr(p, "last_activity_at", None)),
            "open_issues_count": getattr(p, "open_issues_count", None),
            "forks_count": getattr(p, "forks_count", None),
            "star_count": getattr(p, "star_count", None),
        }
        return _render(data, response_format, formatters.project_info)
    except Exception as exc:
        return errors.handle(exc, "getting project info")


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the ``gitlab-ci-mcp`` console script (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
