# Starter Backlog: Runtime + Teaching

This backlog is intentionally biased toward tasks that improve runtime correctness and teach reverse-engineering skills at the same time.

## P1

1. Honor idempotency keys in sink API
- Goal: Ensure repeated writes with same `Idempotency-Key` return stable outcomes.
- Tags: `runtime-correctness`, `teaching-value`, `P1`, `concept-io-protocols`, `parity`, `regression-test-needed`
- Why it teaches: Demonstrates protocol semantics and safe replay behavior.

2. Add explicit error taxonomy to sync CLI exit paths
- Goal: Distinguish transient-retry-exhausted, validation errors, and server hard failures.
- Tags: `runtime-correctness`, `teaching-value`, `P1`, `concept-control-flow`, `concept-tooling`, `regression-test-needed`
- Why it teaches: Shows how to model failure states in automation.

3. Make retry policy configurable via CLI/env with bounds validation
- Goal: Expose attempts/base/cap safely and test edge cases.
- Tags: `runtime-correctness`, `teaching-value`, `P1`, `concept-io-protocols`, `concept-tooling`, `regression-test-needed`
- Why it teaches: Connects distributed-system behavior to tunable controls.

4. Add structured log schema tests
- Goal: Assert required keys in log records (`run_id`, `attempt`, `status`, elapsed time).
- Tags: `runtime-correctness`, `teaching-value`, `P1`, `concept-tooling`, `regression-test-needed`
- Why it teaches: Teaches observability as part of debugging reverse-engineered systems.

5. Detect and fail on malformed source payload shape
- Goal: Validate missing `external_id/name/value` early with clear diagnostics.
- Tags: `runtime-correctness`, `teaching-value`, `P1`, `concept-memory-layout`, `concept-io-protocols`, `regression-test-needed`
- Why it teaches: Reinforces schema assumptions extracted from observed behavior.

## P2

6. Add parity fixture for source paging behavior
- Goal: Capture and assert expected paging edge behavior using fixture snapshots.
- Tags: `runtime-correctness`, `teaching-value`, `P2`, `concept-io-protocols`, `parity`, `regression-test-needed`
- Why it teaches: Introduces behavior capture and regression pinning.

7. Add deterministic jitter mode for tests
- Goal: Seed/random-control backoff jitter to remove flaky timing in CI tests.
- Tags: `runtime-correctness`, `teaching-value`, `P2`, `concept-tooling`, `nondeterministic`, `regression-test-needed`
- Why it teaches: Shows separation of production randomness vs test determinism.

8. Add trace artifact generation for each sync run
- Goal: Persist request timeline and retry decisions into `artifacts/superpowers/`.
- Tags: `runtime-correctness`, `teaching-value`, `P2`, `concept-tooling`, `regression-test-needed`
- Why it teaches: Makes debugging teachable and reproducible.

9. Build "bug to lesson" templates for closed issues
- Goal: Add short postmortem template linking bug cause -> fix -> concept learned.
- Tags: `teaching-value`, `P2`, `concept-tooling`
- Why it teaches: Converts maintenance work directly into lesson material.

10. Add "good first teaching bug" lane and label policy
- Goal: Curate small issues with reproduction scripts and clear acceptance criteria.
- Tags: `teaching-value`, `P2`, `concept-tooling`, `good-first-teaching-bug`
- Why it teaches: Helps newcomers learn by fixing real, bounded bugs.
