"""CI/CD schedule tools."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from gitlab_ci_mcp import formatters, output
from gitlab_ci_mcp._mcp import ProjectPath, get_ci, mask_variables, mcp
from gitlab_ci_mcp.models import (
    ScheduleActionResult,
    SchedulesListOutput,
    ScheduleSummary,
)


@mcp.tool(
    name="gitlab_list_schedules",
    annotations={
        "title": "List CI/CD Schedules",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_list_schedules(project_path: ProjectPath = None) -> SchedulesListOutput:
    """List all CI/CD schedules of a project.

    Variable keys whose name hints at a secret (``TOKEN``, ``PASSWORD``,
    ``SECRET``, ``CREDENTIAL``, ``PRIVATE_KEY``, ``API_KEY``) keep the key
    but have the value replaced by ``***`` so the agent still sees which
    variables exist.

    Examples:
        - "What schedules do we have and are they all active" → default call
        - Don't use to *run* a schedule now — use ``gitlab_trigger_pipeline``
          with the schedule's variables instead.
    """
    try:
        ci = get_ci(project_path)
        schedules = ci.list_schedules()
        summaries: list[ScheduleSummary] = [
            {
                "id": s.id,
                "description": s.description,
                "cron": s.cron,
                "cron_timezone": s.cron_timezone,
                "ref": s.ref,
                "active": s.active,
                "next_run_at": s.next_run_at,
                "variables": mask_variables(s.variables),
                "web_url": s.web_url,
            }
            for s in schedules
        ]
        data: SchedulesListOutput = {
            "project": ci.project_path,
            "schedules_count": len(schedules),
            "active_count": sum(1 for s in schedules if s.active),
            "schedules": summaries,
        }
        return output.ok(data, formatters.schedules_list(data))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, "listing schedules")


@mcp.tool(
    name="gitlab_create_schedule",
    annotations={
        "title": "Create CI/CD Schedule",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    structured_output=True,
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
) -> ScheduleActionResult:
    """Create a new CI/CD schedule with the given cron and variables.

    **Not idempotent**: duplicate calls create duplicate schedules with
    auto-incrementing IDs.

    Examples:
        - "Schedule a nightly build on master at 02:00 Europe/Berlin" →
          ``description='Nightly build'``, ``cron='0 2 * * *'``, ``ref='master'``,
          ``timezone='Europe/Berlin'``, ``variables={'NIGHTLY': '1'}``
        - Don't use to update existing schedules — use ``gitlab_update_schedule``.
    """
    try:
        ci = get_ci(project_path)
        schedule_id = ci.create_schedule(
            description=description,
            cron=cron,
            variables=variables,
            ref=ref,
            timezone=timezone,
            active=active,
        )
        data: ScheduleActionResult = {
            "schedule_id": schedule_id,
            "description": description,
            "cron": cron,
            "ref": ref,
            "active": active,
            "status": "created",
        }
        md = f"✔ Schedule `{schedule_id}` created: `{cron}` on `{ref}` (active={active})"
        return output.ok(data, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"creating schedule '{description}'")


@mcp.tool(
    name="gitlab_update_schedule",
    annotations={
        "title": "Update CI/CD Schedule",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
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
) -> ScheduleActionResult:
    """Update an existing schedule. Only provided fields change.

    Destructive when ``variables`` is set: the entire variable set is replaced,
    so ensure the caller sends a full list.

    Examples:
        - "Deactivate schedule 42" → ``schedule_id=42``, ``active=False``
        - "Change cron of schedule 42 to hourly" → ``schedule_id=42``, ``cron='0 * * * *'``
        - Don't pass ``variables`` unless you want to *replace* them entirely.
    """
    try:
        ci = get_ci(project_path)
        ci.update_schedule(
            schedule_id=schedule_id,
            description=description,
            cron=cron,
            ref=ref,
            active=active,
            variables=variables,
        )
        data: ScheduleActionResult = {"schedule_id": schedule_id, "status": "updated"}
        md = f"✔ Schedule `{schedule_id}` updated"
        return output.ok(data, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"updating schedule {schedule_id}")


@mcp.tool(
    name="gitlab_delete_schedule",
    annotations={
        "title": "Delete CI/CD Schedule",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def gitlab_delete_schedule(
    schedule_id: Annotated[int, Field(description="Schedule ID to delete.", gt=0)],
    project_path: ProjectPath = None,
) -> ScheduleActionResult:
    """Delete a schedule by ID. Cannot be undone.

    Examples:
        - "Delete schedule 42" → ``schedule_id=42``
        - If you only want to pause it temporarily, call ``gitlab_update_schedule``
          with ``active=False`` instead.
    """
    try:
        ci = get_ci(project_path)
        ci.delete_schedule(schedule_id)
        data: ScheduleActionResult = {"schedule_id": schedule_id, "status": "deleted"}
        md = f"✘ Schedule `{schedule_id}` deleted"
        return output.ok(data, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"deleting schedule {schedule_id}")
