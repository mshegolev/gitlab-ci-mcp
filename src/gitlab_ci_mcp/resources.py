"""MCP resources that mirror common tool calls for clients that prefer the
resource model over tools.
"""

from __future__ import annotations

from gitlab_ci_mcp import errors, formatters
from gitlab_ci_mcp._mcp import get_ci, mcp, ts


@mcp.resource(
    "gitlab://project/info",
    name="Project Info",
    description="Metadata of the default project (GITLAB_PROJECT_PATH).",
    mime_type="text/markdown",
)
def project_info_resource() -> str:
    """Markdown snapshot of the default project, exposed as an MCP resource."""
    try:
        ci = get_ci(None)
        p = ci.project
        data = {
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
        return formatters.project_info(data)
    except Exception as exc:
        return errors.handle(exc, "reading project info resource")


@mcp.resource(
    "gitlab://project/ci-config",
    name="CI Config",
    description="Contents of .gitlab-ci.yml on the default branch.",
    mime_type="text/yaml",
)
def ci_config_resource() -> str:
    """Raw ``.gitlab-ci.yml`` of the default project on its default branch."""
    try:
        ci = get_ci(None)
        ref = ci.project.default_branch or "master"
        f = ci.project.files.get(file_path=".gitlab-ci.yml", ref=ref)
        return f.decode().decode("utf-8", errors="replace")
    except Exception as exc:
        return errors.handle(exc, "reading .gitlab-ci.yml resource")
