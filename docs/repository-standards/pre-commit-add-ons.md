# Pre-commit Add-on Hooks

## Purpose

Optional pre-commit hook groups that extend the core set for Docker Compose and Docker Swarm. Synced to spoke repos via `sync-directives.yml`; spokes opt out using `exclude:`.

## Add-on Groups

### Compose (Docker Compose with Traefik)

Applies to repos with Docker Compose files outside of `stacks/` directories.

| Hook ID | Script | Scope |
| ------- | ------ | ----- |
| `dclint` | External (`pre-commit-dclint`) | Generic Compose best practices |
| `check-bound-ports` | `scripts/linting/check_bound_ports.py` | Port binding validation |
| `check-compose-network-mode-conflicts` | `scripts/linting/check_compose_network_mode_conflicts.py` | Network mode conflict detection |
| `lint-compose` | `scripts/linting/lint_compose.py` | Traefik Compose hardening, domain, network, TLS |

File pattern: `^(docker-compose\.ya?ml|compose/.*/docker-compose\.ya?ml|stacks/.*/docker-compose\.ya?ml)$`

The `lint-compose` hook excludes `stacks/` paths internally (handled by `_is_compose_file()`), so it only validates non-stacks Compose files even though the broader compose hooks match both patterns.

### Swarm (Docker Swarm with Traefik)

Implies the compose add-on. Applies to repos deploying Docker Swarm stacks.

| Hook ID | Script | Scope |
| ------- | ------ | ----- |
| `lint-traefik-swarm` | `scripts/linting/lint_swarm.py` | Swarm-specific Traefik validation |

File pattern: `^stacks/.*/docker-compose\.ya?ml$`

## Hub-Spoke Sync Pattern

Add-on hooks live in the hub's `.pre-commit-config.yaml` and sync to spokes. The hub has no compose or stacks directories, so hooks show `Skipped`. Spokes activate when matching files are committed.

### `run_if_exists` Guard

All add-on hooks use the `run_if_exists.py` guard wrapper:

```yaml
- id: lint-traefik-swarm
  args:
    - scripts/precommit/run_in_repo_venv.py
    - scripts/precommit/run_if_exists.py
    - scripts/linting/lint_swarm.py    # guard: does this script exist?
    - scripts/linting/lint_swarm.py    # command: execute if guard passes
  files: ^stacks/.*/docker-compose\.ya?ml$
```

If a spoke excludes a script via `sync-directives.yml`, the hook degrades gracefully (exits 0) instead of failing with a missing-file error.

### Exclusion Pattern

Spokes opt out of irrelevant add-ons in `.github/sync-directives.yml`:

```yaml
# In hub's sync-directives.yml
exclude:
  pkloehn1/docker-swarm-homelab:
    # Compose-only (swarm uses lint_swarm.py instead)
    - scripts/linting/lint_compose.py
    - scripts/linting/tests/test_lint_compose.py
  pkloehn1/docker-compose-homelab:
    # Swarm-only (compose uses lint_compose.py instead)
    - scripts/linting/lint_swarm.py
    - scripts/linting/tests/test_lint_swarm.py
```

## Adding a New Add-on

1. Create the linter script in `scripts/linting/` with tests.
2. Add a hook entry in `.pre-commit-config.yaml` with `run_if_exists` guard.
3. Add the script to `exclude:` for spokes that should not receive it.
4. The directory pattern in `sync-directives.yml` (`scripts/linting/*.py`) auto-syncs new files.

## Spoke-Local Overlay

Hub sync overwrites `.pre-commit-config.yaml` in spokes. Hooks that only serve a single spoke should not live in the hub config. The overlay mechanism preserves spoke-only hooks across syncs.

### When to use overlay vs `run_if_exists`

Use `run_if_exists` for hooks shared across multiple spokes (compose, swarm add-ons). Use the overlay for hooks unique to a single spoke that would add dead weight to the hub.

### Convention

Spokes create `.pre-commit-config.local.yaml` at the repo root with spoke-only hook definitions:

- This file is not listed in `sync-directives.yml`, so sync never overwrites it.
- During sync, `merge_precommit_config` appends overlay `repos:` after hub repos to produce the final `.pre-commit-config.yaml`.
- If no overlay file exists, the hub config is copied verbatim (current behavior preserved).

The merged file is a generated artifact. Direct edits are overwritten on the next sync. A header comment warns against direct edits.

### Example spoke-local file

```yaml
---
repos:
  - repo: local
    hooks:
      - id: verify-recyclarr-profiles
        name: Verify Recyclarr Profiles
        entry: scripts/precommit/run_python
        language: system
        args:
          - scripts/precommit/run_in_repo_venv.py
          - scripts/testing/hooks/verify_recyclarr_profiles.py
        files: ^app-config/recyclarr/recyclarr\.yml$
        pass_filenames: false
```

### Merge semantics

- Hub config is loaded via `yaml.safe_load`, which expands YAML anchors (`&python_wrapper` / `*python_wrapper`) into inline values.
- Overlay `repos:` entries are appended after hub `repos:`.
- Hub top-level keys (`default_stages`, `fail_fast`) are preserved.

### CI validation

Three levels catch bad merges:

- **Hub CI**: `pre-commit.yml` runs `pytest-affected` which covers merge logic tests.
- **Sync workflow**: `run-sync-directives/action.yml` validates the merged YAML after sync, before the spoke PR is created.
- **Spoke CI**: `pre-commit.yml` runs `pre-commit run` on the PR, which parses the config. Spokes should add a pytest test verifying all local hook IDs appear in the merged config.

## SonarCloud Spoke Exclusions

Hub-synced scripts are already analyzed in the hub's SonarCloud project. Spokes should exclude these paths to avoid duplicate analysis:

- Each spoke maintains its own `sonar-project.properties` independently (not synced).
- Spoke-specific scripts (not synced from hub) remain in the Sonar analysis scope.

### Recommended `sonar.exclusions` for spokes

```properties
sonar.exclusions=\
  scripts/ci/**,\
  scripts/github/**,\
  scripts/common/**,\
  scripts/precommit/**,\
  scripts/testing/**,\
  scripts/linting/**,\
  scripts/devops/**,\
  scripts/context_validator/**,\
  scripts/dev/**,\
  docs/**,\
  .venv/**,\
  **/__pycache__/**
```

## See Also

- [Hub/Spoke Composition](style-guides/python-style-guide.md#hubspoke-composition) — code-level composition contract for hub and spoke modules
