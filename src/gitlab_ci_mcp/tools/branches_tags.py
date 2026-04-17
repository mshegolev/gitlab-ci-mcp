"""Branch, tag, and compare tools."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from gitlab_ci_mcp import formatters, output, pagination
from gitlab_ci_mcp._mcp import ProjectPath, get_ci, mcp, ts
from gitlab_ci_mcp.models import (
    BranchesListOutput,
    BranchSummary,
    CommitSummary,
    CompareDiff,
    CompareOutput,
    TagsListOutput,
    TagSummary,
)


@mcp.tool(
    name="gitlab_list_branches",
    annotations={
        "title": "List Branches",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_list_branches(
    search: Annotated[
        str | None,
        Field(default=None, description="Substring match on branch name (case-insensitive).", max_length=255),
    ] = None,
    per_page: Annotated[int, Field(default=20, ge=1, le=100, description="Items per page (1–100).")] = 20,
    page: Annotated[int, Field(default=1, ge=1, description="1-based page number.")] = 1,
    project_path: ProjectPath = None,
) -> BranchesListOutput:
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
        ci = get_ci(project_path)
        kwargs: dict[str, Any] = {"per_page": per_page, "page": page, "get_all": False}
        if search:
            kwargs["search"] = search
        branches = ci.project.branches.list(**kwargs)
        summaries: list[BranchSummary] = [
            {
                "name": b.name,
                "merged": getattr(b, "merged", None),
                "protected": getattr(b, "protected", None),
                "default": getattr(b, "default", None),
                "commit_short_id": b.commit["short_id"] if b.commit else None,
                "commit_title": b.commit.get("title", "")[:80] if b.commit else None,
                "committed_date": ts(b.commit.get("committed_date")) if b.commit else None,
            }
            for b in branches
        ]
        data: BranchesListOutput = {
            "project": ci.project_path,
            "count": len(branches),
            "pagination": pagination.extract(branches),
            "branches": summaries,
        }
        return output.ok(data, formatters.branches_list(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, "listing branches")


@mcp.tool(
    name="gitlab_list_tags",
    annotations={
        "title": "List Tags",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_list_tags(
    search: Annotated[
        str | None, Field(default=None, description="Substring match on tag name.", max_length=255)
    ] = None,
    per_page: Annotated[int, Field(default=20, ge=1, le=100, description="Items per page (1–100).")] = 20,
    page: Annotated[int, Field(default=1, ge=1, description="1-based page number.")] = 1,
    project_path: ProjectPath = None,
) -> TagsListOutput:
    """List tags of a project, newest first.

    Useful for release-note generation or checking the last shipped version.

    Examples:
        - "What was the last release tag" → default call, take the first item
        - "All v2.x releases" → ``search='v2.'``
    """
    try:
        ci = get_ci(project_path)
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
        summaries: list[TagSummary] = [
            {
                "name": t.name,
                "message": getattr(t, "message", None),
                "commit_short_id": t.commit["short_id"] if t.commit else None,
                "committed_date": ts(t.commit.get("committed_date")) if t.commit else None,
            }
            for t in tags
        ]
        data: TagsListOutput = {
            "project": ci.project_path,
            "count": len(tags),
            "pagination": pagination.extract(tags),
            "tags": summaries,
        }
        return output.ok(data, formatters.tags_list(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, "listing tags")


@mcp.tool(
    name="gitlab_compare_branches",
    annotations={
        "title": "Compare Branches",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_compare_branches(
    source: Annotated[str, Field(description="Source branch/tag/SHA.", min_length=1, max_length=255)],
    target: Annotated[
        str, Field(default="master", description="Target branch (default 'master').", min_length=1, max_length=255)
    ] = "master",
    project_path: ProjectPath = None,
) -> CompareOutput:
    """Compare two branches — returns up to 30 commits and the list of changed files.

    Use for "what's in ``release/x.y`` vs ``master``?" or for release-note drafting.

    Examples:
        - "What's new in release/1.5 vs master" → ``source='release/1.5'``, ``target='master'``
        - Don't use to fetch full diffs of an MR — use ``gitlab_get_merge_request_changes``.
    """
    try:
        ci = get_ci(project_path)
        comparison = ci.project.repository_compare(source, target)
        commits = comparison.get("commits", [])
        diffs = comparison.get("diffs", [])
        commit_summaries: list[CommitSummary] = [
            {
                "short_id": c.get("short_id"),
                "title": c.get("title", "")[:120],
                "author_name": c.get("author_name"),
                "created_at": ts(c.get("created_at")),
            }
            for c in commits[:30]
        ]
        changed_files: list[CompareDiff] = [
            {
                "old_path": d.get("old_path"),
                "new_path": d.get("new_path"),
                "new_file": d.get("new_file"),
                "deleted_file": d.get("deleted_file"),
            }
            for d in diffs
        ]
        data: CompareOutput = {
            "source": source,
            "target": target,
            "commits_count": len(commits),
            "diffs_count": len(diffs),
            "commits": commit_summaries,
            "changed_files": changed_files,
        }
        return output.ok(data, formatters.compare(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"comparing {source} with {target}")
