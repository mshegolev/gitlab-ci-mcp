---
id: 2
type: epic
title: "CI configuration lint and simulation"
parent: initiative-gitlab-pipeline-analysis
covers: ["R2"]
sources: ["_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md"]
companions: []
after: ["epic-artifact-listing-reliability"]
refined: false
risk: high
---

# CI configuration lint and simulation

## Description

Add read-only validation for a candidate or repository CI configuration, returning useful lint diagnostics and bounded generated configuration without executing jobs.

## Outcome

An engineer can catch configuration errors and inspect how GitLab resolves the pipeline before creating or running it.

## Done when

- The MCP reports lint validity, errors, warnings, and bounded merged configuration or generated job details.
- The result distinguishes lint simulation from job execution and deployment.
- The tool is included in the single reviewed package release after R1–R6 are complete.

## Boundaries

This epic owns CI configuration lint and simulation. It does not create a pipeline, start jobs, or change repository configuration.

## References

- parent — `_bmad-output/initiative-gitlab-pipeline-analysis/initiative-gitlab-pipeline-analysis.md`, R2 and Constraints.

## Notes

- Decision: 2026-11-25 — Tracer bullet: lint one supplied CI config, surface a validation error and a valid merged/jobs result through the read-only MCP tool, with R1's successful local installation as the prerequisite.
- Waits on epic-artifact-listing-reliability because: R1's local installation and MCP verification is the user's required gate before R2 starts; both increments share the manager and tool registration surface.
