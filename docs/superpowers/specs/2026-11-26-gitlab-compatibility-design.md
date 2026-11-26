# GitLab version compatibility and schedule variable errors

## Intent

Publish a concrete, maintainable GitLab support policy and make schedule-variable failures actionable. An operator must be able to distinguish a missing API field from an empty variable set and see the server version involved.

## Goals

- Document support for GitLab.com and self-managed releases that GitLab currently maintains.
- Keep the documented self-managed version list dated and link to GitLab's maintenance policy.
- When schedule details omit `variables`, fail `gitlab_list_schedules` with an error naming the schedule and detected GitLab version; explain that the response may be limited by role/ownership or differ from the expected API contract.
- Preserve secret masking and avoid logging or returning variable values in errors.

## Non-goals

- Do not change GitLab permissions, schedule contents, or any other tool's behavior.
- Do not call GitLab's version endpoint on every successful schedule listing; query it only on the missing-field error path.
- Do not claim that every published version has been integration-tested. Clearly separate the support policy from the versions tested by this repository.

## Approaches

1. Return partial schedules with a per-schedule unavailable state. This preserves metadata but makes callers branch on a new response state and does not satisfy the selected explicit-error behavior.
2. Fail the whole schedules call with a diagnostic containing the server version. **Chosen:** this does not present an incomplete variable set as complete, while other MCP tools remain available.
3. Fail based only on the response shape without checking server version. This is simpler but cannot tell an operator which server release returned the unexpected shape.

## Compatibility policy

Document GitLab.com and self-managed GitLab releases that GitLab currently maintains as the support scope. As of 2026-11-26, GitLab lists 19.4, 19.5, and 19.6 as maintained. Link the official policy and label the list with its as-of date because it changes monthly. State separately that repository CI currently tests Python versions and does not run a GitLab server-version matrix.

## Runtime behavior

Read the raw schedule response attributes. When the `variables` key is present, parse its key/value entries as before. When absent, obtain GitLab's version through the metadata/version API and raise an actionable error that includes the schedule ID and version (or says the version could not be determined). The message must not assert that the version caused the omission: GitLab can omit variables for users who are not Maintainers/Owners and are not the schedule owner. Treat malformed variable entries as a response-contract error and identify the failing schedule without echoing values.

## Verification

- Unit tests for populated, explicitly empty, and omitted `variables` fields.
- Unit tests for version lookup success/failure and clear error content with no variable values.
- Verify successful schedule calls do not make an extra version request.
- Run repository tests and Ruff.
