#!/usr/bin/env bash
set -euo pipefail

# Sync labels for the issue taxonomy. Idempotent: creates missing labels and edits existing ones.

REPO="${1:-}"
if [[ -z "${REPO}" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

if [[ -z "${REPO}" ]]; then
  echo "Unable to resolve repository. Pass owner/repo as first argument."
  exit 1
fi

ensure_label() {
  local name="$1"
  local color="$2"
  local description="$3"

  if gh label list --repo "${REPO}" --limit 200 --search "${name}" --json name -q '.[].name' | grep -Fxq "${name}"; then
    gh label edit "${name}" --repo "${REPO}" --color "${color}" --description "${description}" >/dev/null
    echo "updated: ${name}"
  else
    gh label create "${name}" --repo "${REPO}" --color "${color}" --description "${description}" >/dev/null
    echo "created: ${name}"
  fi
}

ensure_label "runtime-correctness" "B60205" "Bugs or tasks that affect whether the port runs correctly."
ensure_label "teaching-value" "0E8A16" "Work that improves the learnability of reverse-engineering and systems concepts."

ensure_label "P0" "D93F0B" "Blocks startup, causes crashes, or risks corruption."
ensure_label "P1" "FBCA04" "Core behavior is wrong; workaround may exist."
ensure_label "P2" "0E8A16" "Non-blocking correctness/performance/docs improvement."
ensure_label "P3" "C5DEF5" "Nice-to-have cleanup."

ensure_label "concept-memory-layout" "5319E7" "Pointers, structs, binary layouts, and state representation."
ensure_label "concept-control-flow" "1D76DB" "Loops, state machines, update/render/input sequencing."
ensure_label "concept-io-protocols" "0052CC" "File/network/protocol behavior and parity."
ensure_label "concept-tooling" "006B75" "Debuggers, traces, tests, and reproducible scripts."

ensure_label "parity" "6F42C1" "Behavior should match observed original behavior."
ensure_label "regression-test-needed" "D4C5F9" "Fix requires test coverage before closure."
ensure_label "nondeterministic" "E99695" "Timing/flaky behavior needs deterministic handling."
ensure_label "good-first-teaching-bug" "7057FF" "Small bug suitable for onboarding via real fixes."

echo "Label sync complete for ${REPO}"
