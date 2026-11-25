# Pipeline analysis and deployment diagnosis roadmap

## Source

Approved by the project owner on 2026-11-25 from the GitLab MCP capability research. The implementation order below is intentional. The first item was added from the owner's local `job-artifact-listing-fix-prompt.md`; that prompt remains local and is not copied or committed.

## Requirements

### R1 — Reliable job artifact listing

Fix `gitlab_list_job_artifacts` so a complete listing of relative paths, sizes, and types is returned when available, and a bounded structured error is returned when it is not. A truncated or incomplete response must never be presented as an empty or partial successful listing. Distinguish missing archive, permission denial, missing job/file, and incomplete or corrupt response. Preserve bounded retries, timeout, memory/archive limits, safe ZIP path handling, project scoping, and the existing behavior of `gitlab_get_job_artifact`. Do not trigger or mutate GitLab jobs or pipelines. The supplied live observations (job 132345155 and job 132345154) are investigation inputs, not proof of root cause or a current-session reproduction.

### R2 — CI configuration lint and simulation

Add a read-only MCP capability to validate a candidate or repository `.gitlab-ci.yml` using GitLab CI Lint, including project includes and available configuration context. Return validity, errors, warnings, merged configuration and/or generated job details within explicit response limits. State clearly that simulation does not execute job scripts or deploy.

### R3 — Pipeline job and downstream diagnosis

Expose enough job evidence to distinguish execution failures, allowed failures, retry history, runner queue/resource waits, and child/downstream pipeline failures. Preserve links to the authoritative GitLab job and pipeline records, and label missing or inaccessible downstream data as unknown rather than successful.

### R4 — Test reports and report artifacts

Provide bounded access to test report summaries and failed test details, including available failure output or stack trace. Support GitLab report artifacts separately from files in the ordinary job artifact archive, with explicit limits and clear unavailable/expired states.

### R5 — Deployment history by environment

Provide read-only deployment history filtered by environment and status, with links or identifiers that correlate deployment, pipeline/job, ref, and commit SHA when GitLab returns them. Do not approve, create, retry, roll back, or otherwise mutate a deployment.

### R6 — Bounded job log ranges

Allow callers to read a bounded log range and continue from a returned offset, so a failure before the current tail can be inspected without fetching an unbounded trace. Report offsets, truncation, and limits explicitly.

## Constraints

- Diagnosis tools are read-only. They do not trigger or retry pipelines/jobs, play manual jobs, or mutate deployments.
- Missing, inaccessible, expired, truncated, and not-requested evidence are distinct outcomes; do not infer root cause from status alone.
- Keep project scoping, caller permissions, bounded payloads, and existing secret-handling behavior.
- Do not execute or mutate GitLab pipelines, jobs, deployments, workloads, or live artifacts.
- The owner authorized one package release only after R1–R6 are implemented and R1 passes local tests plus a local installation and MCP verification from this worktree folder.

## Scope

The six requirements are delivered in the order R1 through R6. After R1 passes local tests, install the package from this worktree folder into an isolated local environment and verify the installed MCP before beginning R2. After R2–R6 are complete, push the branch, merge the reviewed change, and publish one package release.
