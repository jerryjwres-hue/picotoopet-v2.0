# Issue #229 State Spine v1.1.0 Implementation Plan

**Spec:** `docs/superpowers/specs/2026-11-06-issue-229-state-spine-v110-design.md`

**Base:** PR #227 `1d81b62338a54f53d37c8d41027dd8b2fee049b1`

## Task 1: strict state_facts.v1 contract

- Add failing unit tests for canonical digest stability, per-field evidence coverage, taxonomy
  authority, strict extra-field rejection, and missing-source `NEEDS_HUMAN` without calling a
  supplied model callback.
- Implement frozen Pydantic contracts and canonical digest validation in a new pure creative
  module.
- Run the focused tests and commit.

## Task 2: deterministic State Spine and locked binder

- Add failing tests for deterministic S0-S3 bytes/digest, shared adjacent state IDs, allowed
  micro-events, locked-field rejection, unchanged lock projection, and compiled prompt fields.
- Implement deterministic state construction, strict unlocked proposal types, the existing
  `PetOnlyVideoBibleDraft` binder, and lock projection verification.
- Represent the blink/breathing Story Gate incompatibility as an explicit STOP reason.
- Run focused tests and commit.

## Task 3: regression, compatibility, and verification

- Add a frozen synthetic fixture derived from the retained PR #228 synthetic artifact and verify
  its own digest before use.
- Add tests proving wrong taxonomy fails, legacy profile/template bytes are unchanged, and the
  existing Video Bible quality review still evaluates the bound draft.
- Run focused tests, Ruff, relevant Mac CI slices, and the full native suite. Distinguish any
  unchanged machine-specific baseline failures from new failures.
- Review the diff for scope/security violations, commit the final result, and report the owner UI
  activation blocker.

