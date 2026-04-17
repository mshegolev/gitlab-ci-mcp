"""TypedDict output schemas for every MCP tool.

Each tool's return type annotation is one of these TypedDicts. FastMCP
auto-generates an ``outputSchema`` from the annotation and exposes the
tool's payload via ``structuredContent``; the ``content`` block carries a
pre-rendered markdown summary so agents keep the same compact, human-
readable text they had before.

Fields declared ``total=False`` are all optional in the JSON Schema;
we use it for "action result" shapes where the set of returned fields
varies by operation outcome (e.g. ``cannot_merge`` vs ``merged``).

Nested summaries (``PipelineSummary``, ``JobSummary``, …) are declared
once and reused across list / detail outputs.
"""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

# ── Shared building blocks ──────────────────────────────────────────────────


class PaginationMeta(TypedDict, total=False):
    page: int | None
    per_page: int | None
    total: int | None
    total_pages: int | None
    next_page: int | None
    has_more: bool


# ── Pipelines ───────────────────────────────────────────────────────────────


class PipelineSummary(TypedDict):
    id: int
    status: str
    ref: str
    source: str | None
    created_at: str | None
    duration: int | None
    web_url: str


class PipelinesListOutput(TypedDict):
    project: str
    count: int
    pagination: PaginationMeta
    pipelines: list[PipelineSummary]


class PipelineDetailOutput(TypedDict):
    id: int
    status: str
    ref: str
    source: str | None
    created_at: str | None
    updated_at: str | None
    started_at: str | None
    finished_at: str | None
    duration: int | None
    queued_duration: int | None
    web_url: str


class JobSummary(TypedDict):
    id: int
    name: str
    stage: str
    status: str
    duration: float | None
    web_url: str


class JobsListOutput(TypedDict):
    pipeline_id: int
    jobs_count: int
    jobs: list[JobSummary]


class JobLogOutput(TypedDict, total=False):
    job_id: int
    total_lines: int
    showing_last: int
    log: str
    grep_pattern: str
    grep_matches: int


class HealthOutput(TypedDict):
    project: str
    ref: str
    source: str
    rate_7d: float
    rate_30d: float
    trend: str
    total_7d: int
    success_7d: int
    failed_7d: int
    total_30d: int
    success_30d: int
    failed_30d: int
    last_10_statuses: list[str]
    generated_at: str


class PipelineActionResult(TypedDict, total=False):
    """Result shape for trigger / retry / cancel operations. Fields vary."""

    pipeline_id: int
    status: str
    web_url: str
    ref: str
    created_at: str
    status_note: str


# ── Schedules ───────────────────────────────────────────────────────────────


class ScheduleSummary(TypedDict):
    id: int
    description: str
    cron: str
    cron_timezone: str
    ref: str
    active: bool
    next_run_at: str | None
    variables: dict[str, str]
    web_url: str


class SchedulesListOutput(TypedDict):
    project: str
    schedules_count: int
    active_count: int
    schedules: list[ScheduleSummary]


class ScheduleActionResult(TypedDict, total=False):
    schedule_id: int
    status: str
    description: str
    cron: str
    ref: str
    active: bool


# ── Branches & tags ─────────────────────────────────────────────────────────


class BranchSummary(TypedDict):
    name: str
    merged: bool | None
    protected: bool | None
    default: bool | None
    commit_short_id: str | None
    commit_title: str | None
    committed_date: str | None


class BranchesListOutput(TypedDict):
    project: str
    count: int
    pagination: PaginationMeta
    branches: list[BranchSummary]


class TagSummary(TypedDict):
    name: str
    message: str | None
    commit_short_id: str | None
    committed_date: str | None


class TagsListOutput(TypedDict):
    project: str
    count: int
    pagination: PaginationMeta
    tags: list[TagSummary]


# ── Merge requests ──────────────────────────────────────────────────────────


class MRSummary(TypedDict):
    iid: int
    title: str
    state: str
    source_branch: str
    target_branch: str
    author: str | None
    merge_status: str | None
    created_at: str | None
    updated_at: str | None
    web_url: str


class MRsListOutput(TypedDict):
    project: str
    state: str
    count: int
    pagination: PaginationMeta
    merge_requests: list[MRSummary]


class MRDetailOutput(TypedDict):
    iid: int
    title: str
    description: str | None
    state: str
    source_branch: str
    target_branch: str
    author: str | None
    assignees: list[str]
    reviewers: list[str]
    labels: list[str]
    merge_status: str | None
    has_conflicts: bool | None
    changes_count: int | str | None
    created_at: str | None
    updated_at: str | None
    merged_at: str | None
    web_url: str


class FileChange(TypedDict):
    old_path: str | None
    new_path: str | None
    new_file: bool | None
    renamed_file: bool | None
    deleted_file: bool | None
    diff: str


class MRChangesOutput(TypedDict):
    mr_iid: int
    title: str | None
    files_count: int
    files: list[FileChange]


class MRActionResult(TypedDict, total=False):
    iid: int
    title: str
    state: str
    source_branch: str
    target_branch: str
    merge_status: str
    has_conflicts: bool
    web_url: str
    status: str
    hint: str


# ── Repository & project ────────────────────────────────────────────────────


class FileContentOutput(TypedDict):
    file_path: str
    ref: str
    size: int
    total_lines: int
    truncated: bool
    content: str


class TreeItem(TypedDict):
    name: str
    type: str
    path: str


class RepoTreeOutput(TypedDict):
    project: str
    path: str
    ref: str
    count: int
    pagination: PaginationMeta
    items: list[TreeItem]


class CommitSummary(TypedDict):
    short_id: str | None
    title: str
    author_name: str | None
    created_at: str | None


class CompareDiff(TypedDict):
    old_path: str | None
    new_path: str | None
    new_file: bool | None
    deleted_file: bool | None


class CompareOutput(TypedDict):
    source: str
    target: str
    commits_count: int
    diffs_count: int
    commits: list[CommitSummary]
    changed_files: list[CompareDiff]


class ProjectInfoOutput(TypedDict):
    id: int
    name: str
    path_with_namespace: str
    default_branch: str | None
    web_url: str
    visibility: str | None
    created_at: str | None
    last_activity_at: str | None
    open_issues_count: int | None
    forks_count: int | None
    star_count: int | None


# ── Utility types ───────────────────────────────────────────────────────────

# Fallback when the typed shape is not worth duplicating. Agents still
# see structuredContent, just without strict field validation.
LooseOutput = dict[str, Any]
