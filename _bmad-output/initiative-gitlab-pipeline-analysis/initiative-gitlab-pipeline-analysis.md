---
type: initiative
title: "GitLab pipeline analysis and deployment diagnosis"
sources: ["docs/requirements/pipeline-analysis-roadmap.md"]
companions: []
after: []
risk: high
---

# GitLab pipeline analysis and deployment diagnosis

## Description

Make this MCP more reliable for artifact inspection and add ordered, evidence-based capabilities for validating GitLab CI configuration and diagnosing pipeline, test, deployment, and log failures. The roadmap is derived from the approved capability research and the artifact-listing investigation input.

## Outcome

An engineer can validate CI configuration and inspect deployment failures using bounded GitLab evidence, with missing evidence and uncertainty named explicitly.

## Requirements

- **R1 (R1):** Job artifact listing returns a complete bounded inventory or an explicit structured failure; incomplete responses never become empty or partial success.
- **R2 (R2):** CI config lint reports validity, errors, warnings, and bounded merged configuration or generated jobs while clearly distinguishing simulation from execution and deployment.
- **R3 (R3):** Pipeline diagnosis exposes job and downstream evidence sufficient to distinguish execution, allowed-failure, retry, queue/resource-wait, and child-pipeline states; unavailable evidence remains unknown.
- **R4 (R4):** Test report inspection returns bounded summaries and failed-test details, and distinguishes report artifacts from ordinary archive files.
- **R5 (R5):** Deployment history is searchable by environment and status and correlates to pipeline/job/ref/SHA when available, without mutating deployments.
- **R6 (R6):** Job logs can be read in bounded ranges with explicit continuation offsets and truncation metadata.

## Constraints

- All diagnosis calls remain read-only; no pipeline/job execution or retry, manual job play, or deployment mutation. (pipeline-analysis-roadmap.md Constraints)
- Missing, inaccessible, expired, truncated, and not-requested evidence remain distinct; status alone is not a root-cause diagnosis. (pipeline-analysis-roadmap.md Constraints)
- Preserve project scoping, caller permissions, bounded responses, and existing secret-handling behavior. (pipeline-analysis-roadmap.md Constraints)
- No live pipeline/job mutation, workload, deployment, or artifact mutation is allowed; one package release is authorized only after all six requirements and the R1 local-install gate. (pipeline-analysis-roadmap.md Constraints)

## Done when

- Each requirement has an implemented, reviewed increment in the approved order.
- Local automated checks demonstrate complete-or-explicitly-failed behavior for the supported GitLab responses, including relevant negative paths.
- The published MCP schema exposes the new read-only capabilities with bounds, permissions, and uncertainty described accurately.
- Before R2 begins, R1 passes local tests and a package installed from this worktree folder into an isolated environment passes MCP verification.
- One reviewed package release occurs only after R1–R6 are complete.
- No diagnosis result claims a live GitLab outcome that was not verified through an authorized read-only call.

## Boundaries

The initiative changes the GitLab CI MCP interface and its GitLab API integration. It does not change GitLab pipelines, jobs, deployments, artifacts, or project configuration.

- Touch point: artifact inventory and selected files inside job artifacts — owner `epic-artifact-listing-reliability`.
- Touch point: CI config lint and simulation — owner `epic-ci-config-lint`.
- Touch point: pipeline/job tools, typed responses, and downstream pipeline traversal — owner `epic-pipeline-deployment-diagnosis`.
- Touch point: GitLab test report endpoints and report artifacts — owner `epic-pipeline-deployment-diagnosis`.
- Touch point: deployment history API — owner `epic-pipeline-deployment-diagnosis`.
- Touch point: job trace API — owner `epic-pipeline-deployment-diagnosis`.

Tracer path: reproduce and fix the existing artifact listing failure; then add CI lint, richer pipeline/job diagnosis, test reports, deployment history, and bounded log ranges in that order, validating each response path with bounded tests and explicit failure states.

## References

- pipeline analysis roadmap — `docs/requirements/pipeline-analysis-roadmap.md`, Requirements and Constraints.

## Notes

- Decision: 2026-11-25 — Keep the five research capabilities in their proposed order and place the newly supplied artifact-listing reliability fix first because it repairs an existing diagnostic function used by later artifact/report work.
- Decision: 2026-11-25 — The existing MCP and packaging pipeline are already established, so this initiative does not add a platform-baseline epic.
- Decision: 2026-11-25 — Draft three epics: artifact-listing reliability, CI config lint, and a pipeline/deployment diagnosis epic containing job graph, test reports, deployment history, and log ranges in the requested order. The first two have distinct early-usable outcomes; the latter four serve one incident-diagnosis outcome and share the same pipeline manager and tools. Chain epics to prevent concurrent edits to shared integration points.
- Decision: 2026-11-25 — After R1's local tests, install this worktree's package into an isolated local environment and verify the installed MCP before starting R2; after R2–R6 are complete, push, merge the reviewed change, and publish one package release.
