# PicotooPet V3.1 — exact frozen Episode admission using existing Worker/Queue

## Admission, not another executor

The Mac Core keeps its persistent Owner GPU HOLD. All old task/episode create APIs remain blocked in Owner mode. GPU admission is **disabled by default**, even with a paired Windows device or a positive MASTER report.

One-time installation/runtime opt-in: PICOTOO_SCOPED_GPU_ADMISSION=1, plus a separately configured Owner credential including production.admit, current independent MASTER reviewer with master.verify, and the existing Worker HMAC secret and ID. This branch does not enable any of these on a user device.

Owner loopback: POST /api/v1/studio/storypacks/production-admission/commit explicitly confirms a named Episode ID, exact frozen Plan SHA and current MASTER review ID. Mac validates the original Owner principal/revision, current independent reviewer, all rights evidence, source digests, Windows Studio staging event, real Worker HMAC proof and genuine Core SQLite keyframe/video/foley tasks. Owner may POST .../revoke at any time; the audit is append-only. Two different active Episodes are rejected for the same Worker.

Existing Windows executor_bridge.py requests a one-use lease challenge with its existing worker_id, resource tags, lease duration and optional Journal resume ID. The signed HMAC covers exactly the Core-selected task_id, episode, plan, worker, nonce and lease request. Only on successful validation and recheck inside the existing Core SQLite queue transaction is one task leased; all unlisted, old, cross-Episode, unsigned, revoked and unproven requests receive 204/409, never GPU work.

A previously running task must be resumed with its exact old Journal task_id and a current signed lease grant audit. Expired leases recover only the exact task, not the global queue. The Worker revalidates the Core heartbeat/revocation at the moment before writing the existing GPU inbox file. Existing local SHA rehash is retained. Already-submitted local GPU tasks are not silently terminated; original complete/fail receipts remain accepted according to old lease rules.

## What this does NOT prove

Native CPU CI validates the HTTP/SQLite/Worker contract only; it cannot attest the hardware, guarantee commercial rights beyond the independent reviewer, or validate actual media quality. Automated QC retries creating new cloned gen tasks and final film assembly in protected Owner mode still need specific admission checks; do not claim unlimited draws or final MP4 ready. The Python GPU Bridge is not yet part of the Windows prebuilt installer. Do not merge to main or activate production env flags before clean Windows installation and double-machine hold tests.

## Release tests

Assert default Owner HOLD; wrong Owner/master/worker, missing sources, old Journal, changed lease body, bad HMAC, replay and revocation all prevent GPU inbox. Check exact task/attempt/Worker and bounded budget, preserve prior SHA checks. Perform first real three-shot render only with explicit operator approval and source/attempt/Comfy history receipts.