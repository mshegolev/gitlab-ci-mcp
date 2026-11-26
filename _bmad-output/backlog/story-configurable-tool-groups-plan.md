---
title: 'Выборочное отключение групп MCP-инструментов'
type: 'feature'
ticket: 'story-configurable-tool-groups'
created: '2026-11-25'
status: 'built'
baseline_revision: '0f6bcee2b9f698f56e0d4fe673b40131567d8903'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every client currently receives all 26 tools even when an operator only needs a subset, increasing the tool context clients must handle. Misconfiguration must be visible, and the default must preserve current behavior.

**Approach:** Add `GITLAB_DISABLED_TOOL_GROUPS`, validate its comma-separated group IDs, and import only enabled tool modules before FastMCP registration. Document the stable group-to-tool mapping and input behavior in README.

## Boundaries & Constraints

**Always:** No setting or a whitespace-only setting keeps all six groups. Trim tokens; ignore empty tokens and duplicates. Reject every unknown ID with a clear error naming it. An explicit list of all six IDs is valid and results in zero tools. Preserve the names, behavior, and schemas of enabled tools.

**Never:** Do not change GitLab permissions/API behavior, tool implementations, resource registration, project-path schema, HTTP authentication, or the separate update-check enable flag. Do not silently ignore unknown configuration values.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default | Variable absent, empty, or whitespace | All 26 tools from all six groups are registered | No error |
| Selected groups | `pipelines, repository` | Those groups are absent; other groups remain registered | No error |
| Normalization | ` , pipelines , , pipelines ` | Pipelines disabled once; empty and duplicate items have no effect | No error |
| Unknown ID | `pipelines, typo` | Startup fails before serving | Error identifies `typo` and the setting |
| Disable all | All six valid IDs | Startup succeeds with zero registered tools | No error |

</frozen-after-approval>

## Code Map

- `src/gitlab_ci_mcp/tools/__init__.py` -- current unconditional imports register all six tool modules; select enabled modules here before decorators run.
- `src/gitlab_ci_mcp/server.py` -- imports the tools package and configures schemas; entrypoint behavior and zero-tool startup must remain sound.
- `src/gitlab_ci_mcp/tools/{pipelines,schedules,branches_tags,mrs,repo,updates}.py` -- module boundaries correspond one-to-one with the six configurable groups.
- `tests/test_entrypoint.py` -- subprocess and protocol-level tool listing tests; appropriate place for fresh-process configuration coverage.
- `tests/test_smoke.py` -- default registry, tool names, output schemas, and annotations; default behavior must remain unchanged.
- `README.md` -- Features list and Configuration table; add the variable and complete stable group composition.
- `_bmad-output/backlog/story-configurable-tool-groups.md` -- approved requirements and acceptance cases.

## Tasks & Acceptance

**Execution:**
- [x] `src/gitlab_ci_mcp/tools/__init__.py` -- define the supported group-to-module mapping, parse and validate `GITLAB_DISABLED_TOOL_GROUPS`, then import only enabled modules -- preserve default registration and make disabled modules absent from the server registry.
- [x] `tests/test_entrypoint.py` -- exercise missing/blank values, normalized duplicates and empty tokens, one and multiple disabled groups, unknown IDs, and all groups disabled in fresh subprocesses -- prove the externally visible tool list and startup error without shared import-cache contamination.
- [x] `README.md` -- document the environment variable, all six IDs with exact tool membership, normalization/error behavior, disable-all behavior, and a multi-group example -- make configuration reviewable without inspecting source.

**Acceptance Criteria:**
- Given no effective disabled IDs, when the server lists tools, then all 26 current tools are present.
- Given known IDs, when the server lists tools, then exactly the tools belonging to those groups are absent and every other current tool remains.
- Given an unknown ID, when startup initializes tool registration, then a clear configuration error names the offending ID.
- Given all six IDs, when the server initializes, then it succeeds and lists zero tools.
- Given the README Configuration section, when an operator configures groups, then all group IDs and memberships plus parsing rules and an example are documented.

## Implementation Notes

Implemented conditional tool-module imports at package initialization. The six validated IDs map directly to their module boundaries; invalid IDs raise `ValueError` before registration. Fresh-process entrypoint tests cover all I/O matrix cases. Focused tests: 27 passed; full suite: 126 passed; Ruff and `git diff --check` passed.

## Plan Change Log

## Review Triage Log

## Design Notes

Import-time registration is the existing mechanism: importing a tool module executes its `@mcp.tool` decorators. Filtering the imports at the package boundary avoids depending on FastMCP's private removal API and keeps group ownership aligned with module ownership. Unknown IDs should be validated before importing any group module so startup fails deterministically.

## Verification

**Commands:**
- `uv run pytest tests/test_entrypoint.py tests/test_smoke.py` -- expected: subprocess configuration cases pass and default registry remains at 26 tools with existing schemas/annotations.
- `uv run pytest` -- expected: full repository test suite passes.
- `uv run ruff check src/gitlab_ci_mcp/tools/__init__.py tests/test_entrypoint.py` -- expected: no lint errors in changed Python files.
- `git diff --check` -- expected: no whitespace errors.
