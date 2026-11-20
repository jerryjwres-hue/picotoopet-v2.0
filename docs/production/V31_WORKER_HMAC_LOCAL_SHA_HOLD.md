# PicotooPet V3.1 — Worker local SHA + independent HMAC (GPU held)

This CPU-only proof checks that a separately configured Windows Worker re-opened real staged files for one exact Owner-frozen Episode, rather than relying only on Windows Studio's device token.

## No extra daily clicks

1. Existing Core Owner freeze and Studio staging bind the Episode to per-shot source SHA.
2. When idle under Owner HOLD, the existing Python executor_bridge.py optionally requests a one-use Core challenge. It runs only if PICOTOO_WORKER_ATTEST_KEY is configured, throttled to once per 60 seconds.
3. Core validates frozen Plan, actual SQLite keyframe task manifests, existing Studio staging audit, and Mac managed object SHA; claim requires HTTPS outside loopback.
4. Existing Worker reopens every staged image using the same file-type/symlink/SHA validation used before local GPU submission. It HMAC-signs nonce + Episode + frozen Plan + source/bindings SHAs with its separate shared key.
5. Core consumes this one-use challenge, verifies the HMAC with constant-time comparison, revalidates frozen source and records a hash-chain audit event episode.worker_local_proof.

Every receipt keeps gpu_authorized=false and can_lease=false. No new database, scheduler, worker, Comfy POST, or GPU lease change.

## One-time configuration (not yet deployed)

Mac AppSettings needs worker_attestation_id (exact existing Worker ID) and worker_attestation_key (random base64url secret of at least 43 characters). The Windows Worker process needs the same secret in PICOTOO_WORKER_ATTEST_KEY. It must differ from device Bearer, Owner token and MASTER credential. Provisioning is not automated in this PR; do not put secrets in GitHub, logs, or chat. Mac diagnostics redact the key. No requirement to enter a key every episode.

## Limits

This is HMAC-authenticated Worker-reported SHA validation, not hardware attestation, copyright verification, GPU authorization or permanent file immutability. Existing Worker must rehash before GPU POST. A final single-Job lease gate still needs current Owner scope, independent MASTER review and revocation, frozen Plan and exact task, current Worker proof, dynamic policy checks, and old Journal recovery. Core Owner HOLD remains active; all new leases remain 204. No user PC/GPU or real media used.