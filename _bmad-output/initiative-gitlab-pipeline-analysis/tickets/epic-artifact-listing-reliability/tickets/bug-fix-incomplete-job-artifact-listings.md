---
id: 1
type: bug
title: "Fix incomplete job artifact listings"
parent: epic-artifact-listing-reliability
covers: [R1]
after: []
refined: true
hitl: false
risk: high
severity: P2
---

# Fix incomplete job artifact listings

## Description

The reported job-artifact list call fails with `ChunkedEncodingError`, while selected files from that job can still be read. Make the list call return a complete inventory or a precise bounded failure; an interrupted response must never appear to mean that there are no artifacts.

## Reproduction

1. In project `enablement-platform/integration-tests/performance/gatling-my-mts`, call `gitlab_list_job_artifacts` for job `132345155`; the reported result is `ChunkedEncodingError: Connection broken: IncompleteRead(0 bytes read, 2 more expected)`.
2. Repeat the same read-only call; the reported error repeats.
3. Read `load-report.json`, `nightly-preflight.json`, `allure-upload-status.json`, `allure-readback-status.json`, and `known-defects.json` from that job; the reported selected-file reads succeed.
4. Call the list tool for `TestStart` job `132345154`; the reported result is that no downloadable archive exists.

These live observations are from the supplied report and have not been replayed in this session. Local regression tests must reproduce the incomplete stream through the current manager/tool path and exercise both the tree API and ZIP fallback paths; the live failing endpoint is not yet known.

## Cause Hypothesis

The current manager builds the list from the GitLab artifact-tree iterator and falls back to reading the ZIP archive after a tree `404`. A `ChunkedEncodingError` during either iteration appears able to escape without being converted into a bounded artifact-listing result. The session cannot prove which endpoint failed for job `132345155` because its connected MCP does not expose artifact tools.

## Acceptance Criteria

1. **A complete retry or explicit incomplete-response failure is returned**
   **Given** a tree listing or ZIP response is interrupted by `ChunkedEncodingError`
   **When** `gitlab_list_job_artifacts` reads the response
   **Then** it retries only within the configured finite limit and returns a complete inventory from a successful attempt or a bounded incomplete-response error, never a partial or empty success
2. **Permanent outcomes remain distinct and are not retried**
   **Given** GitLab reports no downloadable archive, an expired archive, access denied, or a missing job
   **When** the list tool handles the response
   **Then** it returns the specific bounded outcome for that case and does not retry it as a transient transfer failure
3. **Corrupt archive data is explicit**
   **Given** the tree endpoint is unavailable and the archive response is malformed or truncated without a recoverable transfer
   **When** the list tool parses it
   **Then** it reports a bounded corrupt/incomplete archive error and returns no partial entries
4. **Valid inventories remain complete and safe**
   **Given** a complete tree response or valid ZIP archive
   **When** the list tool returns its result
   **Then** every safe file and directory has the correct relative path, type, and size, unsafe paths are excluded, and no archive member is extracted to disk
5. **Existing selected-file reads keep their behavior**
   **Given** UTF-8 text, oversized text, binary data, or invalid UTF-8 in a selected artifact
   **When** `gitlab_get_job_artifact` reads it
   **Then** its existing status, limit, truncation, and content behavior remains unchanged
6. **Resource and transfer limits remain bounded**
   **Given** a tree listing or ZIP archive reaches the configured response/archive limit or the request times out
   **When** the list operation completes
   **Then** the tool returns an explicit bounded failure without unbounded memory growth, extraction, or retries, and tests cover the size, timeout, and attempt limits
7. **The local installed MCP is verified before R2 starts**
   **Given** focused and repository tests pass
   **When** this worktree package is installed into an isolated local environment and its MCP interface is inspected and exercised against the test transport
   **Then** both artifact tools are present, the listing regression behavior is verified, and no version bump or package release has happened yet

## Boundaries

- Do not change pipeline, job, deployment, workload, or live artifact state.
- Do not change `gitlab_get_job_artifact` semantics or the package version during this increment.
- Errors and test output must not contain the GitLab token or authorization headers.

## References

- parent — `_bmad-output/initiative-gitlab-pipeline-analysis/tickets/epic-artifact-listing-reliability/epic-artifact-listing-reliability.md`, R1 and Constraints.

## Notes

- Decision: 2026-11-25 — Use one bounded retry for confirmed incomplete streaming responses; do not retry missing archives, permission errors, missing jobs, or malformed ZIP content.
- Decision: 2026-11-25 — The owner approved implementing R1 under these criteria, requires the local install/MCP gate before R2, and authorized one final package release after R1–R6.
- Decision: 2026-11-25 — Keep the unresolved live endpoint as a non-blocking Open question rather than an entry `unknown`: the local work can exercise both tree and ZIP paths, while live acceptance stays INCONCLUSIVE.
- Open question: The endpoint that failed in the reported live call (artifact tree or ZIP fallback) is unknown until an authorized artifact-listing MCP tool is available; exercise both locally and keep live acceptance INCONCLUSIVE.
- Risk: high, because a false empty inventory could mislead incident investigation. Extra check: verify the malicious ZIP traversal case remains excluded and no archive member is extracted.
- Source path to preserve: `/opt/develop/aiqa/mcps/gitlab-ci-mcp/docs/requirements/job-artifact-listing-fix-prompt.md` remains local and must not be changed or committed.
