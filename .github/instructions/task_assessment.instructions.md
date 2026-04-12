---
applyTo: "**"
---

# Task Assessment

Assess complexity before starting work. Escalate early when requirements are unclear.

## Constraint-Context Matrix

Constraint levels:

- High constraint: clear requirements, well-defined acceptance criteria
- Medium constraint: some ambiguity, multiple valid approaches
- Low constraint: vague or conflicting requirements

Context levels:

- Low context: single file/function
- Medium context: 2-3 files
- High context: >3 files, cross-cutting concerns

| Constraint Level | Context Level | AI Suitability | Approach                             |
| ---------------- | ------------- | -------------- | ------------------------------------ |
| High             | Low           | High           | Proceed                              |
| High             | Medium        | High           | Proceed                              |
| High             | High          | Medium         | Break into subtasks; confirm plan    |
| Medium           | Low           | High           | Ask clarifying questions first       |
| Medium           | Medium        | Medium         | Ask questions; break into subtasks   |
| Medium           | High          | Low            | Escalate for requirements refinement |
| Low              | Any           | Low            | Escalate for clarification           |

## Escalation Protocol

- Do not proceed without clarification when requirements are ambiguous.
- Stop after >2 failed attempts and re-evaluate based on new evidence.
