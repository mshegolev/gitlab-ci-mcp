# Per-user GitLab PAT authentication

The shared deployment mode uses each MCP client's GitLab Personal Access Token
(PAT) directly. It does not implement OAuth login or exchange a token issued for
the MCP server.

## Local mode

`MCP_TRANSPORT` defaults to `stdio`. In this mode the process reads one
`GITLAB_TOKEN` and uses it for every request. This remains the supported local
single-user setup.

## Shared HTTP mode

Set `MCP_TRANSPORT=streamable-http` and run the server behind HTTPS. Each
request to `/mcp` must carry the calling user's token in `X-GitLab-Token`.
The server uses that value only for the GitLab API calls in that request. The
PAT is never a tool argument and is not returned to the model. HTTP mode does
not fall back to the process `GITLAB_TOKEN`.

The header itself is the credential: GitLab determines the caller's identity
and permissions when the API request is made. The HTTP boundary checks only
that a non-empty header is present; it does not call GitLab during initialize
or tool discovery. Therefore an invalid or revoked PAT may connect and list
tools, but its GitLab operation will fail with GitLab's authorization error.

This is custom header authentication, not MCP's standard OAuth authorization
flow. Clients must support sending a configured `X-GitLab-Token` header on
every request. Do not put the PAT in the URL, query string, prompt, tool
arguments, or shared repository configuration. Use each user's own PAT and
GitLab access controls. The current tool set includes write operations, so the
PAT needs GitLab's `api` scope; a read-only scope is insufficient for writes.

Example server environment:

```bash
MCP_TRANSPORT=streamable-http
MCP_HTTP_HOST=127.0.0.1
MCP_HTTP_PORT=8000
GITLAB_URL=https://gitlab.example.com
```

The server binds to loopback by default. To make it reachable to a team, expose
it through a reverse proxy or an equivalent network boundary. Require HTTPS,
restrict network access, redact `X-GitLab-Token` from proxy access logs,
tracing, and error reports, and do not expose the unencrypted uvicorn listener
to an untrusted network. The MCP endpoint path defaults to `/mcp`.

For Claude Code, configure a custom header using a user-owned secret
environment variable. For example, in a shell where `GITLAB_PAT` is already
provided by a secret manager:

```bash
claude mcp add --transport http \
  --header "X-GitLab-Token: ${GITLAB_PAT}" \
  gitlab https://mcp.example.com/mcp
```

Do not run this command with a literal PAT in shell history. Other MCP clients
need an equivalent per-request custom header configuration.

## Project scope and resources

GitLab tools require an explicit `project_path` by default. A deployment can
opt into the legacy `GITLAB_PROJECT_PATH` fallback with
`GITLAB_ALLOW_DEFAULT_PROJECT=true`. The two fixed resource URIs cannot accept
a project argument and therefore remain available only through that explicit
legacy fallback. In HTTP mode, resource reads use the PAT from that HTTP
request and remain isolated from concurrent requests.

## Credential handling and limits

- The server does not persist PATs. It keeps a bounded, process-local cache of
  GitLab clients, keyed by GitLab URL, project, and an HMAC fingerprint of the
  PAT. Raw PAT values are not cache keys.
- The cache is capped at 128 clients, evicts least-recently-used clients, and
  expires idle entries after 30 minutes. Shutdown closes cached HTTP sessions.
- GitLab owns token expiry and revocation. Revoke a PAT in GitLab to stop future
  API calls; rotate the client configuration when replacing it. A cached
  session does not override GitLab's token authorization.
- A token must not be shared across people if distinct GitLab permissions are
  required. The server does not provide a separate team identity provider or
  credential vault.
- The transport rejects missing/blank headers but does not validate token
  validity until a GitLab request. Operators must protect their HTTPS
  termination and logs accordingly.

## Verification

The test suite exercises the real Streamable HTTP endpoint with two concurrent
PATs against the same project. The fake GitLab API returns different results
for the two tokens and verifies that neither client nor response crosses the
user boundary. This validates server-side routing and cache isolation; it is not
a live GitLab deployment test.
