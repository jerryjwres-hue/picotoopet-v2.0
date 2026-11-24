# Existing FLUX/LTX components — source-grounded integration contract

This document is a *technical handoff*, not production approval. The original
files remain private on the user's Windows workstation or private Drive.
Do not include photographs, videos, LoRA weights, credentials or absolute
Windows user-home paths in this repository. No GPU work is authorized.

## Verified existing FLUX first-frame runner (P0-6)

- Source `run_flux_board.py`, SHA256:
  `fba9b6f004871664c92c75f1c36170a17ceef89b47f3a2c71032df472405d2bd`.
- `jobs_keyframes_v8.json`, SHA256:
  `3ae580a6ee6cfa33aa33ef21f64a92785f18f3ec709c390514379e2ad59c2d97`.
- Embedded V8_S2 workflow (actual Comfy output), SHA256:
  `2c45a040650534261b4a01418d779c5107487a17f190d63e257d247361f81e74`.
- Existing verified runner's `build(job,seed,refs)` handles a local
  FLUX.2 Klein 4B fp8 + qwen_3_4b + flux2 VAE, an optional
  `LoraLoaderModelOnly(maotai_lora_v2.safetensors, strength=0.9)`,
  ReferenceLatent per image, Flux2Scheduler(4 steps), 864×1536,
  one or more job seeds. No need to rewrite its model nodes.
- The original runner launches private local ComfyUI 127.0.0.1:8190
  with API cloud nodes disabled. **Do not call its `main()`** during
  architecture or CPU-only CI validation.
- Existing C8B master SHA:
  `c6d7e556b8047d06d6ba7c408e8fdde26d3d16dd59d3c029e901847beac8f59b`.
- B1 scene `PL3b_E_dogeye_in_strip_v2.png`: the retrieved inventory
  records **only a prefix/suffix** `c89f7c8d…c043`, not a complete
  SHA256. Therefore no full B1 hash is pinned in source. The selected
  Windows scene image must be rehashed and then resolved against a
  registered, Owner-approved Core artifact before production.
- Existing LoRA v2 SHA:
  `5972e7f782e3e4ed16b764441fdb66d638cb6a8ba85fb8226d95feeb98e8eb70`,
  46,223,616 bytes. v1/c001 is archived, not an alternate identity source.

`scripts/prepare_existing_flux_board_shot.py` is an optional **CPU-only**
preparation bridge. It checks the unmodified private source SHA, reads the
actual local C8B, user-selected scene and LoRA bytes, invokes only its exact
existing `build()` on verified bytes, and writes a single-shot legacy jobs
file plus the exact candidate graph and provenance manifest. This verifies
the scene's local digest but **does not** independently establish its B1
identity, Core registry binding or Owner approval. It **does not** start ComfyUI, copy
assets, submit a prompt or mark a character/first frame approved.

A suitable JSON request (locally owned, not stored in this repository) is:

```json
{
  "schema": "picotoo.existing-flux-board-shot.v1",
  "source_storypack_sha256": "<exact 64-character SHA256>",
  "source_output_profile": "p0_landscape",
  "shot_id": "S02",
  "seed": 2026112901,
  "prompt": "mtai_dog, one adult malamute in the approved room, one coherent action",
  "references": [
    {
      "role": "character_master",
      "relative_path": "refs_real/MASTER_body_C8B_v1.png",
      "sha256": "c6d7e556b8047d06d6ba7c408e8fdde26d3d16dd59d3c029e901847beac8f59b"
    },
    {
      "role": "scene_master",
      "relative_path": "refs/B1_scene_master.png",
      "sha256": "<exact complete SHA256 from local Windows B1 inventory>"
    }
  ]
}
```

These filenames are **examples only**; actual local reference names must be
verified. The `source_output_profile` is recorded unchanged. A landscape
StoryPack is NOT converted or certified as 864×1536 just because the legacy
FLUX runner makes a portrait still. The example does not imply any Owner
approval. Any output remains `CREATIVE_DRAFT_ONLY`.

## Original LTX Desktop 1.3.1 local controller (P0-4)

- Local source `PicotooPet-LTX.ps1`, SHA256:
  `ace2b5f39496ea7cdc2b1122790c5e83afb9d60b6c8abc675187395e7e9e5e8f`.
- Connects to local `http://127.0.0.1:41955` only, with paired DPAPI
  Bearer credential (never embedded in source/control-plane jobs).
- Current modes `Pair`, `Status`, `Export`, `Audit`, `Submit720`.
  **Submit720 is hard-coded to 8 seconds and null seed, not a ready
  general-purpose three-shot adapter.**
- Before POST, checks LTX Desktop settings:
  `user_prefers_ltx_api_video_generations != true`,
  `use_local_text_encoder == true`, local model `ltx-2.5-fast`
  downloadable status and advertised resolution/duration/ratio.
  It refuses busy queues, duplicate jobs and uncertain POST states.
- POST `/api/assets/upload` (multipart `file`), then ONE POST to
  `/api/generations/image-to-video` with `contract_version=1`,
  `params` (model `ltx-2.5-fast`, resolution `720p`,
  aspectRatio `9:16`, fps `24`, duration, seed, cameraMotion
  `none`, negativePrompt `""`, promptProvenance `typed`),
  and `inputs.startFrame.assetId`.
- `GET /api/generation-queue`, `GET /api/generations?feature=image-to-video`,
  `GET /api/generations/{id}` and authenticated restricted signed
  `/api/assets/<id>/bytes?... ` export. Never accept arbitrary download URLs.
- Historical S1/S2 receipts report 4s, 24fps, seeded jobs, but their actual
  submitting client and `Generation.lane` were **not verified**. Do not
  claim those specific historical runs were local solely from this script.
- The settings checks are a pre-POST local-only guard. Once a generalized
  adapter is connected to the signed Worker attempt, verify that resulting
  `Generation.lane == "local"` or STOP / remain unapproved. If the server
  omits lane, do not invent it.
- The historic observed output was 704×1280, 24 fps, 97 frames
  (about 4.04 s). **704×1280 is not mathematically 9:16**; profile
  geometry and final video frame/timing must be independently audited.
- Do not copy the failed direct `ltx_pipelines.distilled` CLI route into
  production. Reuse the local Desktop REST controller semantics.

## Pending integration boundary

Do not infer a production grant from the above. The actual executable
chain still requires: Core asset approvals, an explicitly chosen episode
output profile, accepted per-shot first frames, frozen StoryPack+ProductionPlan,
a signed Worker attempt with local-only LTX execution and artifact receipts,
then visual review. Original 11-21 horizontal StoryPack stays unchanged.
GPU HOLD remains asserted until those gates are genuinely satisfied.
