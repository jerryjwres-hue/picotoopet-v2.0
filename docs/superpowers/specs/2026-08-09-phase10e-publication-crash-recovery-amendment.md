# Phase 10E Publication Crash-Recovery Amendment

Date: 2026-08-09
Product version: 2.3.17.1
Applies to: `2026-08-09-phase10e-controlled-publish-draft-pr-2.3.17.1-design.md` and its implementation plan.

## Decision

The publication Worker task uses `max_attempts = 2`, not 1.

This is **not** a general retry policy and does not permit repeated external writes after an ordinary publication failure. The second attempt exists only so the existing queue lease-recovery mechanism can recover one process-crash / lease-expiry window after an approved external write may already have happened.

## Required semantics

1. A normal handler error is translated into a terminal Publication Candidate status (`base_moved`, `remote_ref_conflict`, `auth_unavailable`, `policy_blocked`, `push_failed`, `pr_conflict`, `pr_failed`, or `failed`). It is not automatically re-queued by the Publication coordinator.
2. If the Worker process disappears while a task lease is active, the existing queue recovery mechanism may return that task for its second and final attempt.
3. The recovery attempt must re-read external facts before writing:
   - if the fixed remote ref already equals the approved `commit_sha`, reuse it and do not push again;
   - if the exact Open Draft PR already exists with the approved repo/base/head/head SHA, reuse it and do not create another PR;
   - any differing remote SHA, multiple PRs, non-Draft PR, wrong base, wrong head, or wrong head SHA is a conflict and stops.
4. The fixed task type remains `provider.publish.pr-create-v1`; approval remains `provider.publish.pr-create-v1` and binds the same immutable scope.
5. No force push, merge, tag, release, main write, or unbounded retry is introduced.

## Test requirement

Native CI must include a deterministic local-bare-Git + fake-GitHub-CLI test that executes a successful publication, simulates loss of local finalization facts after the external facts exist, and proves a replay adopts the exact existing remote ref and Draft PR without creating a different external write.
