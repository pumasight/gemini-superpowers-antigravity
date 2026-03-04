# Good-First-Teaching-Bug Policy

Use the `good-first-teaching-bug` label for small, high-signal tasks that teach real debugging and implementation habits.

## Selection Criteria

A candidate issue should:

1. Have a clear, deterministic reproduction path.
2. Touch one primary concept area (`concept-*` label).
3. Be solvable in one focused PR.
4. Require at least one regression test.
5. Avoid major architectural rewrites.

## Issue Quality Bar

Before applying `good-first-teaching-bug`, confirm the issue includes:

1. Concise symptom statement.
2. Explicit acceptance criteria.
3. Relevant files/modules to start from.
4. Suggested verification command(s).
5. Taxonomy labels (`runtime-correctness` or `teaching-value`, `P*`, `concept-*`).

## Maintainer Triage Workflow

1. Triage new issues using the taxonomy.
2. If the issue meets criteria, apply `good-first-teaching-bug`.
3. Add one implementation hint (where to start, not full solution).
4. After merge, create a short bug-to-lesson summary using:
   - `docs/bug-to-lesson-template.md`

## Current Starter Lane

At minimum, keep 3 open issues labeled `good-first-teaching-bug` for onboarding continuity.
