"""HTTP boundary authentication for the per-user GitLab PAT transport."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from gitlab_ci_mcp._mcp import mcp


class GitLabPATHeaderMiddleware(BaseHTTPMiddleware):
    """Require a request-local GitLab PAT without logging or echoing it."""

    def __init__(self, app: ASGIApp, endpoint_path: str) -> None:
        super().__init__(app)
        self.endpoint_path = endpoint_path

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == self.endpoint_path and request.method != "OPTIONS":
            token = request.headers.get("x-gitlab-token")
            if not token or not token.strip():
                return JSONResponse({"error": "X-GitLab-Token header is required"}, status_code=401)
        return await call_next(request)


def create_http_app():
    """Build the stateless Streamable HTTP app and require a PAT per request."""
    # Importing these packages registers all tools and resources on the shared MCP.
    from gitlab_ci_mcp import resources as _resources  # noqa: F401
    from gitlab_ci_mcp import tools as _tools  # noqa: F401

    app = mcp.streamable_http_app()
    app.add_middleware(
        GitLabPATHeaderMiddleware,
        endpoint_path=mcp.settings.streamable_http_path,
    )
    return app
