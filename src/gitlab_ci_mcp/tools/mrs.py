"""Merge request tools."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from gitlab_ci_mcp import formatters, output, pagination
from gitlab_ci_mcp._mcp import ProjectPath, get_ci, mcp, ts
from gitlab_ci_mcp.models import (
    FileChange,
    MRActionResult,
    MRChangesOutput,
    MRDetailOutput,
    MRsListOutput,
    MRSummary,
)

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
    structured_output=True,
)
def gitlab_list_merge_requests(
    state: Annotated[MRState, Field(default="opened", description="Filter by MR state.")] = "opened",
    per_page: Annotated[int, Field(default=20, ge=1, le=100, description="Items per page (1–100).")] = 20,
    page: Annotated[int, Field(default=1, ge=1, description="1-based page number.")] = 1,
    project_path: ProjectPath = None,
) -> MRsListOutput:
    """List merge requests of a project, optionally filtered by state.

    Examples:
        - "What MRs are open right now" → default (state='opened')
        - "What merged last week" → ``state='merged'`` then filter by ``updated_at`` client-side
        - "Everything regardless of state" → ``state='all'``
        - Don't use when you have an MR IID — use ``gitlab_get_merge_request`` for detail.
    """
    try:
        ci = get_ci(project_path)
        mrs = ci.project.mergerequests.list(state=state, per_page=per_page, page=page, get_all=False)
        summaries: list[MRSummary] = [
            {
                "iid": mr.iid,
                "title": mr.title,
                "state": mr.state,
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
                "author": mr.author.get("username") if mr.author else None,
                "merge_status": getattr(mr, "merge_status", None),
                "created_at": ts(mr.created_at),
                "updated_at": ts(getattr(mr, "updated_at", None)),
                "web_url": mr.web_url,
            }
            for mr in mrs
        ]
        data: MRsListOutput = {
            "project": ci.project_path,
            "state": state,
            "count": len(mrs),
            "pagination": pagination.extract(mrs),
            "merge_requests": summaries,
        }
        return output.ok(data, formatters.mrs_list(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing merge requests (state={state})")


@mcp.tool(
    name="gitlab_get_merge_request",
    annotations={
        "title": "Get Merge Request",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_get_merge_request(
    mr_iid: Annotated[
        int, Field(description="Merge request IID (project-local number shown as '!42').", gt=0)
    ],
    project_path: ProjectPath = None,
) -> MRDetailOutput:
    """Get full information about a merge request by internal ID (``iid``).

    Includes state, branches, author, assignees, reviewers, labels, conflict
    status, description and timestamps.

    Examples:
        - "Show me the description and state of !42" → ``mr_iid=42``
        - Don't use to see changed files — use ``gitlab_get_merge_request_changes``.
    """
    try:
        ci = get_ci(project_path)
        mr = ci.project.mergerequests.get(mr_iid)
        data: MRDetailOutput = {
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
            "created_at": ts(mr.created_at),
            "updated_at": ts(getattr(mr, "updated_at", None)),
            "merged_at": ts(getattr(mr, "merged_at", None)),
            "web_url": mr.web_url,
        }
        return output.ok(data, formatters.mr_detail(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"getting MR !{mr_iid}")


@mcp.tool(
    name="gitlab_get_merge_request_changes",
    annotations={
        "title": "Get Merge Request Changes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_get_merge_request_changes(
    mr_iid: Annotated[int, Field(description="Merge request IID.", gt=0)],
    project_path: ProjectPath = None,
) -> MRChangesOutput:
    """List changed files in a merge request with truncated diffs (2KB per file).

    Useful for code-review-style queries ("what changed in !42?"). Diffs beyond
    2KB are truncated — fetch the raw file via ``gitlab_get_file`` for full
    content.

    Examples:
        - "What did MR !42 change" → ``mr_iid=42``
        - If you need full content of a changed file, use ``gitlab_get_file``
          with the MR's source branch.
    """
    try:
        ci = get_ci(project_path)
        mr = ci.project.mergerequests.get(mr_iid)
        changes = mr.changes()
        files: list[FileChange] = [
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
        data: MRChangesOutput = {
            "mr_iid": mr_iid,
            "title": changes.get("title"),
            "files_count": len(files),
            "files": files,
        }
        return output.ok(data, formatters.mr_changes(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"getting changes of MR !{mr_iid}")


@mcp.tool(
    name="gitlab_create_merge_request",
    annotations={
        "title": "Create Merge Request",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    structured_output=True,
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
) -> MRActionResult:
    """Create a merge request from ``source_branch`` into ``target_branch``.

    **Not idempotent**: creates a new MR each call. Check existing MRs first
    via ``gitlab_list_merge_requests`` if you want to avoid duplicates.

    Examples:
        - "Open an MR from feature/login to master" → ``source_branch='feature/login'``
        - "Open a WIP MR with a label" → ``title='Draft: ...'``, ``labels=['wip']``
        - Don't use to merge an already-open MR — use ``gitlab_merge_mr``.
    """
    try:
        ci = get_ci(project_path)
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
        data: MRActionResult = {
            "iid": mr.iid,
            "title": mr.title,
            "state": mr.state,
            "source_branch": mr.source_branch,
            "target_branch": mr.target_branch,
            "merge_status": getattr(mr, "merge_status", None),
            "web_url": mr.web_url,
            "status": "created",
        }
        md = f"✔ MR [!{mr.iid}]({mr.web_url}) created: `{source_branch}` → `{target_branch}` — {mr.state}"
        return output.ok(data, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"creating MR from {source_branch} into {target_branch}")


@mcp.tool(
    name="gitlab_merge_mr",
    annotations={
        "title": "Merge an MR",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_merge_mr(
    mr_iid: Annotated[int, Field(description="Merge request IID to merge.", gt=0)],
    project_path: ProjectPath = None,
) -> MRActionResult:
    """Perform the actual merge if GitLab reports the MR can be merged.

    **Destructive**: writes to the target branch. Checks ``merge_status`` first
    and returns ``status='cannot_merge'`` if conflicts exist or pipelines are
    required.

    Examples:
        - "Merge !42" → ``mr_iid=42``
        - Don't call without checking ``gitlab_get_merge_request`` first when you suspect conflicts.
    """
    try:
        ci = get_ci(project_path)
        mr = ci.project.mergerequests.get(mr_iid)
        if getattr(mr, "merge_status", "") != "can_be_merged":
            data: MRActionResult = {
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
            md = f"⚠ MR [!{mr.iid}]({mr.web_url}) cannot be merged — {data['merge_status']}"
            return output.ok(data, md)  # type: ignore[return-value]
        mr.merge()
        data = {"iid": mr.iid, "status": "merged", "web_url": mr.web_url}
        md = f"✔ MR [!{mr.iid}]({mr.web_url}) merged"
        return output.ok(data, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"merging MR !{mr_iid}")
