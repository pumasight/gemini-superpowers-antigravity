# Issue Taxonomy: Working Port + Teaching by Reverse Engineering

This project has two primary outcomes:

1. Runtime correctness: a working game port.
2. Teaching value: a reproducible, understandable reverse-engineering workflow.

Use the tags below on issues and PRs.

## Core Tags

- `runtime-correctness`: Bugs that block the game from running correctly.
- `teaching-value`: Changes that make techniques easier to learn and reproduce.

## Priority Matrix

- `P0`: Blocks startup, crashes often, or causes data/state corruption.
- `P1`: Core feature is wrong but workaround exists.
- `P2`: Non-blocking correctness/performance/docs improvement.
- `P3`: Nice-to-have cleanup.

## Teaching Focus Tags

- `concept-memory-layout`: Pointer/state layout, structs, binary formats.
- `concept-control-flow`: Event loops, state machines, input/update/render flow.
- `concept-io-protocols`: File/network/protocol behavior parity.
- `concept-tooling`: Debuggers, traces, diffing, tests, reproducible scripts.

## Quality Tags

- `parity`: Behavior must match observed original behavior.
- `regression-test-needed`: Add or update tests before closing.
- `nondeterministic`: Flaky/timing-sensitive behavior.
- `good-first-teaching-bug`: Small, high-signal bug for learning.

## How To Prioritize

1. Fix `runtime-correctness` + `P0/P1` first.
2. Prefer issues that also carry `teaching-value`.
3. Require `regression-test-needed` for every fixed bug.
4. Capture investigation notes so others can reproduce reasoning.

## Label Sync

To create/update the matching GitHub labels:

```bash
./scripts/sync_labels.sh pumasight/gemini-superpowers-antigravity
```

If no repo is passed, the script uses the current `gh` repo context.

## Teaching Templates

- Bug-to-lesson capture: `docs/bug-to-lesson-template.md`
- Onboarding policy: `docs/good-first-teaching-bug-policy.md`

## Initial Mapping (Current Demo State)

- Sync `--limit` accepted non-positive values and produced surprising partial syncs.
  - Tags: `runtime-correctness`, `P1`, `teaching-value`, `regression-test-needed`, `good-first-teaching-bug`
- Source pagination accepted invalid values (`page=0`, `limit=0`).
  - Tags: `runtime-correctness`, `P1`, `teaching-value`, `regression-test-needed`
- Retry handling missed some transient transport failures.
  - Tags: `runtime-correctness`, `P1`, `teaching-value`, `nondeterministic`, `regression-test-needed`
- Retry-After parsing could sleep too long or behave unexpectedly on malformed values.
  - Tags: `runtime-correctness`, `P2`, `teaching-value`, `nondeterministic`, `regression-test-needed`
- Pagination cap could silently hide overflow without explicit failure signal.
  - Tags: `runtime-correctness`, `P1`, `teaching-value`, `regression-test-needed`
