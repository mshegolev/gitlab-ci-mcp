# GitLab compatibility and schedule-variable diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make missing schedule variables a clear, version-aware MCP error and publish an explicit GitLab support policy.

**Architecture:** Read variables only from the schedule response's raw `attributes`. If the response omits the field, query `python-gitlab`'s `Gitlab.version()` only on that failure path and raise a schedule-specific error containing the version or `unknown`, plus role/ownership and response-contract guidance. Keep the public `variables` type as a dictionary because the tool will fail rather than return an ambiguous `null`. Document the GitLab support policy and distinguish it from tested versions.

**Tech Stack:** Python 3.10+, python-gitlab, pytest, Ruff, Markdown.

**Spec:** `docs/superpowers/specs/2026-11-26-gitlab-compatibility-design.md`

## Global Constraints

- Support GitLab.com and self-managed releases currently maintained by GitLab; the README's current version snapshot is 19.4, 19.5, and 19.6 as of 2026-11-26.
- Do not claim the repository CI has verified GitLab server versions; its current matrix covers Python 3.10, 3.11, and 3.12 only.
- Never echo schedule variable values or server revision in errors.
- Do not call the version endpoint when schedule variables are present.
- GitLab may omit schedule variables for callers who are not Maintainers/Owners or schedule owners; an omitted field is not an empty variable list.

## Review Focus

- Missing variables due to role/ownership vs API response mismatch — fail with schedule ID, GitLab version or `unknown`, and next-step guidance; never report `{}` or `null`.
- A working schedule response — preserve values and avoid the extra `/version` request.
- An explicitly empty variable array — preserve `{}` as the confirmed empty set.
- An unavailable `/version` response — still return the primary missing-field error with version marked unknown.
- A malformed variables array — report schedule and response-contract error without exposing values.

---

### Task 1: Parse schedule variables and diagnose omitted API fields

**Files:**
- Modify: `src/gitlab_ci_mcp/ci_manager.py`
- Test: `tests/test_hardening.py`

**Interfaces:**
- Consumes: `GitLabCIManager.gl`, the configured `python-gitlab` client.
- Produces: `GitLabCIManager.list_schedules() -> list[ScheduleInfo]`; `ScheduleInfo.variables` remains `dict[str, str]` because missing fields raise instead of being returned.

- [x] **Step 1: Write a regression test for a missing field**

Add `test_schedule_missing_variables_field_raises_with_version`: schedule details have `attributes={}`, and fake `gl.version()` returns `("19.6.1-ee", "revision")`. Assert a `RuntimeError` names the schedule, version, missing API field, and role/ownership or interface guidance; assert no revision is included.

- [x] **Step 2: Run the test and confirm it fails against current code**

Run: `uv run --no-sync pytest tests/test_hardening.py::test_schedule_missing_variables_field_raises_with_version -q`
Expected: FAIL because current code calls the unsupported `.variables.list()` and raises an AttributeError-wrapped error without a GitLab version.

- [x] **Step 3: Implement the missing-field diagnostic**

In `GitLabCIManager.list_schedules`, read `detail.attributes`. If key `variables` is absent, call `self.gl.version()` once for this failure path; use the returned version unless it is empty/unknown, otherwise display `unknown`. Raise a clear `RuntimeError` naming the schedule and explaining the field may be omitted for role/ownership reasons or because the response contract differs. Do not include revision or variable values. Parse a present array into a dict; preserve a present empty array as `{}`. Keep malformed entries inside the schedule-specific error handler.

- [x] **Step 4: Add tests for present, empty, malformed, and version-lookup-failure cases**

Assert populated fields map to key/value dictionaries, an explicit empty array maps to `{}`, malformed entries raise a schedule-specific response-contract error, and a failed/unknown `gl.version()` still produces the primary error with version `unknown`. Assert `gl.version()` is not called when variables are present.

- [x] **Step 5: Run schedule-specific tests**

Run: `uv run --no-sync pytest tests/test_hardening.py -q`
Expected: all hardening tests pass.

### Task 2: Keep the MCP output contract truthful

**Files:**
- Modify: `src/gitlab_ci_mcp/models.py`
- Modify: `src/gitlab_ci_mcp/tools/schedules.py`
- Test: `tests/test_hardening.py`

**Interfaces:**
- Consumes: `ScheduleInfo.variables: dict[str, str]` or an exception from Task 1.
- Produces: `ScheduleSummary.variables: dict[str, str]`; `gitlab_list_schedules` masks secret-looking values for successful results and surfaces the explicit tool error otherwise.

- [x] **Step 1: Add a tool-level regression test**

Add `test_schedule_tool_surfaces_missing_variables_error`: call the real FastMCP tool manager with a fake GitLab schedule response. Assert a successful response masks secret-looking values, then remove the response field and assert the tool manager raises `ToolError` with the version-aware message. FastMCP's protocol server converts `ToolError` into an MCP error result; no `null` schedule variables are returned.

- [x] **Step 2: Verify the non-null output types and masking path**

Keep both schedule variable annotations as `dict[str, str]` and call `mask_variables` unconditionally for successful schedules. If the existing declarations already satisfy this contract, leave them unchanged. Keep the docstring clear that omitted variables produce an actionable MCP error.

- [x] **Step 3: Run the tool-level regression test**

Run: `uv run --no-sync pytest tests/test_hardening.py::test_schedule_tool_surfaces_missing_variables_error -q`
Expected: PASS with the ToolError diagnostic and secret masking assertions.

### Task 3: Publish the support policy and verification limits

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: approved policy in `docs/superpowers/specs/2026-11-26-gitlab-compatibility-design.md`.
- Produces: a compatibility section naming GitLab.com and the current maintained self-managed lines, with an as-of date and official policy link.

- [x] **Step 1: Document supported versions and limits**

Replace the unqualified “Works with any GitLab” claim with the documented support policy. List GitLab 19.4, 19.5, and 19.6 as maintained releases as of 2026-11-26, link GitLab's maintenance policy, explain the list changes monthly, and state that repository CI currently tests Python versions but not GitLab server versions. Document that schedule-variable visibility requires Maintainer/Owner role or schedule ownership.

- [x] **Step 2: Review wording against authoritative sources**

Check the exact current maintained-release list and the schedule-variable visibility note against the linked official GitLab documentation. Expected: no claim that these versions were tested by this repository.

### Task 4: Verify the complete change

**Files:**
- Verify: `src/gitlab_ci_mcp/ci_manager.py`, `src/gitlab_ci_mcp/models.py`, `src/gitlab_ci_mcp/tools/schedules.py`, `tests/test_hardening.py`, `README.md`

- [x] **Step 1: Run the full suite**

Run: `uv run --no-sync pytest -q`
Expected: all tests pass.

- [x] **Step 2: Run lint and whitespace checks**

Run: `uv run --no-sync ruff check src tests && git diff --check`
Expected: both commands pass.
