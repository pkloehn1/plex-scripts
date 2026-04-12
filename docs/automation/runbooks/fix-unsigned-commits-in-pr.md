# Fix Unsigned Commits in Pull Request

## 1. Purpose

This runbook provides a procedure for fixing unsigned commits in an existing pull request that is blocked from merge due to required commit signatures.

## 2. Prerequisites

1. The PR branch is checked out locally
2. Git is configured for commit signing (see [SSH prerequisites](#5-ssh-commit-signing-setup))
3. The signing key is registered on GitHub for the account that will push the fix
4. You have push access to the PR branch

## 3. Quick Reference

**Automated approach (recommended):**

```bash
# 1. Checkout the PR branch
git checkout <branch-name>

# 2. Dry-run to see what would be fixed
.venv/bin/python -m scripts.github.fix_unsigned_commits --pr <NUMBER>

# 3. Apply fixes (rebase and force-push)
.venv/bin/python -m scripts.github.fix_unsigned_commits --pr <NUMBER> --apply
```

**Manual approach:**

```bash
# 1. Verify unsigned commits
.venv/bin/python -m scripts.github.list_pr_commit_verifications --repo owner/name --pr <NUMBER> --only-failing

# 2. Check current git signing config
git config --get commit.gpgsign
git config --get user.signingkey

# 3. Enable signing if not already enabled
git config --global commit.gpgsign true

# 4. Rebase to re-sign commits
git rebase --exec 'git commit --amend --no-edit --no-verify' -i <base-branch>

# 5. Force push (user must approve)
git push --force-with-lease origin <branch-name>
```

## 4. Detailed Procedure

### 4.1 Step 1: Identify Unsigned Commits

List all unsigned commits in the PR:

```bash
.venv/bin/python -m scripts.github.list_pr_commit_verifications \
  --repo owner/name \
  --pr <PR_NUMBER> \
  --only-failing
```

Expected output shows commits with `"reason": "unsigned"` and `"verified": false`.

### 4.2 Step 2: Verify Git Signing Configuration

Check that commit signing is enabled and configured:

```bash
git config --get commit.gpgsign
git config --get gpg.format
git config --get user.signingkey
git config --get user.email
git config --get user.name
```

Expected values:

- `commit.gpgsign` = `true`
- `gpg.format` = `ssh`
- `user.signingkey` = path to SSH public key (e.g., `~/.ssh/id_ed25519_signing.pub`)
- `user.email` = GitHub noreply email or verified email
- `user.name` = GitHub username

### 4.3 Step 3: Enable Commit Signing (If Not Already Enabled)

If signing is not enabled, configure it:

```bash
# Enable SSH signing
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519_signing.pub
git config --global commit.gpgsign true
```

**Note**: The signing key must be registered on GitHub as an SSH signing key for the account that will push the fix.

### 4.4 Step 4: Determine Base Branch

Identify the base branch for the PR:

```bash
gh pr view <PR_NUMBER> --json baseRefName --jq '.baseRefName'
```

Or check locally:

```bash
git log --oneline --graph --all | head -20
```

### 4.5 Step 5: Re-sign Commits via Interactive Rebase

Rebase the commits to re-sign them. This rewrites commit history:

```bash
# Fetch latest base branch
git fetch origin <base-branch>

# Start interactive rebase from base branch
git rebase -i origin/<base-branch>
```

In the rebase editor, change all `pick` to `reword` (or use `exec`), then save and close. Git will re-sign each commit.

**Alternative (automated approach)**:

```bash
# Rebase with exec to re-sign all commits
git rebase --exec 'git commit --amend --no-edit --no-verify' -i origin/<base-branch>
```

This automatically amends each commit (which triggers re-signing) without opening an editor for each one.

**Important**: `--no-verify` skips hooks during rebase to prevent failures while rewriting history. Run pre-commit once after the rebase finishes to re-validate before pushing.

### 4.6 Step 6: Verify Signatures

After rebasing, verify that commits are now signed:

```bash
git log --show-signature -n <number-of-commits>
```

Look for "Good signature" messages. Each commit should show a valid signature.

### 4.7 Step 7: Force Push to PR Branch

Push the rebased commits to the PR branch:

```bash
git push --force-with-lease origin <branch-name>
```

**Safety notes**:

- `--force-with-lease` is safer than `--force` as it prevents overwriting if the remote branch has been updated
- The user must approve this operation (agents should not force-push without explicit approval)
- This will update the PR with the newly signed commits

### 4.8 Step 8: Verify PR Status

After pushing, verify the PR commits are now signed:

```bash
.venv/bin/python -m scripts.github.list_pr_commit_verifications \
  --repo owner/name \
  --pr <PR_NUMBER> \
  --only-failing
```

Expected: Empty list (no failing commits) or all commits show `"verified": true`.

## 5. SSH Commit Signing Setup

If commit signing is not configured, follow these steps:

### 5.1 Create SSH Signing Key

```bash
ssh-keygen -t ed25519 -C "github-commit-signing" -f ~/.ssh/id_ed25519_signing
```

### 5.2 Load Key into SSH Agent

```bash
ssh-add ~/.ssh/id_ed25519_signing
ssh-add -l  # Verify key is loaded
```

### 5.3 Configure Git for SSH Signing

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519_signing.pub
git config --global commit.gpgsign true
```

### 5.4 Register Key on GitHub

1. Copy the public key:

    ```bash
    cat ~/.ssh/id_ed25519_signing.pub
    ```

2. Go to GitHub: Settings → SSH and GPG keys → New SSH key
3. Key type: **Signing key**
4. Paste the public key content
5. Save

### 5.5 Verify Setup

```bash
git log --show-signature -n 1
```

Should show "Good signature" for the most recent commit.

## 6. Troubleshooting

### 6.1 Issue: "gpg: signing failed: No secret key"

**Cause**: SSH agent doesn't have the signing key loaded.

**Fix**:

```bash
ssh-add ~/.ssh/id_ed25519_signing
ssh-add -l  # Verify
```

### 6.2 Issue: "error: gpg failed to sign the data"

**Cause**: Git signing configuration is incorrect or key is not accessible.

**Fix**: Verify configuration:

```bash
git config --get commit.gpgsign  # Should be 'true'
git config --get user.signingkey  # Should point to .pub file
ssh-add -l  # Should list the signing key
```

### 6.3 Issue: Rebase conflicts

**Cause**: Base branch has diverged or conflicts exist.

**Fix**: Resolve conflicts normally during rebase, then continue:

```bash
git rebase --continue
```

### 6.4 Issue: Commits still show as unsigned after push

**Cause**:

- Signing key not registered on GitHub
- Email in commit doesn't match GitHub account
- Key registered but not as a signing key

**Fix**:

1. Verify key is registered on GitHub as a **signing key** (not authentication key)
2. Check commit author email matches GitHub account:

    ```bash
    git log --format='%ae' -n 1
    ```

3. Ensure `user.email` matches GitHub account email or use GitHub noreply email

## 7. Alternative: Amend and Force Push (Single Commit)

If the PR has only one commit or you want to squash all commits:

```bash
# Amend the last commit (re-signs it)
git commit --amend --no-edit

# Force push
git push --force-with-lease origin <branch-name>
```

## 8. Safety Considerations

1. **History Rewriting**: Rebasing rewrites commit history. Coordinate with other contributors if the branch is shared.

2. **Force Push**: Only use `--force-with-lease` and get explicit user approval.

3. **Pre-commit Hooks**: Use `--no-verify` during rebase to avoid hook failures, but verify changes after rebase.

4. **Backup**: Consider creating a backup branch before rebasing:

    ```bash
    git branch backup-<branch-name> <branch-name>
    ```

## 9. Related Documentation

- **Automated fix script**: `scripts/github/fix_unsigned_commits.py` (recommended for programmatic use)
- List PR commit verifications: `scripts/github/list_pr_commit_verifications.py`
- List SSH signing keys: `scripts/github/list_ssh_signing_keys.py`
- GitHub platform standards: `docs/repository-standards/github-platform-standards.md`
