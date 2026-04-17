"""Actionable error messages for python-gitlab exceptions."""

from __future__ import annotations

import gitlab.exceptions as gle


def _rate_limited(action: str) -> str:
    return (
        f"Error: rate-limited (HTTP 429) while {action}. "
        "GitLab is throttling requests — wait ~60s before retrying, reduce "
        "`per_page`, or make fewer calls. See your instance's "
        "`/admin/application_settings/network` for the per-user hourly limit."
    )


def _server_error(code: int, action: str, exc: Exception) -> str:
    return (
        f"Error: GitLab server error (HTTP {code}) while {action}. "
        f"The server reported: {getattr(exc, 'error_message', exc)}. "
        "This is usually transient — retry in a few seconds."
    )


def handle(exc: Exception, action: str) -> str:
    """Convert an exception raised while performing ``action`` into an
    LLM-readable string with a suggested next step.

    The goal is that the agent sees *why* the call failed and *what it could
    do about it* without needing to inspect the Python traceback.
    """
    if isinstance(exc, gle.GitlabAuthenticationError):
        return (
            f"Error: GitLab authentication failed while {action}. "
            "Verify that `GITLAB_TOKEN` is set, not expired, and has the `api` scope. "
            f"Server response: {exc}"
        )

    # Rate-limit and 5xx are shared across Get/Create/Update/Delete, so check
    # the response_code up front (available on all GitlabError subclasses that
    # carry an HTTP response).
    code = getattr(exc, "response_code", None) if isinstance(exc, gle.GitlabError) else None
    if code == 429:
        return _rate_limited(action)
    if isinstance(code, int) and 500 <= code < 600:
        return _server_error(code, action, exc)

    if isinstance(exc, gle.GitlabGetError):
        if code == 404:
            return (
                f"Error: resource not found (HTTP 404) while {action}. "
                "Check that the IDs and `project_path` are correct."
            )
        if code == 403:
            return (
                f"Error: forbidden (HTTP 403) while {action}. "
                "Your token does not have permission for this operation. "
                "Try a token with broader scope or make sure you are a project member."
            )
        return f"Error: GitLab returned HTTP {code} while {action}: {getattr(exc, 'error_message', exc)}"
    if isinstance(exc, gle.GitlabCreateError):
        return (
            f"Error: could not create resource while {action}: "
            f"{getattr(exc, 'error_message', exc)}. Check required fields and uniqueness constraints."
        )
    if isinstance(exc, gle.GitlabUpdateError):
        return (
            f"Error: could not update resource while {action}: "
            f"{getattr(exc, 'error_message', exc)}. The resource may have been modified or deleted."
        )
    if isinstance(exc, gle.GitlabDeleteError):
        return (
            f"Error: could not delete resource while {action}: "
            f"{getattr(exc, 'error_message', exc)}. Verify the resource still exists."
        )
    if isinstance(exc, gle.GitlabError):
        return f"Error: GitLab API error while {action}: {exc}"
    if isinstance(exc, ValueError):
        # Raised by GitLabCIManager.__init__ when config env vars are missing.
        return f"Error: configuration problem — {exc}"
    return f"Error: unexpected {type(exc).__name__} while {action}: {exc}"
