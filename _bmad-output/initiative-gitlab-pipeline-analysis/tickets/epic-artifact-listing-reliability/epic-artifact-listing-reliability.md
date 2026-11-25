---
id: 1
type: epic
title: "Reliable job artifact listing"
parent: initiative-gitlab-pipeline-analysis
covers: ["R1"]
sources: ["_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md"]
companions: []
after: []
refined: true
status: done
risk: high
---

# Reliable job artifact listing

## Description

Correct the existing artifact inventory path so a complete list is returned or GitLab's missing, denied, or incomplete response is named accurately. This is the first increment because later diagnostic work depends on reliable artifact access.

## Outcome

An engineer can distinguish a job with no downloadable archive from a failed or incomplete artifact response.

## Requirements

- **R1 (parent R1):** Job artifact listing returns the complete bounded inventory or an explicit structured failure; an incomplete transport response must never appear as a successful empty or partial list.

## Done when

- The artifact-listing failure modes in R1 are covered by regression checks and never produce a false empty or partial success.
- Missing archive, permission denial, missing job, incomplete transfer, and corrupt archive have distinguishable bounded outcomes; retry is finite and limited to the confirmed transient response failure.
- The existing selected-file reader retains its bounded UTF-8 behavior and safety checks.
- After local tests pass, a package installed from this worktree folder into an isolated environment exposes and passes verification for the artifact tools.

## Constraints

- No GitLab job, pipeline, deployment, or live artifact is changed; no real credentials enter tests or results.
- Archive paths remain validated, archives are never extracted to disk, and response size, timeout, and memory stay bounded.
- Successful `gitlab_get_job_artifact` behavior remains unchanged.

## Boundaries

This epic owns job-artifact inventory reliability and preserves the existing file reader. It does not add CI lint, test-report APIs, deployment history, pipeline/job execution, or live artifact mutation.

## References

- parent — `_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md`, R1 and Constraints.

## Notes

- Decision: 2026-11-25 — Tracer bullet: reproduce an incomplete response through the artifact-listing path, return an explicit bounded failure or complete listing, and pass local install/MCP verification before epic 2 starts.
- Open question: The current connected MCP does not expose artifact tools, so the live job's failing endpoint (tree listing or ZIP fallback) is unknown. This does not block local implementation because tests will exercise both paths; live acceptance remains INCONCLUSIVE until an authorized artifact-listing tool is available.
