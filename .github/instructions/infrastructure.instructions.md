---
applyTo: "**/*.tf,**/*.tfvars,**/ansible/**,**/k8s/**,**/kubernetes/**,**/helm/**"
---

# Infrastructure as Code Instructions

Path-specific instructions for infrastructure files.

## General Principles

REQUIRE:

- Idempotent operations (safe to run multiple times)
- Remote state with locking for shared infrastructure
- Environment isolation (dev, staging, production)

NEVER:

- Hardcode credentials or secrets in code
- Commit sensitive values to version control
- Use `latest` tags for container images

## State Management

REQUIRE:

- Remote backend for state storage
- State locking to prevent concurrent modifications
- Backup and recovery procedures documented

## Secret Management

REQUIRE:

- External secret management (vault, cloud secrets manager)
- No plaintext secrets in repositories
- Audit logging for secret access

NEVER:

- Log secret values
- Pass secrets as command-line arguments

## Validation

REQUIRE before commit:

- Format validation (terraform fmt, yamllint)
- Syntax validation
- Security scanning (checkov, tfsec, or equivalent)
