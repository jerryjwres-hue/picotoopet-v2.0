# P0-B explicit per-user Media Worker

This is a CI-built **developer preview**, not a formal PicotooPet release or installer.
Do not compile it on the user's daily computer. No SDK/service/Task Scheduler/Startup installation.
No new renderer, production database or UI is introduced. The same ProductionExecutionService
uses existing Mac Core claims, snapshots, heartbeat, attempts and result evidence, and the existing
ComfyProductionClient/frozen Wan graphs. The executable loads the Desktop assembly for that executor;
it does not instantiate Application, Window, Dispatcher or ControlCenterSession.

Use the complete precompiled `P0-MediaWorker-DeveloperPreview-<run-id>` CI artifact, never scattered DLLs.
Check `p0-worker-evidence.json` for the exact source SHA and native run ID. It explicitly states
`user_install_allowed=false` (not a formal installer). From that bundle, an operator explicitly runs
`PicotooPet.MediaWorker.exe` as the already-paired Windows user, **not LocalSystem/admin**.
Normal Windows Goal UI remains the daily product interface; this preview's console is not a replacement UI.

Closing WPF does not affect the worker. To explicitly stop it use Ctrl+C or
`PicotooPet.MediaWorker.exe --stop`. This stops polling/heartbeats, not every ComfyUI job globally.
Any already-submitted prompt remains journaled and must reconcile on restart before a fresh GPU job.
To explicitly request cancellation of one Core job use `PicotooPet.MediaWorker.exe --cancel <job-id>`;
the worker drains/reconciles that prompt before admitting another job. It never sends global Comfy interrupt.
Stopping Worker is not the same as Core job cancellation.

Credentials remain in existing Windows Credential Manager target `PicotooPetV2/MacCoreApiToken`.
Mac endpoint is read from existing `%LOCALAPPDATA%/PicotooPetV2/Desktop/settings.json` on each reconnect.
Local submission uncertainty lives under `%LOCALAPPDATA%/PicotooPetV2/MediaWorker/v1`, without tokens,
leases, authored prompts or a second authoritative job lifecycle. Do not delete unresolved journals.
Core live lease is respected; after process death recovery can wait up to its expiry before claiming.
Known prompt IDs resume history. Lost POST responses reconcile exact graph digests against queue/history.
Empty/evicted/ambiguous history means `MEDIA_SUBMISSION_UNKNOWN`, **not permission to POST again**.
Malformed journal, conflicting digest/prompt and missing models fail closed with bounded Windows messages.
One process lock plus a per-user cross-process GPU lock and unresolved-submission barrier serialize jobs.

## Current scope / honest acceptance

This P0 stage keeps raw Comfy WebM/Production package completion independent of GUI lifetime.
Existing C004/C007–C012 assembly/QA/receipt paths and Goal projection are unchanged; no alternative MP4
assembler or unverified final-delivery status is added. The Stage-2 UI/postproduction integration remains
with the existing pipeline/controller. Automatic startup packaging/signing/installation is not performed.

`LIVE_MAC_CORE=UNVERIFIED`, `REAL_COMFY_GPU=UNVERIFIED` until physical-device output with prompt_id,
WebM SHA and canonical Core package is checked. Offline fake HTTP/native CI is not live GPU evidence.
First physical test, after controller-approved preview deployment: explicitly start this precompiled
worker as the paired user, create one eligible Goal/Production job in the existing Windows UI, close
the GUI while that one prompt renders, reopen it, and verify unchanged prompt_id plus output/package SHA.
Do not repeat generation unless preflight/model checks and API readiness are positive.
