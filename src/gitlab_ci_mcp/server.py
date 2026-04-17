"""FastMCP server exposing GitLab CI/CD operations as MCP tools."""

from __future__ import annotations

import logging
import warnings
from typing import Any

import urllib3
from mcp.server.fastmcp import FastMCP

from gitlab_ci_mcp.ci_manager import GitLabCIManager

warnings.filterwarnings("ignore")
urllib3.disable_warnings()

logger = logging.getLogger(__name__)

mcp = FastMCP("gitlab")

_managers: dict[str, GitLabCIManager] = {}


def _get_ci(project_path: str | None = None) -> GitLabCIManager:
    """Get or create a ``GitLabCIManager`` for the given project path.

    When ``project_path`` is ``None`` the default from env (``GITLAB_PROJECT_PATH``)
    is used. Managers are cached per project path so repeated calls reuse the
    same python-gitlab connection.
    """
    if project_path is None:
        # use default manager (configured from env)
        project_path = ""  # cache key for default
    if project_path not in _managers:
        _managers[project_path] = GitLabCIManager(project_path=project_path or None)
    return _managers[project_path]


def _ts(dt_str: str | None) -> str | None:
    if not dt_str:
        return None
    return dt_str[:19].replace("T", " ")


# ─── Pipelines ───


@mcp.tool()
def gitlab_list_pipelines(
    ref: str | None = None,
    status: str | None = None,
    source: str | None = None,
    per_page: int = 20,
    project_path: str | None = None,
) -> dict[str, Any]:
    """List recent pipelines of a project.

    Args:
        ref: Filter by branch/tag (e.g. ``master``).
        status: Filter by status (``running``, ``pending``, ``success``, ``failed``, ``canceled``).
        source: Filter by source (``push``, ``schedule``, ``web``, ``trigger``, ``api``).
        per_page: Number of results (default 20, max 100).
        project_path: GitLab project path. If ``None``, uses ``GITLAB_PROJECT_PATH`` env.
    """
    ci = _get_ci(project_path)
    kwargs: dict[str, Any] = {"per_page": min(per_page, 100)}
    if ref:
        kwargs["ref"] = ref
    if status:
        kwargs["status"] = status
    if source:
        kwargs["source"] = source

    pipelines = ci.project.pipelines.list(**kwargs)

    return {
        "project": ci.project_path,
        "count": len(pipelines),
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


@mcp.tool()
def gitlab_get_pipeline(pipeline_id: int, project_path: str | None = None) -> dict[str, Any]:
    """Get detailed info about a single pipeline."""
    ci = _get_ci(project_path)
    p = ci.project.pipelines.get(pipeline_id)
    return {
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


@mcp.tool()
def gitlab_get_pipeline_jobs(pipeline_id: int, project_path: str | None = None) -> dict[str, Any]:
    """List jobs of a pipeline."""
    ci = _get_ci(project_path)
    jobs = ci.get_pipeline_jobs(pipeline_id)
    return {"pipeline_id": pipeline_id, "jobs_count": len(jobs), "jobs": jobs}


@mcp.tool()
def gitlab_get_job_log(job_id: int, tail: int = 100, project_path: str | None = None) -> dict[str, Any]:
    """Get job trace / log, last ``tail`` lines."""
    ci = _get_ci(project_path)
    log = ci.get_job_log(job_id)
    lines = log.splitlines()
    total = len(lines)
    if tail and tail < total:
        lines = lines[-tail:]
    return {
        "job_id": job_id,
        "total_lines": total,
        "showing_last": len(lines),
        "log": "\n".join(lines),
    }


@mcp.tool()
def gitlab_trigger_pipeline(
    ref: str = "master",
    variables: dict[str, str] | None = None,
    project_path: str | None = None,
) -> dict[str, Any]:
    """Trigger a new pipeline with optional CI variables."""
    ci = _get_ci(project_path)
    result = ci.trigger_pipeline(ref=ref, variables=variables)
    return {
        "pipeline_id": result.pipeline_id,
        "status": result.status,
        "ref": result.ref,
        "web_url": result.web_url,
        "created_at": result.created_at,
    }


@mcp.tool()
def gitlab_retry_pipeline(pipeline_id: int, project_path: str | None = None) -> dict[str, Any]:
    """Retry all failed jobs of a pipeline."""
    ci = _get_ci(project_path)
    pipeline = ci.project.pipelines.get(pipeline_id)
    pipeline.retry()
    pipeline.refresh()
    return {"pipeline_id": pipeline.id, "status": pipeline.status, "web_url": pipeline.web_url}


@mcp.tool()
def gitlab_cancel_pipeline(pipeline_id: int, project_path: str | None = None) -> dict[str, Any]:
    """Cancel a running pipeline."""
    ci = _get_ci(project_path)
    pipeline = ci.project.pipelines.get(pipeline_id)
    pipeline.cancel()
    pipeline.refresh()
    return {"pipeline_id": pipeline.id, "status": pipeline.status, "web_url": pipeline.web_url}


# ─── Pipeline Health ───


@mcp.tool()
def gitlab_pipeline_health(
    ref: str = "master",
    source: str = "schedule",
    project_path: str | None = None,
) -> dict[str, Any]:
    """Pipeline health report: success rate for 7/30 days, trend, last 10 statuses."""
    from gitlab_ci_mcp.pipeline_health import PipelineHealthCollector

    ci = _get_ci(project_path)
    report = PipelineHealthCollector(ci).collect(ref=ref, source=source)
    return {
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


# ─── Schedules ───


@mcp.tool()
def gitlab_list_schedules(project_path: str | None = None) -> dict[str, Any]:
    """List all CI/CD schedules of a project."""
    ci = _get_ci(project_path)
    schedules = ci.list_schedules()
    return {
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
                "variables": {k: v for k, v in s.variables.items() if "TOKEN" not in k and "PASSWORD" not in k},
                "web_url": s.web_url,
            }
            for s in schedules
        ],
    }


@mcp.tool()
def gitlab_create_schedule(
    description: str,
    cron: str,
    variables: dict[str, str],
    ref: str = "master",
    timezone: str = "UTC",
    active: bool = True,
    project_path: str | None = None,
) -> dict[str, Any]:
    """Create a new CI/CD schedule."""
    ci = _get_ci(project_path)
    schedule_id = ci.create_schedule(
        description=description,
        cron=cron,
        variables=variables,
        ref=ref,
        timezone=timezone,
        active=active,
    )
    return {
        "schedule_id": schedule_id,
        "description": description,
        "cron": cron,
        "ref": ref,
        "active": active,
        "status": "created",
    }


@mcp.tool()
def gitlab_update_schedule(
    schedule_id: int,
    description: str | None = None,
    cron: str | None = None,
    ref: str | None = None,
    active: bool | None = None,
    variables: dict[str, str] | None = None,
    project_path: str | None = None,
) -> dict[str, Any]:
    """Update an existing schedule (only passed fields are changed)."""
    ci = _get_ci(project_path)
    ci.update_schedule(
        schedule_id=schedule_id,
        description=description,
        cron=cron,
        ref=ref,
        active=active,
        variables=variables,
    )
    return {"schedule_id": schedule_id, "status": "updated"}


@mcp.tool()
def gitlab_delete_schedule(schedule_id: int, project_path: str | None = None) -> dict[str, Any]:
    """Delete a schedule by ID."""
    ci = _get_ci(project_path)
    ci.delete_schedule(schedule_id)
    return {"schedule_id": schedule_id, "status": "deleted"}


# ─── Branches & Tags ───


@mcp.tool()
def gitlab_list_branches(
    search: str | None = None,
    per_page: int = 20,
    project_path: str | None = None,
) -> dict[str, Any]:
    """List project branches."""
    ci = _get_ci(project_path)
    kwargs: dict[str, Any] = {"per_page": min(per_page, 100)}
    if search:
        kwargs["search"] = search
    branches = ci.project.branches.list(**kwargs)
    return {
        "project": ci.project_path,
        "count": len(branches),
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


@mcp.tool()
def gitlab_list_tags(
    search: str | None = None,
    per_page: int = 20,
    project_path: str | None = None,
) -> dict[str, Any]:
    """List project tags (newest first)."""
    ci = _get_ci(project_path)
    kwargs: dict[str, Any] = {"per_page": min(per_page, 100), "order_by": "updated", "sort": "desc"}
    if search:
        kwargs["search"] = search
    tags = ci.project.tags.list(**kwargs)
    return {
        "project": ci.project_path,
        "count": len(tags),
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


# ─── Merge Requests ───


@mcp.tool()
def gitlab_list_merge_requests(
    state: str = "opened",
    per_page: int = 20,
    project_path: str | None = None,
) -> dict[str, Any]:
    """List merge requests.

    Args:
        state: ``opened``, ``closed``, ``merged`` or ``all``.
    """
    ci = _get_ci(project_path)
    mrs = ci.project.mergerequests.list(state=state, per_page=min(per_page, 100))
    return {
        "project": ci.project_path,
        "state": state,
        "count": len(mrs),
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


@mcp.tool()
def gitlab_get_merge_request(mr_iid: int, project_path: str | None = None) -> dict[str, Any]:
    """Get full info of a merge request by internal ID (``iid``)."""
    ci = _get_ci(project_path)
    mr = ci.project.mergerequests.get(mr_iid)
    return {
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


@mcp.tool()
def gitlab_get_merge_request_changes(mr_iid: int, project_path: str | None = None) -> dict[str, Any]:
    """List changed files with truncated diffs of an MR."""
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
    return {
        "mr_iid": mr_iid,
        "title": changes.get("title"),
        "files_count": len(files),
        "files": files,
    }


@mcp.tool()
def gitlab_create_merge_request(
    source_branch: str,
    target_branch: str = "master",
    title: str | None = None,
    description: str | None = None,
    labels: list[str] | None = None,
    remove_source_branch: bool = True,
    project_path: str | None = None,
) -> dict[str, Any]:
    """Create a merge request."""
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
    return {
        "iid": mr.iid,
        "title": mr.title,
        "state": mr.state,
        "source_branch": mr.source_branch,
        "target_branch": mr.target_branch,
        "merge_status": getattr(mr, "merge_status", None),
        "web_url": mr.web_url,
        "status": "created",
    }


@mcp.tool()
def gitlab_merge_mr(mr_iid: int, project_path: str | None = None) -> dict[str, Any]:
    """Merge an MR if GitLab reports it can be merged."""
    ci = _get_ci(project_path)
    mr = ci.project.mergerequests.get(mr_iid)
    if getattr(mr, "merge_status", "") != "can_be_merged":
        return {
            "iid": mr.iid,
            "merge_status": getattr(mr, "merge_status", None),
            "has_conflicts": getattr(mr, "has_conflicts", None),
            "status": "cannot_merge",
            "web_url": mr.web_url,
        }
    mr.merge()
    return {"iid": mr.iid, "status": "merged", "web_url": mr.web_url}


# ─── Repository Files ───


@mcp.tool()
def gitlab_get_file(
    file_path: str,
    ref: str = "master",
    project_path: str | None = None,
) -> dict[str, Any]:
    """Get file contents from a repository. Truncates to 500 lines."""
    ci = _get_ci(project_path)
    try:
        f = ci.project.files.get(file_path=file_path, ref=ref)
        content = f.decode().decode("utf-8")
        lines = content.splitlines()
        truncated = len(lines) > 500
        if truncated:
            content = "\n".join(lines[:500])
        return {
            "file_path": file_path,
            "ref": ref,
            "size": f.size,
            "total_lines": len(lines),
            "truncated": truncated,
            "content": content,
        }
    except Exception as e:
        return {"file_path": file_path, "ref": ref, "error": str(e)}


@mcp.tool()
def gitlab_list_repository_tree(
    path: str = "",
    ref: str = "master",
    recursive: bool = False,
    per_page: int = 50,
    project_path: str | None = None,
) -> dict[str, Any]:
    """List files and directories in repository at a given path."""
    ci = _get_ci(project_path)
    items = ci.project.repository_tree(path=path, ref=ref, recursive=recursive, per_page=min(per_page, 100))
    return {
        "project": ci.project_path,
        "path": path or "/",
        "ref": ref,
        "count": len(items),
        "items": [{"name": item["name"], "type": item["type"], "path": item["path"]} for item in items],
    }


@mcp.tool()
def gitlab_compare_branches(
    source: str,
    target: str = "master",
    project_path: str | None = None,
) -> dict[str, Any]:
    """Compare two branches — returns commits and changed files."""
    ci = _get_ci(project_path)
    comparison = ci.project.repository_compare(source, target)
    commits = comparison.get("commits", [])
    diffs = comparison.get("diffs", [])
    return {
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


@mcp.tool()
def gitlab_project_info(project_path: str | None = None) -> dict[str, Any]:
    """Basic info about a project (ID, default branch, visibility, counts)."""
    ci = _get_ci(project_path)
    p = ci.project
    return {
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


def main() -> None:
    """Entry point for the ``gitlab-ci-mcp`` console script."""
    mcp.run()


if __name__ == "__main__":
    main()
