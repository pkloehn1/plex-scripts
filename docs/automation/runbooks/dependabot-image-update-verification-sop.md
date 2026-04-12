# Dependabot Image Update Verification SOP

Table of contents:

- [1. Purpose](#1-purpose)
- [2. Scope](#2-scope)
- [3. Roles](#3-roles)
- [4. GitOps exceptions for Dependabot PRs](#4-gitops-exceptions-for-dependabot-prs)
- [5. Verification procedure](#5-verification-procedure)
- [6. Automated test expectations](#6-automated-test-expectations)
- [7. Manual verification checklist](#7-manual-verification-checklist)
- [8. Rollback](#8-rollback)
- [9. Decision matrix](#9-decision-matrix)
- [10. Service maturity model](#10-service-maturity-model)
- [11. References](#11-references)

## 1. Purpose

This SOP defines how to verify Dependabot Docker image update PRs against the live environment before merge.

## 2. Scope

- Applies to: Dependabot PRs that bump Docker image tags in compose files.
- Does not apply to: application code changes, new service additions, or infrastructure refactoring. Those follow the standard DevSecOps Workflow.

## 3. Roles

### 3.1 DSO engineer

Responsible for:

- Verifying CI pipeline status on the Dependabot PR.
- Checking out the Dependabot branch locally and deploying to the target stack.
- Reviewing container logs for errors, deprecation warnings, or configuration drift.

### 3.2 QA engineer

Responsible for:

- Running the automated test suite (CI checks, linting, smoke tests).
- Executing the manual verification checklist (section 7).
- Confirming service health, endpoint reachability, and functional correctness.
- Documenting test results as a PR comment before merge approval.

### 3.3 AI agent

Responsible for:

- Analyzing upstream changelogs and CVE databases to produce a structured summary of breaking changes, CVEs (CVSS scores), deprecations, and deployment impact.
- Assessing risk level (patch, minor, major) and flagging breaking changes.
- Reassessing risk when CVSS base scores exceed the current risk category (see decision matrix, section 9).
- Analyzing version coupling across related images (e.g., all images in a group must bump in lockstep).
- Verifying tag stability (published tag exists, not yanked or pre-release).
- Cross-referencing the service maturity model (section 10) to determine the required verification depth.

In a small team context, one person may fill both DSO and QA roles. The separation ensures each responsibility is explicitly performed.

## 4. GitOps exceptions for Dependabot PRs

Dependabot image update PRs are exempt from the standard GitOps workflow:

- No new issue is required (the PR itself is the work item).
- No new branch is required (Dependabot creates its own branch).
- No separate work package issue template needs to be filled out.

All other standards still apply:

- CI checks must pass.
- Pre-commit hooks must pass on the branch.
- Signed commits are not required for Dependabot bot commits (CI skips signing checks).
- The PR must be reviewed and approved before merge.

## 5. Verification procedure

### 5.1 Review upstream release notes

Before any local testing, the DSO engineer reviews the upstream release notes for the image being updated.

Check for:

- Breaking changes or migration steps.
- Deprecated configuration options.
- Changes to default behavior (ports, environment variables, file paths).
- Security advisories addressed by the release.

#### 5.1.1 Verify tag stability

Confirm the proposed image tag is a **stable release**, not a release candidate or pre-release. Check:

- The tag name for pre-release indicators (`-rc`, `-beta`, `-alpha`, `-dev`).
- The upstream release page: verify the version is listed as "Latest Release", not "Pre-release".
- When in doubt, inspect registry metadata:

```bash
docker manifest inspect <IMAGE>:<TAG>
```

Pre-release tags warrant closing the PR. Use `@dependabot ignore` to suppress alerts until a stable release ships.

#### 5.1.2 Check version coupling and release tracks

Some images must upgrade in lockstep. If a PR bumps only one side, **close it** and upgrade the pair in one commit.

Confirm the proposed version stays on the **same release track** (e.g., LTS vs STS). A track change requires deliberate migration.

### 5.2 AI agent release notes analysis

The AI agent performs a structured analysis of upstream release notes and CVE databases per the repo's AI directive files. The agent produces a summary covering:

- **Breaking changes**: API removals, renamed config keys, changed defaults.
- **Security advisories**: CVE identifiers with CVSS base scores and affected component versions.
- **Deprecations**: features or config options scheduled for removal.
- **Configuration changes**: new required environment variables, changed ports, or altered file paths.
- **Deployment-specific impact**: assessment of whether findings affect components actively used in this deployment.

The agent presents findings to the DSO engineer. CVEs exceeding the risk category on active components escalate to match CVSS severity (section 9).

### 5.3 Verify CI status

PRs labeled `status/needs-manual-review` contain a **major version bump** and require the full major-update path (section 9): release notes, migration guide, and owner approval.

Confirm all required CI checks pass on the Dependabot PR:

```bash
gh pr checks <PR_NUMBER>
```

All CI checks must pass before local testing (sections 5.4--5.8). Release notes review (section 5.1) may proceed in parallel. Resolve any failure before continuing.

### 5.4 Check out the Dependabot branch locally

```bash
gh pr checkout <PR_NUMBER>
```

#### 5.4.1 Fallback checkout

If `gh pr checkout` is unavailable or fails:

```bash
git fetch origin pull/<PR_NUMBER>/head:dependabot/<BRANCH_NAME>
git checkout dependabot/<BRANCH_NAME>
```

**Do not** use `gh pr diff | git apply` — it leaves orphaned changes that block `git pull` post-merge. Always fetch a proper branch.

### 5.5 Branch retention

Stay on the Dependabot branch until the PR merges. Commit any fixes found during verification directly on this branch to keep all changes in the PR.

### 5.6 Deploy the updated stack locally

Identify the target stack from the PR diff path and deploy it using the project's deployment tooling.

### 5.7 Verify service convergence

Wait for the updated service to converge and confirm replicas are running.

### 5.8 Review container logs

Check logs for errors, warnings, or unexpected behavior:

- Startup errors or crash loops.
- Deprecation warnings related to the version change.
- Configuration parsing failures.
- Connection errors to dependent services.

### 5.9 Post-merge cleanup

After the PR is merged on GitHub, clean up the local environment:

```bash
git checkout main
git pull origin main
git branch -d dependabot/<BRANCH_NAME>
```

## 6. Automated test expectations

### 6.1 CI pipeline tests (pre-merge)

These run automatically on the Dependabot PR and must all pass:

- Lint Code Base (Super-Linter): YAML, Checkov, EditorConfig, Gitleaks.
- Pre-commit hooks: full hook suite (signing checks skipped for bot commits).
- Pytest coverage: existing test suites must not regress.

### 6.2 Smoke tests (post-deploy, local)

Run after deploying the updated stack. These confirm the service starts and responds.

### 6.3 End-to-end tests (post-deploy, local)

These validate that the service functions correctly in the context of the full stack:

- Dependent services still connect.
- Authentication flows work if the service participates in SSO.
- Certificate issuance works if the service is a CA.
- Monitoring detects the service as healthy.

## 7. Manual verification checklist

Complete this checklist and post results as a PR comment before approving the merge.

Mark non-applicable items **N/A** with justification. See the service maturity model (section 10) for which items apply at each stage.

Responsibility markers:

- **[AI]** -- performed by the AI agent; human reviewer confirms findings.
- **[BOT]** -- verified automatically by CI; human confirms status.
- **[HUMAN]** -- requires manual verification by the reviewer.
- **[AI/HUMAN]** -- performed jointly by the AI agent and DSO engineer.
- **[BOT/HUMAN]** -- partially automated; human confirms result.

```markdown
## Dependabot Update Verification

- [ ] **[AI/HUMAN]** **Release notes reviewed** -- no breaking changes identified
- [ ] **[AI]** **Release notes analysis** -- AI agent summary reviewed, risk level confirmed or escalated
- [ ] **[BOT]** **CI checks** -- all green on the PR
- [ ] **[HUMAN]** **Local deployment** -- stack deployed with updated image
- [ ] **[HUMAN]** **Service convergence** -- replicas running, no restart loops
- [ ] **[BOT/HUMAN]** **Health check** -- built-in health check passes
- [ ] **[HUMAN]** **Log review** -- no errors, deprecation warnings, or config drift
- [ ] **[HUMAN]** **Smoke test** -- service endpoint responds (HTTP 200 or equivalent)
- [ ] **[HUMAN]** **Dependent services** -- upstream/downstream services unaffected
- [ ] **[HUMAN]** **End-to-end** -- functional flow validated (auth, certs, routing as applicable)
```

## 8. Rollback

If the updated image causes issues, redeploy with the previous image version.

### 8.1 Revert the image tag

Edit the Compose file to restore the previous image tag, then redeploy.

### 8.2 Verify rollback

Verify convergence, review logs, and run smoke tests to confirm the service is stable on the previous version.

### 8.3 Close the Dependabot PR

If the update cannot be applied, close the PR with a comment explaining the failure. Use Dependabot commands to manage ignore rules if needed:

```text
@dependabot ignore <dependency> minor version
@dependabot ignore <dependency> major version
```

## 9. Decision matrix

<!-- markdownlint-disable MD013 -->

| Update type           | Risk     | Release notes review          | Risk reassessment                                                          | Local deploy required | End-to-end test required | Approval        |
| --------------------- | -------- | ----------------------------- | -------------------------------------------------------------------------- | --------------------- | ------------------------ | --------------- |
| Patch (x.y.Z)         | Low      | Skim for fixes                | Escalate if CVSS >= 4.0 on active components; target matches CVSS severity | Recommended           | Optional                 | Single reviewer |
| Minor (x.Y.0)         | Medium   | Full review required          | Escalate if CVSS >= 7.0 on active components; target matches CVSS severity | Required              | Required                 | Single reviewer |
| Major (X.0.0)         | High     | Full review + migration guide | Escalate if CVSS >= 9.0 on active components; target matches CVSS severity | Required              | Required                 | Owner approval  |
| Pre-release (RC/beta) | Critical | N/A -- do not merge           | N/A                                                                        | N/A                   | N/A                      | Close PR        |

<!-- markdownlint-enable MD013 -->

CVSS severity ranges (v3.1/v4.0): None 0.0, Low 0.1--3.9, Medium 4.0--6.9, High 7.0--8.9, Critical 9.0--10.0.

When risk is escalated, apply the requirements from the matching risk row in the matrix above.

## 10. Service maturity model

Services follow a three-stage maturity model that determines the required verification depth for image updates.

### 10.1 Maturity stages

| Stage | Name  | Description                                                                       | Required checklist items                   |
| ----- | ----- | --------------------------------------------------------------------------------- | ------------------------------------------ |
| 1     | Crawl | Deployed but not operationalized; no downstream consumers or exposed endpoints    | Release notes, CI, deploy, convergence     |
| 2     | Walk  | Operationalized with limited dependents; serves internal traffic only             | All Crawl items + health, logs, smoke test |
| 3     | Run   | Fully operationalized; serves external traffic, participates in auth/cert/routing | Full checklist + owner approval            |

Crawl-stage services require only the first four checklist items. Walk-stage services require all items except end-to-end. Run-stage services require the full checklist and owner approval.

## 11. References

- GitHub platform standards: `docs/repository-standards/github-platform-standards.md`
