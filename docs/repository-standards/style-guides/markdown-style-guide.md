# Markdown Style Guide

## Purpose

Normative rules for Markdown in this repository.

## Core Rules

### Structure

REQUIRE:

- Use a single top-level heading (`# Title`) at the start of a document.
- Use headings to create a stable outline (`##`, `###`, `####`) rather than bold text.

NEVER:

- Skip heading levels (e.g., `##` directly to `####`) unless the file is intentionally partial.

### Runbook Headings (Numbered)

Applies to `docs/automation/runbooks/**/*.md`.

REQUIRE:

- Headings MUST be numbered and sequential (e.g., `## 1.`, `## 2.`, `### 2.1`).
- Subsection numbers MUST match their parent section.

Validation:

- `scripts/linting/validate_heading_numbers.py` (wired via `pre-commit`).

### Prose Quality

A paragraph is the unit of composition. Each paragraph groups related sentences about one topic into a single coherent thought. It may be one sentence or many, but it must hold together as a unit.

REQUIRE:

- Make each paragraph cover exactly one topic. Do not split a single thought across multiple paragraphs.
- A single sentence is a valid paragraph only when it is a complete, self-contained thought (e.g., a section introduction).
- Omit needless words. Every word must earn its place. Cut filler that adds no meaning.
- Use the active voice. Write what the subject does, not what was done to it.
- Put statements in positive form. Say what to do, not what to avoid.
- Use definite, specific, concrete language. Avoid vague abstractions.
- Keep related words together. Place modifiers next to what they modify.
- Default to short sentences. Vary length for rhythm, but prefer short.
- Use strong nouns and verbs to carry meaning. Strip extra modifiers.
- Prefer simple words over complex ones.
- When a line exceeds the character limit, shorten the prose. Do not insert line breaks to wrap text.

NEVER:

- Treat each sentence as its own paragraph, producing sequences of single-line "paragraphs" with no cohesion.
- Insert line breaks between sentences within a single thought.
- Split lines mechanically to fit the character limit instead of rewriting shorter.

#### Hemingway Editor evaluation criteria

Target grade 9 reading level or "Technical" mode for documentation:

- Flag hard-to-read sentences (4+ grade levels above target) and very hard sentences (6+ levels).
- Flag adverb overuse, passive voice, and phrases with simpler alternatives.

Automated enforcement is tracked in issue #372.

### Lists

REQUIRE:

- Use `-` for unordered lists.
- Keep list items as short as possible.
- If a list item contains multiple steps, convert it into a subheading + steps instead.

### Code Blocks

REQUIRE:

- Use fenced code blocks with a language tag when known (e.g., `bash`, `yaml`, `powershell`, `python`).
- Prefer showing the minimal snippet needed to understand the change.

NEVER:

- Paste large, unscoped logs or full files when a link to the file is sufficient.

### Mermaid Diagrams

This repository uses GitHub-rendered Mermaid diagrams (see: [GitHub Mermaid diagrams documentation](https://docs.github.com/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams#creating-mermaid-diagrams)).

REQUIRE:

- Use fenced Mermaid blocks (` ```mermaid `) only.
- Keep flowchart node labels short and plain to maximize GitHub rendering compatibility.

PREFER:

- Put detailed REST endpoints, placeholders, and URLs in the surrounding prose instead of inside node labels.

NEVER (inside Mermaid *node labels* like `nodeId[Label text]`):

- Curly-brace placeholders like `{owner}` or `{repo}` (GitHub's renderer frequently fails on these).
- Parentheses in label text.
- Slash-delimited paths in label text (e.g., `/repos/OWNER/REPO/...`).

Enforcement:

- `scripts/linting/check_mermaid_diagrams.py` is enforced via `pre-commit`.

### Links

REQUIRE:

- Use relative links for repository content.
- Link to SSOT documents rather than duplicating procedures.

PREFER:

- Descriptive link text.

### Linting

REQUIRE:

- Markdown MUST pass repo linting (via `pre-commit` and/or Super-Linter).
- If disabling a rule is unavoidable, keep the disable block as small as possible and add justification.

### Line Length (MD013)

REQUIRE:

- Wrap prose to a maximum of 200 characters per line.
- When a line exceeds the limit, shorten the prose rather than inserting a line break mid-sentence.

NEVER:

- Insert a line break mid-sentence to satisfy the character limit. Rewrite shorter instead.

#### Shortening techniques (adapted from *The Elements of Style*)

Use these methods to bring lines under 200 characters:

1. **Omit needless words.** Cut filler that adds no meaning.

  - "owing to the fact that" → "since"
  - "in order to trigger CI" → "to trigger CI"
  - "It is a script that consolidates" → "Consolidates"

2. **Use the active voice.** Active is shorter and clearer than passive.

  - "The command should be run by the user" → "Run the command"
  - "Each file change MUST be in its own commit" → "Commit each file separately"

3. **State positively.** Say what to do, not what to avoid.

  - "Do not manually construct branch names" → "Use `start_issue_work` for branch names"

4. **Break long comma-separated lists into bullet lists.**

  - Inline: "`# noqa`, `# nosec`, `# type: ignore`, `# nosemgrep`, `<!-- markdownlint-disable -->`"
  - As bullets, each item gets its own line and the parent sentence stays short.

5. **Use parallel structure in lists.** All items should share the same grammatical form.

  - All imperatives: "Run X. Verify Y. Commit Z."
  - All noun phrases: "`--no-verify` flag, `SKIP=<hook>` variable, inline suppressions"

#### When shortening is not enough

NOTE:

- Tables are excluded from MD013 checks repo-wide.

ALLOW:

- Use a scoped disable for MD013 only when a long URL or command cannot be shortened.

Example (scoped exception):

```markdown
<!-- markdownlint-disable MD013 -->
| Column | Example |
| --- | --- |
| Long value | https://example.com/some/really/long/path |
<!-- markdownlint-enable MD013 -->
```

## See Also

- [Documentation Standards](../documentation-standards.md)
