# Owner Review Principal v1 — P0 #231 (code-only security boundary)

The ordinary Mac Core API uses a **device** bearer. This new, independent principal is a
**capability for authenticated field review**, not a claim of legal identity, verified media,
a production reference, or permission to create/execute a Goal.

## Configuration and default

- An absent `PICOTOO_OWNER_REVIEW_REGISTRY_FILE` means **no owner-review credentials**.
- The optional registry must be a regular, current-user-owned file with mode `0600`,
  opened without following symlinks, containing only `token_sha256` fingerprints,
  `credential_id`, stable `actor_id`, exact `subject_keys`, explicit permissions,
  `registry_revision`, enabled status and optional expiry.
- A grant also requires a corresponding current-user macOS Keychain secret stored under
  `PicotooPetV2.OwnerReview.<credential_id>`. If the registry is missing, unreadable,
  malformed, too permissive, unprovisioned or disagrees with Keychain, the owner-review
  grant is disabled (fail closed).
- Registration requires a **separate local operator action**, a 256-bit randomly generated
  token, protected Keychain/Windows user storage and controlled rollout. There is intentionally
  **no** automatic token bootstrap, no raw token accepted in config or logs, and no default
  `pet:*` wildcard. Do not paste secrets into issues, CI, chat, source, shell history or
  Windows device bearer settings.
- The API must be restarted/reloaded after registry/Keychain change. Revocation removes or
  disables the grant and its secret; the current running configuration is immutable until
  a controlled restart.

## Separation and transport

`require_auth` is unchanged. `require_owner_principal` does not grant device API access;
presenting the device token to it returns **403**. A different owner token cannot authenticate
legacy API routes, and neither token automatically approves any facts. An authenticated owner
principal must still be checked with `authorize_owner_subject`, plus actual Goal/subject
authorization and per-field proposal/digest checks in the future review endpoints.

The dependency currently accepts **direct local-loopback peers only** and rejects unverified
proxy forwarding metadata. Remote/ordinary LAN HTTP returns **403** even with a valid owner
credential. There is no verified Windows→Mac TLS/mTLS transport yet; a network deployment
must remain **BLOCKED** until an authenticated encrypted path is separately verified.

`OwnerPrincipal` is a stable credential-derived actor identifier, not a proof of the legal
owner's physical identity. One review actor cannot replay a different actor's frozen review.
Missing/invalid/expired/revoked credentials return **401**; a valid device credential or
owner credential without the required Goal/subject/permission returns **403**.

## Current integration status

This is an **isolated, default-off authentication prerequisite**, with no live owner-review
routes, no database edits and no new Worker capability. Proposal→Preview→Atomic Commit,
real canonical evidence-binding verification, and the Windows UI remain separate #231/#232
tasks. Production Mac SHA, existing seven owner attestations and historical jobs are unchanged.
No new Goal, Ollama call, GPU request, deployment or credential provisioning is authorized by
this change.
