# GitHub Repository Management Platform Standards

## Purpose

This document defines the mandatory, one-way-to-win procedure for interacting with GitHub pull request review feedback via API automation.

Scope:

- Creating replies to pull request review comments (inline comments)
- Marking pull request review threads as resolved

## Terminology

- **Pull request review comment**: An inline comment attached to a file diff in a pull request.
- **Pull request review thread**: The discussion thread that groups a pull request review comment and its replies.
- **Resolve a review thread**: Mark the review thread as resolved in GitHub.

## Required Status Checks (Always-On Model)

The `main` branch is protected by a GitHub ruleset that enforces required status checks.

See the documented ruleset export: [docs/ci/github-rulesets/main-ruleset.jsonc](../ci/github-rulesets/main-ruleset.jsonc).

### Required contexts

The required status check context names MUST match exactly.

- `Super-Linter / Lint Code Base` (GitHub Actions integration id `15368`)
- `Lint Traefik Swarm / Lint Traefik Swarm Configuration` (GitHub Actions integration id `15368`)

### Workflow mapping

| Required context | Workflow | Job |
| --- | --- | --- |
| `Super-Linter / Lint Code Base` | `.github/workflows/super-linter.yml` | `Lint Code Base` |
| `Lint Traefik Swarm / Lint Traefik Swarm Configuration` | `.github/workflows/lint-traefik-swarm.yml` | `Lint Traefik Swarm Configuration` |

### Always-on requirements

- `.github/workflows/super-linter.yml` MUST run on `pull_request` and `merge_group` for `main`.
- Do not add `paths`, `paths-ignore`, or job-level `if:` conditions that can prevent the `Lint Code Base` job from running on some PRs.
- Do not rename the workflow (`name: Super-Linter`) or the job (`name: Lint Code Base`) without updating the ruleset required context.

### Path-filtered workflows

Path-filtered workflows (using `on.<event>.paths` / `paths-ignore`) legitimately do not run on all PRs.
If a path-filtered check is made ruleset-required, unrelated PRs can deadlock in "Expected" because the required context is never emitted.

Allowed models:

- **Informational only**: Keep path-filtered workflows non-required.
- **Required-safe**: Remove `paths` filters and emit the check on every PR, but gate expensive work behind a fast "skip vs run" decision.

Example (required-safe):

| Stable context (if required)                            | Workflow                                   | Job                                |
| ------------------------------------------------------- | ------------------------------------------ | ---------------------------------- |
| `Lint Traefik Swarm / Lint Traefik Swarm Configuration` | `.github/workflows/lint-traefik-swarm.yml` | `Lint Traefik Swarm Configuration` |

### Verification

Use the PR rollup to verify the emitted workflow/job pair (GitHub combines them into the required context string):

```sh
gh pr view <PR_NUMBER> --json statusCheckRollup --jq '.statusCheckRollup[] | {workflowName, name, status, conclusion}'
```

## One-Way-To-Win Procedure (Reply + Resolve)

### 1) Pre-check: avoid duplicate replies

Before creating any reply, query the review thread and confirm there is no existing reply authored by the automation user that targets the same pull request review comment.

Acceptance criteria:

- Exactly one automation-authored reply exists per target pull request review comment.
- If a matching reply exists, skip creation.

### 2) Create the reply (REST)

Use the canonical REST endpoint to reply to a pull request review comment:

- `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies`
- Body: `{ "body": "<reply text>" }`

Constraints:

- The `comment_id` MUST be the ID of a top-level pull request review comment (replies-to-replies are not supported).
- Do not edit existing comments. Only create a reply.

Rationale:

- This endpoint creates a visible reply without introducing a pending pull request review.

### 3) Resolve the review thread (GraphQL)

Resolve the thread using GitHub GraphQL:

- Mutation: `resolveReviewThread(input: { threadId: "<thread id>" })`

Notes:

- Thread resolution is performed on the thread node ID, not the REST numeric comment ID.

### 4) Post-check: verify clean state

After replying and resolving:

- Re-query the pull request review thread:
  - Confirm the reply exists.
  - Confirm `isResolved == true`.
- Confirm there is no pending pull request review created by the automation user.

## Prohibited Patterns

- Avoid GraphQL mutations for inline PR review comments in automation — they create pending reviews that require manual submission.
- Do not use REST endpoints that edit existing pull request review comments (`PATCH /repos/{owner}/{repo}/pulls/comments/{comment_id}`).

## References

- GitHub REST API: Pull request review comments
  - <https://docs.github.com/en/rest/pulls/comments>
- GitHub GraphQL API: `resolveReviewThread`
  - <https://docs.github.com/en/graphql/reference/mutations#resolvereviewthread>
