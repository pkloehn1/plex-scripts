---
name: branch-cleanup
description: Switch to main, pull latest, and prune local branches whose remote counterparts no longer exist
---

# Prune Local Branches

Clean up local branches after squash merges by removing branches that no
longer have a remote counterpart.

## Procedure

### Step 1: Switch to main and pull

```bash
git checkout main
git fetch origin main --tags
git pull origin main
```

### Step 2: Prune remote tracking references

Remove stale remote-tracking branches that no longer exist on origin:

```bash
git fetch origin --prune
```

### Step 3: List local and remote branches

```bash
git branch        # local branches
git branch -r     # remote branches
```

### Step 4: Identify and delete stale local branches

For each local branch (excluding `main`):

1. Check if a corresponding `origin/<branch>` remote-tracking branch exists.
2. If no remote counterpart exists, the branch was likely merged via squash merge and the remote was deleted.
3. Confirm by verifying the branch content is already in main:
    - `git diff --name-status origin/main..<branch>`
    - If the diff is empty, the branch content is present in main.
4. Delete the local branch using `git branch -D <branch>` (force delete is required because squash merges break git's ancestry-based "fully merged" detection).

### Step 5: Report results

Print a summary of:

- Branches deleted (with verification status)
- Branches kept (still have a remote counterpart)
- Branches skipped (no remote but diff against main is non-empty — warn user)

## Safety rules

- NEVER delete `main`.
- NEVER run `git push` or delete remote branches — that is a user operation.
- If a branch has no remote AND has a non-empty diff against `origin/main`, do NOT delete it. Warn the user that this branch has unmerged changes.
- Always show the user which branches will be deleted before proceeding. Wait for confirmation.
