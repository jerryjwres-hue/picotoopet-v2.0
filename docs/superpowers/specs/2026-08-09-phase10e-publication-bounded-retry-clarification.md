# Phase 10E Publication Bounded-Retry Clarification

Date: 2026-08-09
Product version: 2.3.17.1
Supersedes the narrower retry wording in the earlier crash-recovery amendment where the two differ.

## Final rule

`provider.publish.pr-create-v1` has `max_attempts = 2`: one initial attempt plus at most one bounded recovery attempt. There is no third attempt and no unbounded publication loop.

This bounded second attempt is safe because every external operation is read-before-write and exact-identity checked:

- the remote base must still equal the approved immutable `base_commit`;
- the fixed remote publication ref is reused only when it already equals the approved `commit_sha`;
- a different remote SHA is a terminal conflict and is never overwritten;
- an existing PR is reused only when it is one unique Open Draft PR with the approved repository, base branch, fixed head branch, and exact head SHA;
- wrong/multiple/non-Draft PR facts are conflicts;
- no force push, merge, tag, release, or main write exists in this version.

The second attempt therefore covers process crashes and ambiguous transport failures (for example, a push may have reached the server before the local process lost the response) without allowing duplicate or broadened external writes.

All CI publication execution tests must use a local bare Git remote and fake GitHub CLI. Real GitHub publication remains an explicit human-approved runtime action only.
