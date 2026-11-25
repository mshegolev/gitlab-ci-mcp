---
title: 'Fix incomplete job artifact listings'
type: 'bugfix'
ticket: '1'
created: '2026-11-25'
status: 'built'
baseline_revision: '8edbf91e34442a44d729bcf43778ed52c97af585'
route: 'full'
route_source: 'auto'
risk: 'high'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The reported `gitlab_list_job_artifacts` call fails with `ChunkedEncodingError` for job 132345155 even though selected files can be read. A separate job, 132345154, has no downloadable archive; the list tool must distinguish these outcomes and never imply that an interrupted response means no artifacts.

**Approach:** Reproduce incomplete tree-pagination and ZIP-body reads through local regression tests. Retry one complete listing attempt only for `ChunkedEncodingError`, discard partial state, and return a bounded explicit error if the retry also fails. Preserve safe paths, archive limits, and selected-file behavior.

## Boundaries & Constraints

**Always:** Keep project scoping; preserve the 30-second request timeout and 128 MiB archive limit; cap inventory output at 256,000 encoded bytes and fail explicitly above it; never extract an archive; keep token and authorization data out of errors and tests.

**Never:** Trigger or mutate a GitLab job, pipeline, deployment, workload, or live artifact. Do not change `gitlab_get_job_artifact` behavior. Do not bump the package version or release during R1; one package release happens only after R1–R6.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Complete tree | All tree pages arrive | Complete safe path/type/size inventory | No error |
| Tree stream interrupted once | `ChunkedEncodingError` during a page | Fresh full attempt returns complete inventory | At most one retry; discard first-attempt entries |
| ZIP stream interrupted once | Tree returns 404, archive body raises `ChunkedEncodingError` | Fresh full attempt returns complete ZIP inventory | At most one retry; close each response |
| Repeated interrupted stream | Both attempts fail with `ChunkedEncodingError` | No listing is returned | Bounded incomplete-response error, no partial entries |
| Permanent or missing result | 403, missing job, no archive, or expired archive | Distinct existing/actionable outcome | No transient retry |
| Corrupt ZIP or timed out response | Invalid/truncated ZIP or request timeout | No listing is returned | Bounded corrupt or timeout error; no retry |
| Inventory exceeds output cap | Tree/ZIP metadata exceeds 256,000 encoded bytes | No partial listing is returned | Explicit limit error |

</frozen-after-approval>

## Code Map

- `src/gitlab_ci_mcp/ci_manager.py` — `_download_artifacts_archive` streams with a 30-second timeout and 128 MiB cap; `list_job_artifacts` iterates the paginated tree, falls back to ZIP only on tree HTTP 404, and currently catches only `BadZipFile`. A failure after partial iteration escapes the attempt.
- `src/gitlab_ci_mcp/tools/pipelines.py` — `gitlab_list_job_artifacts` runs the manager in a worker thread and sends exceptions through `output.fail`.
- `src/gitlab_ci_mcp/errors.py` and `src/gitlab_ci_mcp/output.py` — `ArtifactOperationError` is rendered as a safe tool error; generic exceptions expose their message, so transport failures must be wrapped with bounded text.
- `tests/test_job_artifacts.py` — existing tree success, ZIP fallback/path traversal, missing/expired archive, UTF-8 truncation, binary, and invalid-UTF-8 tests. Patch `http_list` with a generator that yields one item and then raises the real `requests.exceptions.ChunkedEncodingError`; use a fake streamed response for ZIP-body interruption.
- `pyproject.toml` — package already depends on `python-gitlab`; declare Requests directly if production code imports its exception classes, and keep the 0.5.6 version unchanged for this increment.
- Live route for job 132345155 is not known: the connected MCP does not expose artifact tools. Exercise both local paths and report live acceptance as INCONCLUSIVE.

## Tasks & Acceptance

**Execution:**
- [x] `tests/test_job_artifacts.py` — first add failing regression coverage for tree pagination and mid-body ZIP interruption, one successful bounded retry, repeated failure with no partial list, permanent 403/404 cases, corrupt ZIP, timeout, output/archive size bounds, response closure, traversal safety, and unchanged file reads.
- [x] `src/gitlab_ci_mcp/ci_manager.py` — make each list attempt atomic, retry only `ChunkedEncodingError` once from the start, discard partial entries, normalize exhausted/incomplete/corrupt/timeout outcomes, and enforce the inventory output cap.
- [x] `pyproject.toml` — declare the transport exception dependency directly if the manager imports `requests.exceptions`; do not change the package version.
- [x] Isolated local install — after focused and repository tests passed, installed this worktree from its folder into `/tmp/gitlab-ci-mcp-r1-env`, verified both artifact tools through MCP `tools/list`, and exercised listing through the test transport before R2.

**Acceptance Criteria:**
- Given a one-time chunked interruption in either tree or ZIP reading, when listing retries, then it returns a complete inventory from a fresh attempt and never includes entries from the failed attempt.
- Given repeated chunked interruption, timeout, corrupt ZIP, or output/archive limit overflow, when listing fails, then it returns a bounded explicit error and no partial success.
- Given a missing job, missing archive, expired archive, or 403, when listing responds, then its existing distinct outcome is preserved and no transient retry occurs.
- Given existing successful `gitlab_get_job_artifact` fixtures, when the repository tests run, then UTF-8 truncation, binary rejection, and invalid-UTF-8 behavior are unchanged.
- Given local focused and full tests pass, when the local folder install is inspected and called through the MCP interface, then both artifact tools are available and the listing regression passes before R2 begins.

## Implementation Notes


## Plan Change Log


## Review Triage Log

- patch — The listing cap previously measured only the manager's compact inventory while the MCP response duplicated paths in structured content and Markdown. Verified in `tools/pipelines.py` and `formatters.job_artifacts`; added a final serialized response-size check and regression test.
- patch — A non-numeric `Content-Length` previously escaped as `ValueError` from `int()`. Verified the archive downloader's generic error path; invalid headers now produce a bounded `ArtifactOperationError`, with a response-close regression test.
- false — The installed MCP/tool-transport acceptance criterion was reported unmet, but after editable installation `tools/list` returned both artifact tools and `test_list_job_artifacts_tool_returns_structured_content` passed against the `responses` test transport; the final full suite passed 121 tests. The claim is disproved by direct run evidence.


## Design Notes

The retry boundary should cover the whole list operation, including consuming every tree page, the 404-to-ZIP fallback, and parsing. This ensures any partial list is thrown away. Retry only the confirmed `ChunkedEncodingError`; keep 403/404, no archive, timeout, malformed ZIP, and size-limit outcomes bounded and non-retrying. The 256,000-byte inventory cap reuses the existing job-log response cap; an over-cap inventory must fail explicitly rather than truncate.

## Verification

**Commands:**
- `PYTHONPATH=src <isolated-env>/bin/python -m pytest -q tests/test_job_artifacts.py` — expected: focused artifact tests pass.
- `PYTHONPATH=src <isolated-env>/bin/python -m pytest -q` — expected: full repository suite passes.
- `<isolated-env>/bin/ruff check .` — expected: no lint findings.
- `git diff --check` — expected: no whitespace errors.
- After the tests pass, install the local folder into `<isolated-env>` with `uv pip install --python <isolated-env>/bin/python -e .`; inspect `tools/list` through a local MCP client and call the artifact-listing handler against the test transport — expected: both tools are present and the installed operation returns a complete list or a precise error.
