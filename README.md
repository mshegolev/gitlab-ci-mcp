# gitlab-ci-mcp

MCP server for GitLab CI/CD. Lets an LLM agent (Claude Code, Cursor, OpenCode, DevX Agent, etc.) work with pipelines, jobs, schedules, branches, tags, merge requests and repository files.

Python, [FastMCP](https://github.com/modelcontextprotocol/python-sdk), stdio transport.

Works with any GitLab — SaaS `gitlab.com` or self-hosted / on-prem. Designed with corporate networks in mind: configurable `NO_PROXY` handling, optional SSL-verify toggle, per-project scoping via env vars.

## Design highlights

- **Tool annotations** — every tool carries `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint` so MCP clients can classify operations (e.g. ask for confirmation only on destructive ones like `gitlab_merge_mr`, `gitlab_delete_schedule`).
- **Dual response format** — `response_format='markdown'` (default) returns a compact table tuned for agent context; `response_format='json'` returns the raw structure.
- **Structured errors** — authentication, 404, 403, rate-limit, missing-env errors are converted to actionable messages (e.g. _"GitLab authentication failed… verify GITLAB_TOKEN has `api` scope"_) instead of raw tracebacks.
- **Pydantic input validation** — every argument has typed constraints (ranges, lengths, literals) auto-exposed as JSON Schema.
- **Project scoping per call** — every tool accepts an optional `project_path` that overrides `GITLAB_PROJECT_PATH` for cross-project queries.

## Features

23 tools covering the everyday CI/CD surface:

**Pipelines**
`gitlab_list_pipelines` · `gitlab_get_pipeline` · `gitlab_get_pipeline_jobs` · `gitlab_get_job_log` · `gitlab_trigger_pipeline` · `gitlab_retry_pipeline` · `gitlab_cancel_pipeline` · `gitlab_pipeline_health`

**Schedules**
`gitlab_list_schedules` · `gitlab_create_schedule` · `gitlab_update_schedule` · `gitlab_delete_schedule`

**Branches & tags**
`gitlab_list_branches` · `gitlab_list_tags` · `gitlab_compare_branches`

**Merge requests**
`gitlab_list_merge_requests` · `gitlab_get_merge_request` · `gitlab_get_merge_request_changes` · `gitlab_create_merge_request` · `gitlab_merge_mr`

**Repository & project**
`gitlab_get_file` · `gitlab_list_repository_tree` · `gitlab_project_info`

### Pipeline health report

`gitlab_pipeline_health` returns a ready-to-read summary over 7/30 days:

```
Last 7d:  96.4%  up   | 27/28 success
Last 30d: 92.1%       | 105/114 success
Last 10:  success success success failed success ...
```

Handy for on-call / triage: `покажи health master за последние 7 дней`.

## Installation

Requires Python 3.10+.

```bash
# via uvx (recommended)
uvx --from gitlab-ci-mcp gitlab-ci-mcp

# or via pip/pipx
pipx install gitlab-ci-mcp
```

## Configuration

All config is via environment variables:

| Variable | Required | Description |
| --- | --- | --- |
| `GITLAB_URL` | **yes** | Base URL, e.g. `https://gitlab.example.com` |
| `GITLAB_TOKEN` | **yes** | Personal Access Token with `api` scope |
| `GITLAB_PROJECT_PATH` | **yes** | Default project, e.g. `my-org/my-repo` |
| `GITLAB_SSL_VERIFY` | no | `true` (default) / `false` |
| `GITLAB_NO_PROXY_DOMAINS` | no | Comma-separated domains to add to `NO_PROXY` (useful in corp networks behind a local HTTP proxy — e.g. `.corp.example.com,gitlab.internal`) |

Every tool accepts an optional `project_path` arg that overrides `GITLAB_PROJECT_PATH` per call — useful for cross-project queries.

## Claude Code

```bash
claude mcp add gitlab uvx --from gitlab-ci-mcp gitlab-ci-mcp \
  --env GITLAB_URL=https://gitlab.example.com \
  --env GITLAB_TOKEN=glpat-xxxxxx \
  --env GITLAB_PROJECT_PATH=my-org/my-repo
```

Or in `~/.claude.json` / project `.mcp.json`:

```json
{
  "mcpServers": {
    "gitlab": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "gitlab-ci-mcp", "gitlab-ci-mcp"],
      "env": {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "${GITLAB_TOKEN}",
        "GITLAB_PROJECT_PATH": "my-org/my-repo",
        "GITLAB_SSL_VERIFY": "true"
      }
    }
  }
}
```

Check:

```bash
claude mcp list
# gitlab: uvx --from gitlab-ci-mcp gitlab-ci-mcp - ✓ Connected
```

## Cursor / OpenCode / DevX Agent

Same idea — point the MCP config to `uvx --from gitlab-ci-mcp gitlab-ci-mcp` with the env vars above. See each tool's own MCP config syntax.

## Example prompts

```
что сломалось в последнем pipeline master
```

```
покажи health master за 7 дней для проекта my-org/other-repo
```

```
создай MR из feature/foo в master с title "feat: foo"
```

```
покажи содержимое .gitlab-ci.yml из master
```

## Self-hosted GitLab behind a corporate proxy

When your laptop has a local HTTP proxy (e.g. `http://127.0.0.1:3128` for corp web access) but GitLab is on the intranet, the proxy intercepts and kills internal requests. Two options:

1. Set `GITLAB_NO_PROXY_DOMAINS` — the server will add them to `NO_PROXY` at startup **and clear `HTTP_PROXY`/`HTTPS_PROXY` from its own process** so they don't affect GitLab traffic.
2. Pass explicitly empty `HTTP_PROXY=""` etc. in the MCP `env` section.

## Development

```bash
git clone https://github.com/mshegolev/gitlab-ci-mcp
cd gitlab-ci-mcp
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Run the server directly (stdio transport, waits on stdin for MCP messages):

```bash
GITLAB_URL=... GITLAB_TOKEN=... GITLAB_PROJECT_PATH=... gitlab-ci-mcp
```

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Built on [python-gitlab](https://github.com/python-gitlab/python-gitlab) and the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
