---
id: 1
type: story
title: "Lint candidate and repository CI configurations"
parent: epic-ci-config-lint
covers: [R1]
after: [1.1]
refined: true
hitl: false
risk: high
---

# Lint candidate and repository CI configurations

## Description

An engineer can lint supplied YAML or a project configuration at a ref, inspect bounded diagnostics and resolved jobs/configuration, and tell static validation from opt-in simulation.

## Requirements

1. **Lint a supplied candidate** (R1)
   **Given** the caller supplies CI YAML no larger than 1 MiB when encoded as UTF-8, for either lint mode
   **When** the caller requests static lint
   **Then** GitLab validates it in the selected project context and the MCP returns `valid`, errors, warnings, and any available merged configuration or generated jobs
   **And** invalid YAML is returned as a lint result, not confused with a GitLab API failure
2. **Lint repository configuration** (R1)
   **Given** the caller selects a project ref without supplying YAML
   **When** the caller requests lint
   **Then** GitLab validates the repository configuration at that ref, including project includes and available project context
   **And** the response identifies the selected ref and returns included-file locations/context refs when GitLab provides them
3. **Keep simulation explicit** (R1)
   **Given** static lint is the default and no simulation was requested
   **When** the tool returns
   **Then** it identifies the result as static lint and states that no pipeline or job was created or run
   **When** the caller explicitly requests pipeline-creation simulation
   **Then** the response identifies simulation separately and states that job scripts and deployments were not executed
   **And** candidate YAML over 1 MiB is rejected with a bounded input-limit error before any GitLab request
4. **Bound the response** (R1)
   **Given** the complete encoded MCP response would exceed 256,000 bytes
   **When** the tool responds
   **Then** the response is no larger than 256,000 bytes and identifies every truncated field, or returns a bounded explicit limit error
5. **Keep permission and service failures distinct** (R1)
   **Given** GitLab denies access, cannot find the project/ref, or the API is unavailable
   **When** lint is requested
   **Then** the tool returns a bounded actionable API error and does not report the configuration as valid or invalid
6. **Preserve the read-only boundary** (R1)
   **Given** any supported lint mode
   **When** it completes
   **Then** no pipeline, job, or deployment is created or changed, no job script is executed, and authorization data is absent from results

## Boundaries

- Do not add pipeline creation, job execution/retry, manual job play, or deployment operations.
- Existing pipeline, job, artifact, and log tools retain their current behavior.
- Do not claim simulation proves successful runtime execution or deployment.

## References

- parent — _bmad-output/initiative-gitlab-pipeline-analysis/tickets/epic-ci-config-lint/epic-ci-config-lint.md
- API — https://docs.gitlab.com/api/lint/, CI Lint API
- user guide — https://docs.gitlab.com/ci/yaml/lint/, static validation and pipeline simulation

## Notes

- Decision: 2026-11-25 — Use the current documented GitLab v4 CI Lint parameters (`content_ref` and `dry_run_ref`) for repository configuration. The target instance version is not available in this session, so live compatibility stays INCONCLUSIVE; unsupported API parameters must be reported as an API failure, never as a lint result.
- Decision: 2026-11-25 — Limit candidate YAML to 1 MiB UTF-8 and the complete encoded MCP response to 256,000 bytes, matching the existing MCP response budget. Oversized response fields carry explicit truncation metadata.
- Risk: high, because overstating a lint or simulation result could mislead an engineer before pipeline execution. Extra check: verify the tool never calls pipeline creation or job execution endpoints.
