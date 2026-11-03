# Shared MCP with per-user GitLab PATs Implementation Plan

> **For agentic workers:** Implement this plan task-by-task, test-first. Commit the completed tasks to the authorized feature branch. Do not put PAT values in URLs, MCP tool arguments, logs, responses, or committed configuration.

**Goal:** Let each remote MCP client use one shared Streamable HTTP server while every GitLab operation is made with that client's own PAT; preserve stdio and release all approved hardening changes.

**Architecture:** Keep stdio as the default and add an opt-in, stateless Streamable HTTP app. Require `X-GitLab-Token` on every HTTP request; each tool/resource handler reads that request's header through the MCP context and obtains a bounded in-memory GitLab client keyed by URL, project, and an HMAC token fingerprint. The HTTP middleware rejects missing headers before MCP processing, while GitLab itself validates PATs and permissions.

**Tech Stack:** Python 3.10–3.12, MCP Python SDK 1.x (`mcp>=1.30,<2`), FastMCP/Starlette, Uvicorn, python-gitlab, pytest, Ruff, GitHub Actions and PyPI Trusted Publishing.

**Spec:** `docs/superpowers/specs/2026-11-03-shared-mcp-gitlab-pat-design.md`

## Global Constraints

- `MCP_TRANSPORT=stdio` remains the default; stdio uses `GITLAB_TOKEN`.
- Remote mode is opt-in with `MCP_TRANSPORT=streamable-http` and never falls back to process-wide `GITLAB_TOKEN`.
- Every request to `/mcp` requires a non-empty `X-GitLab-Token`; the token is never a URL query parameter or tool argument.
- HTTP mode uses stateless Streamable HTTP; credentials are resolved per request.
- Client cache is process-local, bounded to 128 entries, and expires idle entries after 1800 seconds; cache keys contain an HMAC fingerprint, not the token.
- Existing fixed resource URIs use only an explicitly configured legacy default project and fail closed in strict scope mode.
- Remote deployments require HTTPS termination and redaction of `X-GitLab-Token` in all proxy/access/tracing logs.
- Keep `MCP_GITLAB_UPDATE_CHECK_ENABLED=false` as default; update checking remains explicit and independent of GitLab PAT handling.
- Bump package and server metadata to `0.5.5` for the release. Preserve OIDC and exact-tag validation in `.github/workflows/publish.yml`.
- Stage only project files. Preserve existing unrelated work. Do not expose or record credentials.

## Review Focus

- Two simultaneous callers use the same project but different PATs; they must get distinct managers and retain their own GitLab permissions.
- A missing, empty, malformed, or revoked PAT must fail without leaking its value or falling back to `GITLAB_TOKEN` in HTTP mode.
- Streamable HTTP initialization, tool listing, resource listing, tool calls, and close requests all carry the header; unauthenticated requests fail before MCP handling.
- Stdio calls still use `GITLAB_TOKEN`, and missing scope still fails before a GitLab request.
- Fixed resources in strict mode continue to fail clearly before accessing GitLab; legacy resources require both existing compatibility settings.

---

### Task 1: Isolated release branch

**Files:** Git worktree only.

**Interfaces:** Base the feature branch on fetched `origin/main` at `eee2364fa067bb6d404b4676a6efba0e0287d0e0a`. Keep the primary checkout untouched. Use branch `feat/shared-mcp-gitlab-pat`.

- [x] Verify `origin/main` still equals the expected baseline and the branch name does not exist locally or remotely.
- [x] Create and checkout `feat/shared-mcp-gitlab-pat` in the current managed worktree; confirm all existing approved dirty changes remain present.
- [x] Run the current approved hardening suite (`78 passed` expected on Python 3.12) and Ruff before changing auth code.
- [x] Commit the already-approved hardening/update-check work as `fix: harden GitLab CI operations`; stage only `.github/workflows/publish.yml`, `README.md`, `docs/claude-code.md`, `server.json`, the existing changed `src/gitlab_ci_mcp` files, and `tests/test_entrypoint.py`, `tests/test_tools_mocked.py`, `tests/test_hardening.py`. Leave `_bmad/`, `_bmad-output/`, and the auth design docs out of this commit.

### Task 2: Credential-aware manager factory and bounded cache

**Files:**
- Modify: `src/gitlab_ci_mcp/_mcp.py`
- Modify: `src/gitlab_ci_mcp/ci_manager.py`
- Test: `tests/test_hardening.py`

**Interfaces:**
- `get_ci(project_path: str | None, *, ctx: Context | None = None) -> GitLabCIManager`
- Add private `_request_gitlab_token(ctx: Context | None) -> str` to resolve the HTTP request header in HTTP mode and the environment token in stdio mode.
- Store managers in an `OrderedDict[tuple[str, str, str], CacheEntry]`, with URL, project path, and HMAC-SHA256 token fingerprint as the key.
- Use `_CACHE_TTL_SECONDS = 1800`, `_CACHE_MAX_ENTRIES = 128`, and a process-random HMAC key. Close expired/evicted sessions and all sessions during shutdown.

- [x] Add a test proving `get_ci` creates distinct clients for PAT A and PAT B on the same GitLab URL/project, and reuses a client for repeated calls with the same PAT.
- [x] Run that test and confirm it fails because the current cache is keyed only by project path.
- [x] Implement the request-token helper and bounded token-isolated cache. Never include the raw token in a key, log, error, or returned value.
- [x] Add tests for HTTP mode rejecting absent/empty request tokens without environment fallback, stdio retaining `GITLAB_TOKEN`, HMAC-only cache keys, LRU eviction, idle expiry, and session close.
- [x] Run `uv run --python 3.12 --extra dev pytest -q tests/test_hardening.py -k 'gitlab_client or request_gitlab_token or manager_cache'` and verify all focused tests pass.
- [x] Commit Task 2 as `feat: isolate GitLab clients by caller PAT`, staging only its implementation and tests.

### Task 3: Streamable HTTP mode and request-header gate

**Files:**
- Create: `src/gitlab_ci_mcp/http_auth.py`
- Modify: `src/gitlab_ci_mcp/_mcp.py`
- Modify: `src/gitlab_ci_mcp/server.py`
- Modify: `pyproject.toml` (require `mcp>=1.30,<2` for the supported Streamable HTTP/session lifecycle and declare Uvicorn if importing it directly)
- Test: `tests/test_hardening.py`

**Interfaces:**
- Add `create_http_app() -> Starlette` that returns FastMCP's Streamable HTTP app with a middleware requiring `X-GitLab-Token` for requests to the MCP endpoint.
- `main()` selects `stdio` or `streamable-http` from `MCP_TRANSPORT`; the default remains stdio.
- HTTP host/port come from `MCP_HTTP_HOST` (default `127.0.0.1`) and `MCP_HTTP_PORT` (default `8000`). Set FastMCP `stateless_http=True` before constructing the HTTP app; it does not alter stdio behavior.
- Middleware returns HTTP 401 with a fixed, sanitized error for a missing/blank header. It never logs or echoes the value; `OPTIONS` may pass through.

- [ ] Add an integration test proving an unauthenticated initialize/list request gets HTTP 401 before FastMCP responds.
- [ ] Run the new integration test and confirm it fails against the current stdio-only server.
- [ ] Implement `create_http_app`, transport selection, stateless mode, and configurable loopback bind.
- [ ] Add integration tests proving a non-empty header reaches FastMCP on initialize and tool-list requests. A scoped GitLab tool call is verified in Task 4 after request context is passed to handlers.
- [ ] Verify default `main()` still selects stdio and HTTP mode does not reuse stateful MCP session credentials.
- [ ] Run focused HTTP tests and existing `tests/test_entrypoint.py`.
- [ ] Commit Task 3 as `feat: add authenticated Streamable HTTP transport`, staging only its implementation and tests.

### Task 4: Pass request context through tools and resources

**Files:**
- Modify: `src/gitlab_ci_mcp/tools/pipelines.py`
- Modify: `src/gitlab_ci_mcp/tools/schedules.py`
- Modify: `src/gitlab_ci_mcp/tools/mrs.py`
- Modify: `src/gitlab_ci_mcp/tools/branches_tags.py`
- Modify: `src/gitlab_ci_mcp/tools/repo.py`
- Modify: `src/gitlab_ci_mcp/resources.py`
- Test: `tests/test_hardening.py`, `tests/test_tools_mocked.py`, `tests/test_smoke.py`

**Interfaces:** Add an optional injected `ctx: Context | None = None` argument to every GitLab tool and call `get_ci(project_path, ctx=ctx)`. FastMCP excludes `ctx` from input schemas. Keep the two fixed resources as static registrations; HTTP middleware scopes their request PAT with a task-local ContextVar because a Context argument would convert fixed resources into resource templates. Preserve strict/legacy behavior.

- [x] Add a test that invokes a real registered GitLab tool through an HTTP MCP client with PAT A and proves the mocked GitLab manager receives A.
- [x] Add a concurrent two-user integration test for the same project, with different PATs and different simulated permissions; assert no client, result, or authorization state crosses between calls.
- [x] Run these tests and confirm they fail before request context is threaded through all entry points.
- [x] Add context injection and pass it to the client factory in every GitLab tool. Preserve static resource registration by using an HTTP request-local ContextVar for fixed resources; verify concurrent isolation. Preserve existing tool schemas and direct-call defaults.
- [x] Add assertions that `ctx` is absent from all generated input schemas and that fixed resources still fail before GitLab access in strict mode.
- [x] Run the complete mocked-tool, entrypoint, and hardening test files.
- [x] Commit Task 4 as `feat: route request PATs through GitLab tools`, staging only its implementation and tests.

### Task 5: Docs, deployment metadata, and issue updates

**Files:**
- Modify: `README.md`
- Modify: `docs/claude-code.md`
- Modify: `docs/per-user-auth.md`
- Modify: `server.json`
- Modify: GitHub issue #4 comment

- [x] Document local stdio and remote HTTP configuration separately, including `MCP_TRANSPORT`, bind/port, `X-GitLab-Token`, HTTPS/reverse-proxy redaction, token scopes, and fixed-resource behavior.
- [x] Add a Claude Code configuration example with the PAT supplied through a custom header and a secret/environment expansion mechanism; never put an actual credential in docs or committed JSON.
- [x] Update `server.json` environment metadata to explain conditional `GITLAB_TOKEN` use and add HTTP transport/host/port settings.
- [x] Replace the obsolete OAuth-only blocker document with the selected direct-PAT model, constraints, lifecycle, and remaining limitations.
- [x] Add an issue #4 comment explaining implementation and custom-header tradeoffs; keep issue state accurate.
- [ ] Commit Task 5 as `docs: document shared MCP PAT authentication`, staging the updated docs, server metadata, design, and implementation plan.

### Task 6: Versioned release and full verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/gitlab_ci_mcp/__init__.py`
- Modify: `server.json`
- Modify: version assertions in `tests/test_hardening.py` if needed
- Verify: `.github/workflows/publish.yml`, `.github/workflows/test.yml`

- [ ] Bump package version from `0.5.4` to `0.5.5` in all version authorities and confirm the update checker reports the installed version dynamically.
- [ ] Commit Task 6 release metadata as `release: 0.5.5` after updating version tests.
- [ ] Run pytest on Python 3.10, 3.11, and 3.12; run Ruff; build sdist and wheel; validate server.json; run `git diff --check`.
- [ ] Inspect the exact diff and run an independent security-focused review for credential leakage, cache isolation, stateless HTTP behavior, and workflow permissions.
- [ ] Commit in logical conventional commits, stage only intended project files, and confirm the resulting branch contains the entire approved hardening + PAT HTTP feature.
- [ ] Push the feature branch, open a PR against `main`, and wait for the GitHub Python 3.10–3.12 matrix to pass.
- [ ] Merge the PR after checks pass. If GitHub or a check blocks merging, report the exact blocker without bypassing it.
- [ ] Confirm `main` contains the merged commit; push tag `v0.5.5` only after verifying the tag matches package metadata and the PyPI publish workflow is ready.
- [ ] Wait for the tag workflow's pytest, Ruff, version check, build, and PyPI publish result. Report release complete only after the publish job succeeds.

## Self-review

- Spec coverage: transport/default behavior (Tasks 2–3), request PAT flow and client isolation (Tasks 2 and 4), static resource boundary and project scope (Task 4), documentation/issue (Task 5), and release verification/merge/tag publication (Task 6).
- Review Focus items are pinned to tests in Tasks 2–4.
- Cache key and TTL values are exact and consistent with the design constraints.
- The HTTP app middleware authenticates before MCP handling; tool context carries the same request's headers to the GitLab client factory.
- The plan includes the existing approved hardening changes from the detached worktree and does not rely on the stale local `main` branch.
