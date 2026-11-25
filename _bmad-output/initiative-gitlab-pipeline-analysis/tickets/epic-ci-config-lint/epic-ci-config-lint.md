---
id: 2
type: epic
title: "CI configuration lint and simulation"
parent: initiative-gitlab-pipeline-analysis
covers: ["R2"]
sources: ["_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md"]
companions: []
after: ["epic-artifact-listing-reliability"]
refined: true
risk: high
---

# CI configuration lint and simulation

## Description

Add read-only validation for a supplied CI configuration or a project configuration at a selected ref, returning lint diagnostics and bounded merged configuration or generated job details without executing jobs.

## Outcome

An engineer can catch CI configuration errors and inspect GitLab's resolved configuration before deciding whether to create a pipeline.

## Requirements

- **R1 (parent R2):** CI config lint reports validity, errors, warnings, and bounded merged configuration or generated jobs while clearly distinguishing simulation from execution and deployment.

## Constraints

- Lint calls are read-only: they never create a pipeline, execute job scripts, or mutate a deployment.
- Keep project scope and caller permissions; do not expose authorization data.
- Bound candidate input and the complete MCP response; report omitted output explicitly.
- Keep static lint and pipeline-creation simulation as distinct modes, with simulation opt-in.

## Done when

- The MCP reports lint validity, errors, warnings, and bounded merged configuration or generated job details.
- The result distinguishes lint simulation from job execution and deployment.
- Valid and invalid configs both return structured results; GitLab API failures remain distinguishable from lint findings.
- Local tests cover candidate content, repository-ref lint, simulation opt-in, limits, and API failure states.
- The increment is integrated and verified locally; package publication remains at the initiative-wide release after R1–R6.

## Boundaries

This epic owns CI configuration lint and simulation. It does not create a pipeline, start jobs, or change repository configuration.
Pipeline/job diagnosis, test reports, deployments, and log ranges belong to the following diagnosis epic.

## References

- parent — `_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md`, R2 and Constraints.

## Notes

- Decision: 2026-11-25 — Tracer bullet: lint one supplied CI config, surface a validation error and a valid merged/jobs result through the read-only MCP tool, with R1's successful local installation as the prerequisite.
- Decision: 2026-11-25 — Use GitLab's CI Lint API for both supplied YAML and repository-ref configuration; default to static lint and require an explicit request for pipeline-creation simulation. Do not execute jobs or create a pipeline.
- Decision: 2026-11-25 — Keep one story because both input modes share one endpoint family, output contract, and read-only MCP registration path; the first runnable demo includes invalid and valid candidate YAML.
