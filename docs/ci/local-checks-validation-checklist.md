# Local Check Validation Checklist (Reusable)

## Purpose

Provide a repeatable checklist to verify that local checks on Linux and
Windows match the configured behavior and align with CI expectations.

## Scope

- Local pre-commit hooks (Linux and Windows)
- Local runner scripts (for CI parity)
- GitHub Actions checks (reference point)

## Preparation

- Identify the check to validate (hook id or script).
- Record configuration files and allowlist paths.
- Identify whether the check runs on staged files only or all files.
- Choose a minimal fixture set (single file when possible).
- Use a scratch location already excluded from commits (recommend `tmp/`).
- Record the exact command to run (single hook or script).

## Execution Steps (per check)

1. **Define target and expected outcome**

  - Check name:
  - Hook id / command:
  - Expected outcome (fail, pass, allowlist-suppressed, skip):
  - Config files used:

2. **Create a minimal violating fixture**

  - Fixture path:
  - Violation description:
  - Ensure the fixture is in a tracked path if the hook only inspects staged files.

3. **Stage if required**

  - If the hook runs on staged files, stage the fixture.
  - If the hook runs on all files, do not stage unless required by the hook.

4. **Run only the target check**

  - Command executed:
  - Capture the full output.

5. **Evaluate the result**

  - Did it detect the violation as expected?
  - If not, identify the mismatch: wrong config path, allowlist suppressing,
    OS-specific path/glob behavior, or Git default branch ref missing.

6. **Fix or confirm alignment**

  - If mismatch: update config or runner to align behavior.
  - If aligned: mark the check as aligned for this OS.

7. **Clean up**

  - Remove the fixture (or reset via git).
  - Unstage changes if required.

## Output Template (per check)

```text
Check:
OS:
Hook/Command:
Expected:
Config files:
Fixture:
Staged:
Command:
Result:
Alignment status: aligned | gap
Notes:
```

## Tips

- For diff-based linters, ensure the default branch ref exists locally.
- If a check relies on Docker, confirm sudo token is fresh on Linux.
- When an allowlist suppresses an issue, record it explicitly and treat as
  aligned.
