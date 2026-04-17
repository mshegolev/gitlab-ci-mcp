"""Repository file, tree, and project metadata tools."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from gitlab_ci_mcp import formatters, output, pagination
from gitlab_ci_mcp._mcp import ProjectPath, get_ci, mcp, ts
from gitlab_ci_mcp.models import (
    FileContentOutput,
    ProjectInfoOutput,
    RepoTreeOutput,
    TreeItem,
)


@mcp.tool(
    name="gitlab_get_file",
    annotations={
        "title": "Get Repository File",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
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
) -> FileContentOutput:
    """Read a text file from the repository, truncated to 500 lines.

    For binaries, gets decoded as UTF-8 with errors replaced — you will likely
    get garbage; use for text content only.

    Examples:
        - "Show me .gitlab-ci.yml on master" → ``file_path='.gitlab-ci.yml'``
        - "Read src/app.py from the release-1.2 tag" → ``file_path='src/app.py'``, ``ref='release-1.2'``
        - Don't use for listings — use ``gitlab_list_repository_tree``.
    """
    try:
        ci = get_ci(project_path)
        f = ci.project.files.get(file_path=file_path, ref=ref)
        content = f.decode().decode("utf-8", errors="replace")
        lines = content.splitlines()
        truncated = len(lines) > 500
        if truncated:
            content = "\n".join(lines[:500])
        data: FileContentOutput = {
            "file_path": file_path,
            "ref": ref,
            "size": f.size,
            "total_lines": len(lines),
            "truncated": truncated,
            "content": content,
        }
        return output.ok(data, formatters.file_content(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"getting file {file_path}@{ref}")


@mcp.tool(
    name="gitlab_list_repository_tree",
    annotations={
        "title": "List Repository Tree",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
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
) -> RepoTreeOutput:
    """List files and directories at a given path in the repository.

    Examples:
        - "Show top-level files" → default call
        - "All .py files recursively" → ``recursive=True`` then filter on ``.py`` in path
        - Don't use for full-text content — use ``gitlab_get_file`` for that.
    """
    try:
        ci = get_ci(project_path)
        items = ci.project.repository_tree(
            path=path, ref=ref, recursive=recursive, per_page=per_page, page=page, get_all=False
        )
        tree: list[TreeItem] = [
            {"name": item["name"], "type": item["type"], "path": item["path"]} for item in items
        ]
        data: RepoTreeOutput = {
            "project": ci.project_path,
            "path": path or "/",
            "ref": ref,
            "count": len(items),
            "pagination": pagination.extract(items),
            "items": tree,
        }
        return output.ok(data, formatters.repo_tree(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing tree {path or '/'}@{ref}")


@mcp.tool(
    name="gitlab_project_info",
    annotations={
        "title": "Get Project Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_project_info(project_path: ProjectPath = None) -> ProjectInfoOutput:
    """Return basic metadata about a project: ID, default branch, visibility, counts.

    Examples:
        - "What's the project ID and default branch" → default call
        - "Is this repo public or private" → look at ``visibility``
    """
    try:
        ci = get_ci(project_path)
        p = ci.project
        data: ProjectInfoOutput = {
            "id": p.id,
            "name": p.name,
            "path_with_namespace": p.path_with_namespace,
            "default_branch": p.default_branch,
            "web_url": p.web_url,
            "visibility": getattr(p, "visibility", None),
            "created_at": ts(getattr(p, "created_at", None)),
            "last_activity_at": ts(getattr(p, "last_activity_at", None)),
            "open_issues_count": getattr(p, "open_issues_count", None),
            "forks_count": getattr(p, "forks_count", None),
            "star_count": getattr(p, "star_count", None),
        }
        return output.ok(data, formatters.project_info(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, "getting project info")
