# Shared GitLab CI MCP with per-user PATs

## Intent

Let a team run one remote GitLab CI MCP endpoint while each person supplies
their own GitLab personal access token (PAT). Every GitLab operation must use
the credential from that caller's HTTP request, so GitLab authorization and
audit identity remain the caller's. Keep the existing local stdio setup
available.

## Goals

- Add opt-in Streamable HTTP transport for one shared deployment.
- Accept a caller's GitLab PAT in `X-GitLab-Token` on every HTTP request that
  invokes a tool or reads a resource.
- Create/use clients isolated by GitLab URL, project path, and a keyed token
  fingerprint; never share one user's authenticated session with another.
- Avoid persistent PAT storage and never put PATs in a URL, MCP tool argument,
  response, log, or exception message.
- Preserve stdio + `GITLAB_TOKEN` as the default local setup.
- Document HTTPS proxy requirements, header redaction, PAT scopes, and client
  configuration.
- Finish the previously approved hardening work, then commit, push, open a PR,
  merge after required checks, and publish a versioned release if repository
  release gates permit it.

## Non-goals

- MCP OAuth, a separate identity provider, OAuth credential storage, or
  mapping one identity-provider subject to a GitLab account.
- Accepting a GitLab PAT as `Authorization: Bearer` for the MCP endpoint.
- Persisting, refreshing, rotating, or revoking a user's PAT on their behalf.
- Claiming that arbitrary MCP clients support custom headers.
- Deploying a public service or configuring DNS, certificates, firewall rules,
  or a reverse proxy on the owner's infrastructure.

## Approaches considered

1. **PAT in `X-GitLab-Token` over Streamable HTTP — selected.** This matches the
   request to use each person's existing GitLab PAT and avoids a server-side
   credential database. It is a custom header convention, so the client must
   support arbitrary HTTP headers and the endpoint must be protected by HTTPS.
2. **OAuth for MCP plus separate GitLab OAuth authorization.** This follows
   MCP's standard remote authorization flow and provides a validated identity,
   but requires an authorization server and GitLab OAuth grant lifecycle; it
   does not use the requested PAT directly.
3. **One stdio process per user.** This keeps the current transport and
   environment-token model but does not provide the requested shared URL.

The owner selected approach 1. MCP's standard `Authorization: Bearer` token
must be issued for the MCP server and cannot be treated as or forwarded as a
GitLab PAT. The PAT therefore uses the separate `X-GitLab-Token` header.

## Behavior and configuration

- `MCP_TRANSPORT=stdio` remains the default. `MCP_TRANSPORT=streamable-http`
  starts the remote endpoint; host defaults to `127.0.0.1`, and host and port
  are configurable and documented.
- HTTP mode requires `GITLAB_URL`. Each tool/resource call must include a
  non-empty `X-GitLab-Token`; it does not silently fall back to process-wide
  `GITLAB_TOKEN`.
- Require the header on every request to the MCP HTTP endpoint, including
  initialize, list, tool/resource, notification, and session-close requests.
  The custom header is supplied by the client on each request; never accept a
  token in a query string or MCP tool argument.
- Configure Streamable HTTP stateless mode so MCP session identifiers do not
  bind one user's conversation to another user's credential. Each request's
  PAT alone determines the GitLab client for that request.
- Stdio mode continues to use `GITLAB_TOKEN` and existing strict project
  scope behavior.
- `project_path` remains required unless the existing explicit legacy scope
  compatibility setting is enabled.
- Existing fixed resource URIs remain available only for the explicitly
  configured legacy default project. In strict mode they return the existing
  named scope error; tools continue to take explicit `project_path` values.
- The server returns a named authentication error for a missing PAT and a
  sanitized GitLab authorization error for invalid/revoked/under-scoped PATs.
- The update check remains separately opt-in through
  `MCP_GITLAB_UPDATE_CHECK_ENABLED` and runs only on explicit tool invocation.

## Credential handling and isolation

- Read the token from request context, not model-controlled tool arguments.
- Keep request authentication explicit: tool/resource handlers resolve their
  request context and pass the PAT to the GitLab client factory.
- Key client reuse by GitLab URL, project path, and an HMAC fingerprint made
  with a process-random key. Never use or log the raw token as a cache key.
- Bound the in-memory client cache and expire idle entries; close sessions on
  eviction and shutdown. The cache is process-local and not persistent.
- Every GitLab API request still uses the caller's PAT. GitLab remains the
  authority for membership, scopes, expiration, and revocation.
- Do not log incoming headers. Ensure token-bearing HTTP errors are sanitized
  before returning MCP content.
- Require HTTPS at the deployment edge. Documentation must warn operators to
  redact `X-GitLab-Token` in reverse-proxy, tracing, and access logs. Never
  encourage putting the token in query strings or URLs.
- The server binds to loopback by default. Remote deployment must explicitly
  configure its bind address and use a TLS-terminating reverse proxy/firewall;
  the application must not trust arbitrary forwarded-protocol headers.

## Acceptance checks

- A remote tool call with PAT A uses a GitLab client authenticated with A.
- Concurrent calls with PAT A and PAT B to the same project use distinct
  clients and cannot see each other's authorization context or cached data.
- A missing/empty header fails before any GitLab API request; an invalid PAT
  yields a named, sanitized failure.
- No PAT appears in captured logs, errors, tool output, URLs, or cache keys.
- Expired/evicted cache entries close their sessions; shutdown closes all
  remaining sessions.
- stdio still uses `GITLAB_TOKEN`; remote mode does not silently use it.
- HTTP transport can be exercised through an MCP client integration test, with
  explicit checks of request headers and concurrent user isolation.
- Existing project-scope, health, schedule, logs, MR, release-workflow, and
  update-check tests continue to pass.
- Run full tests on Python 3.10, 3.11, and 3.12; Ruff; build; and release
  workflow checks before merging/publishing.

## Release path

Use a feature branch based on current `origin/main`, preserve the primary
checkout, and include the previously approved hardening changes with this
feature. Commit and push the branch, open a PR, wait for repository-required
checks, and merge only when they pass and GitHub permits it. If the PyPI tag
workflow and version policy permit a patch release, bump the package version,
push the matching tag, and verify the publish workflow result. Do not claim a
release based only on a merged PR or local build.

## Builder decisions left open

- Select the maximum client-cache size and idle TTL from measured test/runtime
  needs; keep both bounded and configurable only if operations require it.
- Use the MCP Python SDK's supported Streamable HTTP entry point and request
  context APIs for the currently resolved compatible SDK version.
- Keep API exception text sanitized; return status/code and action guidance,
  not response bodies that may contain request data.

## Builder-check resolutions

- Static resource URIs retain their existing fixed-default semantics. They
  fail closed under strict scope and only work with the explicit default
  project compatibility opt-in; no new scope-less resource is introduced.
- Use stateless Streamable HTTP, so there is no reusable MCP session identity
  to bind or switch between PATs. Every HTTP request must carry its own PAT.
- Require `X-GitLab-Token` on every request to `/mcp`, not only tool calls.
