"""Pipeline, job, and health tools."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from mcp.types import CallToolResult
from pydantic import Field

from gitlab_ci_mcp import formatters, output, pagination
from gitlab_ci_mcp._mcp import ProjectPath, get_ci, mcp, ts
from gitlab_ci_mcp.models import (
    HealthOutput,
    JobLogOutput,
    JobsListOutput,
    PipelineActionResult,
    PipelineDetailOutput,
    PipelinesListOutput,
    PipelineSummary,
)

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
    structured_output=True,
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
    per_page: Annotated[int, Field(default=20, ge=1, le=100, description="Items per page (1–100).")] = 20,
    page: Annotated[int, Field(default=1, ge=1, description="1-based page number.")] = 1,
    project_path: ProjectPath = None,
) -> PipelinesListOutput:
    """List recent pipelines of a project, newest first.

    Use for triage ("show failed pipelines on master"), release readiness checks,
    or feeding pipeline IDs into follow-up calls. Read-only and idempotent.

    Returns ``PipelinesListOutput``: ``project``, ``count``, ``pagination`` and
    ``pipelines[]`` (each ``PipelineSummary``). The tool result additionally
    carries a markdown table in its text content.

    Examples:
        - "Show failed pipelines on master" → ``status='failed'``, ``ref='master'``
        - "Last nightly schedule runs" → ``source='schedule'``
        - "Second page of pipelines" → ``page=2``
        - Don't use when you have a specific pipeline ID — use ``gitlab_get_pipeline`` instead.
    """
    try:
        ci = get_ci(project_path)
        kwargs: dict[str, Any] = {"per_page": per_page, "page": page, "get_all": False}
        if ref:
            kwargs["ref"] = ref
        if status:
            kwargs["status"] = status
        if source:
            kwargs["source"] = source
        pipelines = ci.project.pipelines.list(**kwargs)
        summaries: list[PipelineSummary] = [
            {
                "id": p.id,
                "status": p.status,
                "ref": p.ref,
                "source": getattr(p, "source", None),
                "created_at": ts(p.created_at),
                "duration": getattr(p, "duration", None),
                "web_url": p.web_url,
            }
            for p in pipelines
        ]
        data: PipelinesListOutput = {
            "project": ci.project_path,
            "count": len(pipelines),
            "pagination": pagination.extract(pipelines),
            "pipelines": summaries,
        }
        return output.ok(data, formatters.pipelines_list(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, "listing pipelines")


@mcp.tool(
    name="gitlab_get_pipeline",
    annotations={
        "title": "Get GitLab Pipeline",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_get_pipeline(
    pipeline_id: Annotated[int, Field(description="Numeric pipeline ID (not ``iid``).", gt=0)],
    project_path: ProjectPath = None,
) -> PipelineDetailOutput:
    """Get a single pipeline with full timing details.

    Useful right after ``gitlab_list_pipelines`` — lists only return summaries.
    Returns status, ref, source, durations (queued/total), and started/finished timestamps.

    Examples:
        - "Why was pipeline 123 slow" → check ``queued_duration`` and ``duration`` fields
        - "Is pipeline 456 still running" → look at ``status``
        - Don't use to see individual jobs — use ``gitlab_get_pipeline_jobs``.
    """
    try:
        ci = get_ci(project_path)
        p = ci.project.pipelines.get(pipeline_id)
        data: PipelineDetailOutput = {
            "id": p.id,
            "status": p.status,
            "ref": p.ref,
            "source": getattr(p, "source", None),
            "created_at": ts(p.created_at),
            "updated_at": ts(getattr(p, "updated_at", None)),
            "started_at": ts(getattr(p, "started_at", None)),
            "finished_at": ts(getattr(p, "finished_at", None)),
            "duration": getattr(p, "duration", None),
            "queued_duration": getattr(p, "queued_duration", None),
            "web_url": p.web_url,
        }
        return output.ok(data, formatters.pipeline_detail(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"getting pipeline {pipeline_id}")


@mcp.tool(
    name="gitlab_get_pipeline_jobs",
    annotations={
        "title": "List Pipeline Jobs",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_get_pipeline_jobs(
    pipeline_id: Annotated[int, Field(description="Numeric pipeline ID.", gt=0)],
    project_path: ProjectPath = None,
) -> JobsListOutput:
    """List jobs of a pipeline with stage, status, duration and web URL.

    Use after noticing a failed pipeline to drill down into which specific job
    broke and fetch its log via ``gitlab_get_job_log``.

    Examples:
        - "What jobs are in pipeline 123" → ``pipeline_id=123``
        - "Which job failed in pipeline 456" → filter result by ``status='failed'`` client-side
        - Don't use for overall pipeline status — use ``gitlab_get_pipeline`` instead.
    """
    try:
        ci = get_ci(project_path)
        jobs = ci.get_pipeline_jobs(pipeline_id)
        data: JobsListOutput = {"pipeline_id": pipeline_id, "jobs_count": len(jobs), "jobs": jobs}
        return output.ok(data, formatters.pipeline_jobs(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing jobs of pipeline {pipeline_id}")


@mcp.tool(
    name="gitlab_get_job_log",
    annotations={
        "title": "Get Job Log",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
async def gitlab_get_job_log(
    job_id: Annotated[int, Field(description="Numeric job ID (from ``gitlab_get_pipeline_jobs``).", gt=0)],
    tail: Annotated[
        int,
        Field(default=100, ge=1, le=5000, description="Return only the last N lines (1–5000, default 100)."),
    ] = 100,
    grep_pattern: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional regex — when set, returns only lines matching the pattern (with ``grep_context`` "
                "surrounding lines) instead of the tail. Great for finding errors in huge logs without "
                "downloading everything. Invalid regex falls back to literal substring match."
            ),
            max_length=500,
        ),
    ] = None,
    grep_context: Annotated[
        int,
        Field(default=3, ge=0, le=20, description="Surrounding lines to include around each grep match (0–20)."),
    ] = 3,
    project_path: ProjectPath = None,
    ctx: Context | None = None,
) -> JobLogOutput:
    """Fetch the trace/log of a job, with optional regex filter.

    Two modes:

    * Default: return the last ``tail`` lines (token-efficient, good for
      "why did this just fail?").
    * With ``grep_pattern``: return only matching lines with
      ``grep_context`` surrounding lines on each side — ideal for finding
      "ERROR" / "Traceback" in megabyte-scale CI logs without pulling the
      whole trace into context.

    Examples:
        - "Why did job 789 fail" → default tail=100, look at the end of the log
        - "Show me the first stage output of job 789" → ``tail=5000`` and scan for stage separator
        - "Find every Traceback in job 789" → ``grep_pattern='Traceback'``, ``grep_context=5``
        - "All ERROR lines from job 789" → ``grep_pattern='ERROR|FAIL'``
    """
    try:
        if ctx:
            hint = f"grep={grep_pattern!r}" if grep_pattern else f"tail={tail}"
            await ctx.info(f"Fetching log of job {job_id} ({hint})")
        ci = await asyncio.to_thread(get_ci, project_path)
        log = await asyncio.to_thread(ci.get_job_log, job_id)
        lines = log.splitlines()
        total = len(lines)

        matched_count: int | None = None
        if grep_pattern:
            try:
                regex = re.compile(grep_pattern)
                matches = [i for i, line in enumerate(lines) if regex.search(line)]
            except re.error:
                needle = grep_pattern
                matches = [i for i, line in enumerate(lines) if needle in line]
            matched_count = len(matches)
            keep: set[int] = set()
            for i in matches:
                for j in range(max(0, i - grep_context), min(total, i + grep_context + 1)):
                    keep.add(j)
            lines = [lines[i] for i in sorted(keep)]
        elif tail and tail < total:
            lines = lines[-tail:]

        data: JobLogOutput = {
            "job_id": job_id,
            "total_lines": total,
            "showing_last": len(lines),
            "log": "\n".join(lines),
        }
        if grep_pattern:
            data["grep_pattern"] = grep_pattern
            data["grep_matches"] = matched_count or 0
        return output.ok(data, formatters.job_log(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"getting log of job {job_id}")


@mcp.tool(
    name="gitlab_trigger_pipeline",
    annotations={
        "title": "Trigger Pipeline",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    structured_output=True,
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
) -> PipelineActionResult:
    """Create a new pipeline on the given ref, optionally with CI variables.

    **Not idempotent**: each call creates a new pipeline. Consumes minutes on
    your runners — avoid calling in loops.

    Examples:
        - "Run the pipeline on master" → default (``ref='master'``)
        - "Run the pipeline on feature/x with DEBUG=1" → ``ref='feature/x'``, ``variables={'DEBUG': '1'}``
        - Don't call to retry — use ``gitlab_retry_pipeline`` which keeps the same pipeline ID.
    """
    try:
        ci = get_ci(project_path)
        result = ci.trigger_pipeline(ref=ref, variables=variables)
        data: PipelineActionResult = {
            "pipeline_id": result.pipeline_id,
            "status": result.status,
            "ref": result.ref,
            "web_url": result.web_url,
            "created_at": result.created_at,
            "status_note": "pipeline created — poll gitlab_get_pipeline for progress",
        }
        md = f"✔ Pipeline [{data['pipeline_id']}]({data['web_url']}) created on `{data['ref']}` — {data['status']}"
        return output.ok(data, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"triggering pipeline on {ref}")


@mcp.tool(
    name="gitlab_retry_pipeline",
    annotations={
        "title": "Retry Failed Jobs of Pipeline",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_retry_pipeline(
    pipeline_id: Annotated[int, Field(description="Pipeline ID to retry failed jobs for.", gt=0)],
    project_path: ProjectPath = None,
) -> PipelineActionResult:
    """Retry all failed jobs of an existing pipeline.

    Creates new job runs (new history entries). Safe to call when the pipeline
    has at least one failed/canceled job; has no effect if everything already
    passed.

    Examples:
        - "Retry the failed jobs in pipeline 123" → ``pipeline_id=123``
        - Don't use to rerun a successful pipeline — use ``gitlab_trigger_pipeline`` instead.
    """
    try:
        ci = get_ci(project_path)
        pipeline = ci.project.pipelines.get(pipeline_id)
        pipeline.retry()
        pipeline.refresh()
        data: PipelineActionResult = {
            "pipeline_id": pipeline.id,
            "status": pipeline.status,
            "web_url": pipeline.web_url,
        }
        md = f"↻ Pipeline [{pipeline.id}]({pipeline.web_url}) retried — {pipeline.status}"
        return output.ok(data, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"retrying pipeline {pipeline_id}")


@mcp.tool(
    name="gitlab_cancel_pipeline",
    annotations={
        "title": "Cancel Running Pipeline",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_cancel_pipeline(
    pipeline_id: Annotated[int, Field(description="Pipeline ID to cancel.", gt=0)],
    project_path: ProjectPath = None,
) -> PipelineActionResult:
    """Cancel a running pipeline. In-flight jobs will be interrupted.

    Destructive for *in-progress* work. Cancelling an already-finished pipeline
    is a no-op.

    Examples:
        - "Pipeline 123 is stuck, cancel it" → ``pipeline_id=123``
        - Don't use on finished pipelines — no effect; use ``gitlab_retry_pipeline``
          if you want to rerun it.
    """
    try:
        ci = get_ci(project_path)
        pipeline = ci.project.pipelines.get(pipeline_id)
        pipeline.cancel()
        pipeline.refresh()
        data: PipelineActionResult = {
            "pipeline_id": pipeline.id,
            "status": pipeline.status,
            "web_url": pipeline.web_url,
        }
        md = f"✘ Pipeline [{pipeline.id}]({pipeline.web_url}) cancelled — {pipeline.status}"
        return output.ok(data, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"cancelling pipeline {pipeline_id}")


@mcp.tool(
    name="gitlab_pipeline_health",
    annotations={
        "title": "Pipeline Health Report",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
async def gitlab_pipeline_health(
    ref: Annotated[
        str, Field(default="master", description="Branch to analyse.", min_length=1, max_length=255)
    ] = "master",
    source: Annotated[
        PipelineSource,
        Field(default="schedule", description="Pipeline source to include (typically 'schedule' or 'push')."),
    ] = "schedule",
    project_path: ProjectPath = None,
    ctx: Context | None = None,
) -> HealthOutput:
    """Aggregate success rate over 7 and 30 days with a trend indicator.

    Great for stand-ups and on-call hand-offs. Returns success rate %, totals,
    last-10 statuses and a trend (``up``/``down``/``flat``).

    Emits progress via the MCP Context (``info`` log + ``report_progress``) —
    useful in IDEs that show per-tool progress bars.

    Examples:
        - "How stable is master" → default (``ref='master'``, ``source='schedule'``)
        - "Push-driven pipeline health" → ``source='push'``
        - Don't use for a single pipeline — use ``gitlab_get_pipeline``.
    """
    from gitlab_ci_mcp.pipeline_health import PipelineHealthCollector

    try:
        if ctx:
            await ctx.info(f"Fetching 30 days of '{source}' pipelines on {ref}")
            await ctx.report_progress(0.1, total=1.0, message="connecting")
        ci = await asyncio.to_thread(get_ci, project_path)
        if ctx:
            await ctx.report_progress(0.3, total=1.0, message="loading pipelines")
        report = await asyncio.to_thread(PipelineHealthCollector(ci).collect, ref, source)
        if ctx:
            await ctx.report_progress(1.0, total=1.0, message="done")
        data: HealthOutput = {
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
        return output.ok(data, formatters.pipeline_health(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"computing pipeline health for {ref}")


# Re-export CallToolResult so tests and callers can ``isinstance``-check.
__all__ = ["CallToolResult"]
