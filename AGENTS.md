# AGENTS.md

## Goal

Complete the task with the smallest safe change. Follow the existing codebase style and avoid unrelated work.

## Rules

* Follow the user's request and the nearest `AGENTS.md`.
* Read only relevant files; use targeted search.
* Check project scripts and docs before guessing commands.
* Preserve existing behavior unless a change is requested.
* Avoid unnecessary refactors, abstractions, comments, or dependencies.
* Do not overwrite uncommitted user changes.
* Do not commit, push, deploy, migrate, or modify production unless asked.

## Safety

* Never expose or modify secrets, tokens, credentials, or `.env` files.
* Avoid destructive commands and irreversible actions.
* Do not bypass tests, validation, authentication, or security checks.
* Validate external input and handle errors clearly.

## Testing

* Run the most relevant tests first.
* Run applicable lint, type-check, or build commands.
* Fix only issues caused by or related to the task.
* If testing is unavailable, state what was not verified.

## Token Efficiency

* Keep analysis and responses concise.
* Do not repeat instructions or results.
* Avoid printing full files, logs, diffs, or stack traces.
* Stop exploring once enough information is available.
* Do not create extra documentation unless requested.

## Final Response

Use at most 5 short bullets:

* What changed
* Key files
* Tests and results
* Remaining risk, only if relevant
  :::
