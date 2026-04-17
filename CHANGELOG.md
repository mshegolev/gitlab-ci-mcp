# Changelog

All notable changes to `gitlab-ci-mcp` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use [SemVer](https://semver.org/).

## [0.4.0] — 2026-04-17

### Added
- **Lifespan management** (`asynccontextmanager`) — `python-gitlab` HTTP
  sessions closed cleanly on server shutdown.
- **MCP Context integration** — `gitlab_pipeline_health` and
  `gitlab_get_job_log` are now `async def` and emit `ctx.info` / `ctx.report_progress`
  events, letting clients display progress for the slower operations.
- **MCP Resources** — `gitlab://project/info` (markdown snapshot of the default
  project) and `gitlab://project/ci-config` (raw `.gitlab-ci.yml`).
- Tests for lifespan, async tools' Context parameters, and resource registration.

### Changed
- README: "Design highlights" section extended with Lifespan / Context /
  Resources entries and a "Threading model" subsection documenting why most
  tools remain sync (FastMCP runs them in a worker thread).

## [0.3.1] — 2026-04-17

### Added
- `Examples` section on every remaining tool docstring — all 23 tools now
  include "Use when / Don't use when" guidance for LLM tool-picking.
- `CHANGELOG.md`.
- README section on rate limits and connection reuse.

## [0.3.0] — 2026-04-17

### Added
- **Pagination**: new `gitlab_ci_mcp.pagination` module exposes `page`,
  `per_page`, `total`, `total_pages`, `next_page`, `has_more` on all list
  tools (`list_pipelines`, `list_branches`, `list_tags`,
  `list_merge_requests`, `list_repository_tree`).
- Markdown formatters render a pagination footer with a next-page hint.
- **Docstring `Examples:` sections** on 14 tools covering "Use when / Don't
  use when" — improves agent routing accuracy.
- **Mock tests** (`tests/test_tools_mocked.py`, 7 cases) using the
  `responses` library: happy paths (JSON + markdown), pagination,
  401/404 error paths, missing env, project info markdown shape.
- **Evaluations** (`evaluations/questions.xml`): 22 tool-picking QA pairs
  for agent-level evaluation; plus a minimal runner snippet.

### Changed
- `responses>=0.25` added to dev dependencies.

## [0.2.0] — 2026-04-17

### Added
- Tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`) on all 23 tools.
- Pydantic input validation via `typing.Annotated + pydantic.Field` on every
  argument (descriptions, ranges, lengths, Literal enums).
- Dual response format: `response_format='markdown'` (default) or
  `'json'` on read tools.
- New `gitlab_ci_mcp.errors` module — actionable error messages for
  auth / 404 / 403 / 5xx / `ValueError` instead of raw tracebacks.
- New `gitlab_ci_mcp.formatters` module — compact markdown renderings
  for pipelines, jobs, schedules, branches, tags, MRs, diffs, repo tree,
  file content, compare, project info.

### Changed
- FastMCP server name `'gitlab'` → `'gitlab_ci_mcp'` to match
  `{service}_mcp` convention.
- README redesigned with a "Design highlights" section explaining the
  above.

## [0.1.0] — 2026-04-17

### Added
- Initial release. FastMCP server exposing 22 tools over stdio for
  pipelines, schedules, branches, tags, merge requests, repository
  files, and pipeline health. Env-based config, MIT license.
