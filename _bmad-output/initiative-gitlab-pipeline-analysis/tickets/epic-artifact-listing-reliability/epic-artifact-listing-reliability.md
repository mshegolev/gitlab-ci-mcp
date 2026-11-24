---
id: 1
type: epic
title: "Reliable job artifact listing"
parent: initiative-gitlab-pipeline-analysis
covers: ["R1"]
sources: ["_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md"]
companions: []
after: []
refined: false
risk: high
---

# Reliable job artifact listing

## Description

Correct the existing artifact inventory path so a complete list is returned or GitLab's missing, denied, or incomplete response is named accurately. This is the first increment because later diagnostic work depends on reliable artifact access.

## Outcome

An engineer can distinguish a job with no downloadable archive from a failed or incomplete artifact response.

## Done when

- The artifact-listing failure modes in R1 are covered by regression checks and never produce a false empty or partial success.
- The existing selected-file reader retains its bounded UTF-8 behavior and safety checks.
- After local tests pass, a package installed from this worktree folder into an isolated environment exposes and passes verification for the artifact tools.
- This increment is included in the single reviewed package release after R1–R6 are complete.

## Boundaries

This epic owns job-artifact inventory reliability and preserves the existing file reader. It does not add CI lint, test-report APIs, deployment history, pipeline/job execution, or live artifact mutation.

## References

- parent — `_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md`, R1 and Constraints.

## Notes

- Decision: 2026-11-25 — Tracer bullet: reproduce an incomplete response through the artifact-listing path, return an explicit bounded failure or complete listing, and pass local install/MCP verification before epic 2 starts.
