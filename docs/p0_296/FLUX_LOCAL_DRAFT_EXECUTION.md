# P0-6 — Explicit existing FLUX draft execution

This uses the historically verified original run_flux_board.py (source SHA pinned by preparation) rather than a new graph. It is Windows-only, offline, and opt-in. All output remains creative draft; no Owner approval, production authorization or visual PASS is inferred.

## Operator prerequisites

- Existing Windows Core/Worker local state, explicit valid HOLD plus armed marker, no pending production journal.
- Both 8188 and 8190 idle, no other GPU-heavy application. The original runner checks VRAM.
- Exact historical ComfyUI standalone install, actual maotai_lora_v2.safetensors under its models/loras folder, verified original runner and reference bytes. If the real installed model uses a different registered directory, stop and verify it rather than guessing.
- Frozen Creative Package ZIP SHA and reference map as used by prepare_existing_flux_board_shot.py.

## Single command (local only)

```powershell
# 01. Supply the existing exact local paths; select a fresh run directory.
#     Omit --shot for all three shots; use a new variant for an individual reroll.
python scripts/run_existing_flux_board_batch.py `
  --package $PackageZip --package-sha256 $PackageSha `
  --reference-map $ReferenceMap --runner $OriginalRunner `
  --lora $ActiveLoraV2 --run-dir $NewRunDirectory --variant 0 --execute
```

The command prepares the batch, stages the pinned legacy source and exact reference files, acquires the same GPU lock as the existing Worker, runs the original local FLUX component, then verifies all expected PNG embedded graphs. Import the resulting keyframe-candidates.json in the existing Reference Preview using the parent of the run directory as output root. Multiple variant manifests share that root.

The script does not release HOLD. The production Worker also refuses a new GPU acquisition while a durable flux-draft-in-progress.json marker exists. Failure or timeout leaves the marker for explicit local reconciliation; do not delete it until private Comfy process, ports, GPU activity and results have been checked. An interrupted original runner can leave a child process; this is intentionally not treated as successful termination. A successful full collection and idle ports remove the marker. Real device execution is not claimed by synthetic CI.

## Desktop integration

The installed Reference Preview now provides explicit full-batch and per-shot FLUX actions. Configure the trusted local file `%LOCALAPPDATA%/PicotooPetV2/MediaWorker/v1/flux-draft.json` once with exactly `{"runner_path":"<absolute original run_flux_board.py>","reference_map_root":"<absolute local map folder>"}`. Put each package-specific map at `<reference_map_root>/<64-character Creative Package SHA256>.json`. The desktop downloads and hashes the current Creative ZIP itself and runs only its packaged helper scripts with the fixed historical Python executable. All still candidates remain unreviewed. Up to eight recent completed variant manifests are loaded for preview; old variants remain on disk. No arbitrary remote command or automatic model download is added.
