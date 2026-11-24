---
id: 3
type: epic
title: "Pipeline and deployment diagnosis"
parent: initiative-gitlab-pipeline-analysis
covers: ["R3", "R4", "R5", "R6"]
sources: ["_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md"]
companions: []
after: ["epic-ci-config-lint"]
refined: false
risk: high
---

# Pipeline and deployment diagnosis

## Description

Extend the MCP's read-only evidence path from job and downstream state through test failures, environment deployment history, and bounded job logs. Deliver its four capabilities in the initiative's R3–R6 order.

## Outcome

An engineer can follow a failing or delayed deployment through its authoritative pipeline, job, test, environment, and log evidence.

## Done when

- Job/downstream state, test reports, deployment history, and ranged logs each return bounded evidence and name unavailable information explicitly.
- Job results expose allowed-failure, retry, queue/resource wait, and downstream states with authoritative links; test reports distinguish summary/details and report artifacts; deployment history correlates environment/status with pipeline/job/ref/SHA when available; log responses carry continuation offsets and truncation state.
- The four capabilities are integrated and verified together as one diagnosis increment.
- This increment is included in the single reviewed package release after R1–R6 are complete.

## Boundaries

This epic owns pipeline/job details, child pipeline navigation, test reports, deployment history, and job trace ranges. It does not mutate pipelines, jobs, deployments, or live artifacts. R3, R4, R5, and R6 are implemented in that order.

## References

- parent — `_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md`, R3–R6 and Constraints.

## Notes

- Decision: 2026-11-25 — Tracer bullet: traverse one pipeline's job details and any accessible child pipeline through the manager, typed output, MCP tool, and tests; then deliver test reports, deployment history, and ranged logs in R4–R6 order.
- Waits on epic-ci-config-lint because: the shared manager, typed responses, and read-only tool registration surface must be integrated before this epic starts.
