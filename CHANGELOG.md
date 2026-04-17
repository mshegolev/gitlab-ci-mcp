# Changelog

All notable changes to `gitlab-ci-mcp` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use [SemVer](https://semver.org/).

## [0.5.0] — 2026-04-17

**Big one.** Every tool is now a fully typed MCP citizen: ``outputSchema``,
``structuredContent``, and the markdown text block you liked are now all
present on every response.

### Added
- **TypedDict output schemas** for all 23 tools (new ``models.py``) —
  FastMCP auto-generates an ``outputSchema`` from the return annotation
  and exposes the typed payload as ``structuredContent`` on every tool
  result.
- **Dual-channel responses via ``CallToolResult``** — the ``content``
  block still carries the compact markdown rendering (context-efficient
  for agents), while ``structuredContent`` carries the full validated
  payload (for clients that can render / process structured data).
- New ``output.py`` with ``ok()`` (builds the ``CallToolResult``) and
  ``fail()`` (raises ``ToolError`` wrapping the actionable error
  message). All 23 tools share this pattern.

### Changed
- **Server split into domain modules**: the 1500-line ``server.py`` is
  now a thin composition point; tools live under ``tools/``
  (``pipelines.py``, ``schedules.py``, ``branches_tags.py``, ``mrs.py``,
  ``repo.py``), MCP resources in ``resources.py``, and shared FastMCP
  instance + lifespan + helpers in ``_mcp.py``.
- Shared helpers ``_get_ci`` / ``_ts`` / ``_is_secret_key`` /
  ``_mask_variables`` renamed without the leading underscore and moved
  to ``_mcp`` (they are no longer single-module private).
- Error path is now uniform: tools raise ``ToolError(errors.handle(…))``
  and FastMCP reports the result as ``isError=True`` — no more
  string-based error returns.

### Removed
- **``response_format`` parameter** (breaking): no longer needed because
  every tool now returns *both* markdown and structured data. Existing
  callers that passed ``response_format='markdown'`` or ``'json'`` must
  drop the argument — markdown remains the text content by default,
  structured data is on ``result.structuredContent``.
- Dead code from ``ci_manager.py``: ``wait_for_pipeline``,
  ``ScheduleCompareResult`` (unused from the MCP path).

### Migration notes (v0.4.x → v0.5.0)
- Tools no longer return plain strings. If you call them programmatically,
  inspect ``result.structuredContent`` for the typed payload and
  ``result.content[0].text`` for the markdown summary.
- Module imports moved: ``from gitlab_ci_mcp.server import mcp`` still
  works, but tool functions now live under ``gitlab_ci_mcp.tools.*``.

## [0.4.2] — 2026-04-17

### Changed
- `warnings.filterwarnings("ignore")` and `urllib3.disable_warnings()` now
  target **only** `urllib3.exceptions.InsecureRequestWarning` so future
  deprecation / runtime warnings from any library still surface.
- `evaluations/questions.xml` — destructive-op questions (trigger / cancel /
  retry / delete / create / merge) reframed as "Which tool should you call
  to …?" to make the routing-only evaluation intent unambiguous. Added a
  top-of-file comment stating harnesses must capture tool names, not execute
  the tools.

## [0.4.1] — 2026-04-17

### Added
- `gitlab_get_job_log` — new `grep_pattern` + `grep_context` parameters for
  regex-filtering large CI logs with surrounding context instead of blindly
  tailing. Falls back to literal substring on invalid regex.
- `errors.handle` — explicit branches for HTTP 429 (rate-limit with wait/retry
  guidance) and 5xx (transient server error, retry hint), applied uniformly
  across Get/Create/Update/Delete exceptions.
- Tests for 429 / 5xx error paths, secret-masking helper, and job-log grep
  parameters.

### Changed
- `gitlab_list_schedules` — expanded secret redaction from `TOKEN`/`PASSWORD`
  to also match `SECRET`, `CREDENTIAL`, `PRIVATE_KEY`, `API_KEY`. Now *masks
  values* (`"***"`) instead of dropping keys, so the agent can still see which
  variables exist on a schedule.
- `evaluations/questions.xml` — added 7 multi-tool composition questions on
  top of the 22 tool-picking ones.

### Fixed
- `tests/test_tools_mocked.py` — removed a leftover `os.environ.pop(v, None)`
  that used the loop variable outside its scope (redundant with
  `monkeypatch.delenv`).

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
