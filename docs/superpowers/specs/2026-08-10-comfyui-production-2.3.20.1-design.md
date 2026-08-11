# PicotooPet 2.3.20.1 — ComfyUI Production

## Status

Approved continuation of the previously frozen roadmap: product version `2.3.20.1` is the first formal Windows GPU production layer and is stacked on exact 2.3.19.1 source head:

`dd9188676815e61ea81093c4281d9e2b76bc02cc`

The architectural roles remain unchanged:

- Mac Core = durable control/fact plane.
- Mac Worker + local `gpt-oss:20b` = intelligence/creative reasoning plane.
- Windows = business ingress/egress plus local GPU production executor.
- ComfyUI = loopback-only GPU graph executor, never the decision engine.
- Web GPT / paid AI = manual exception path only.

## 1. Product goal

2.3.20.1 converts one immutable 2.3.19.1 `creative_ready` Creative Package v1 into a durable, auditable production run and a Production Package v1:

`Creative Package v1 → Production Job → Production Plan → Windows Preflight → ComfyUI Shot Runs → Output Validation → Production Package v1 → production_ready`

`production_ready` means that all supported render tasks completed and their output bytes, hashes, provenance, workflow-template identities, model identities and execution evidence were captured. It does **not** mean editorially approved, publish-ready, uploaded, posted, or automatically accepted by a human.

## 2. Approaches considered

### A. Core-owned production facts + closed Windows ComfyUI executor — selected

Mac Core owns Production Job state, plan digests and immutable Production Package metadata. Windows receives only a bounded plan, binds it to source-controlled workflow templates, calls local ComfyUI on loopback, validates returned artifacts, and commits result metadata back to Core.

Benefits:

- preserves the durable fact-plane architecture;
- keeps arbitrary ComfyUI graphs out of API payloads;
- gives restart/idempotency semantics across machines;
- supports exact provenance from output media back to the Creative Package and original evidence chain;
- keeps paid/cloud rendering out of the unattended path.

### B. Windows-only production state

Simpler initially, but would split durable state between Mac Core and the Windows filesystem. Rejected because recovery, audit and idempotency would become machine-local and harder to reconcile.

### C. Mac Worker directly controls ComfyUI

Rejected because it would give the reasoning plane direct production authority and require additional Mac→Windows execution networking. The local model must not receive ComfyUI graph or command authority.

## 3. Frozen input boundary

A Production Job consumes exactly one Creative Package v1.

The source package must:

- exist in Core-managed immutable creative storage;
- have `quality_outcome = PASS`;
- have source Creative Job state `creative_ready`;
- use `creative_profile = creative.content_plan.v1`;
- have a valid package digest and resolvable shot/beat/source provenance;
- contain at least one shot.

Windows cannot upload or substitute a different Creative Package body for a Production Job. Only the Core-stored package identity/digest is authoritative.

## 4. Closed production profile

2.3.20.1 ships exactly one first-class production profile:

`production.comfyui.v1`

The profile is source-controlled and owns:

- supported render intents;
- workflow-template IDs;
- model-role bindings;
- prompt compiler version;
- fixed negative prompt policy;
- resolution/frame/fps bounds;
- seed derivation policy;
- output validation rules;
- retry budget.

Windows cannot define new production profiles through Core APIs.

## 5. Supported render boundary

The initial formal executor supports the existing installed Wan2.2 TI2V 5B inventory for:

- `GENERATIVE_VIDEO` → text-to-video workflow;
- `IMAGE_TO_VIDEO` → image-to-video workflow when a valid local input asset is explicitly bound by the plan.

The 5B model is selected because the existing PicotooPet model manifest already pins:

- `wan2.2_ti2v_5B_fp16.safetensors`;
- `wan2.2_vae.safetensors`;
- `umt5_xxl_fp8_e4m3fn_scaled.safetensors`.

Other 19.1 render intents are deterministic `NEEDS_HUMAN` in 20.1 rather than silently mapped to an unrelated renderer:

- `GENERATIVE_IMAGE`;
- `PRODUCT_ASSET_COMPOSITE`;
- `TEXT_CARD`;
- `EXISTING_ASSET`.

No automatic model download is introduced by 20.1.

## 6. Production Plan v1

Mac Core deterministically compiles the Creative Package into a bounded Production Plan v1. Each shot plan item becomes one `ProductionTask` containing only:

- `production_task_id`;
- `shot_id`;
- `beat_id`;
- `render_intent`;
- `workflow_template_id` from an allowlist;
- deterministic positive prompt text compiled from subject/environment/action/framing/lighting/style/continuity fields;
- source-controlled negative prompt policy ID;
- bounded width/height/fps/frame-count;
- deterministic seed derived from Production Job ID + shot ID + plan version;
- optional trusted asset reference for image-to-video;
- expected model roles;
- source Creative Package/shot digests.

The plan cannot contain:

- arbitrary ComfyUI node graphs;
- arbitrary node IDs/classes;
- model filenames or filesystem paths supplied by the producer/model/user payload;
- shell/PowerShell/Python commands;
- URLs;
- network endpoints;
- arbitrary sampling names/schedulers;
- custom-node install instructions;
- API keys.

## 7. Workflow templates

Windows ships source-controlled API-format templates under a dedicated production workflow directory.

Initial IDs:

- `comfy.wan22.ti2v5b.t2v.v1`
- `comfy.wan22.ti2v5b.i2v.v1`

The templates use only ComfyUI native/core node classes required by the official Wan2.2 5B example and are validated before use. Runtime mutation is limited to explicitly declared slots such as positive text, seed, size, length, fps, filename prefix and optional input image.

Template validation must reject:

- unexpected node classes;
- changed model loader values;
- unknown output nodes;
- remote/API/provider nodes;
- custom-node classes;
- paths outside trusted model/input/output roots;
- graph mutation outside declared slots.

Template digests are included in Production Package provenance.

## 8. ComfyUI transport boundary

The Windows executor talks only to a local ComfyUI endpoint:

`http://127.0.0.1:8188`

The host and port are fixed in 20.1 runtime policy and are not accepted from Core job payloads or UI fields.

Required calls are bounded to local execution/read APIs such as:

- `GET /object_info` for preflight;
- `POST /prompt` for submission;
- `GET /history/{prompt_id}` or equivalent local compatibility endpoint for completion evidence;
- local output file reads from the trusted ComfyUI output root.

LAN bind, cloud Comfy API, partner/API nodes and automatic external network rendering remain prohibited.

## 9. Windows preflight

Before any render, the executor verifies:

1. ComfyUI responds on loopback.
2. Required native node classes are present in `/object_info`.
3. The configured Comfy data/model roots do not target `resources\ComfyUI`.
4. Required model files exist under trusted model categories.
5. Required model files match the hashes pinned in `model_manifest.json` when a hash is available.
6. Workflow templates pass the closed-template validator.
7. Production output root is writable and outside the Comfy Desktop immutable resource tree.
8. NVIDIA availability is recorded as execution evidence, but absence is an explicit preflight failure rather than a reason to switch to cloud rendering.

Preflight failure does not partially mutate Production Job outputs.

## 10. Durable data model

Database schema advances to `13`.

Core adds Migration 13 tables for:

- `production_jobs`;
- `production_tasks`;
- `production_attempts`;
- `production_packages`.

### Production Job states

- `Ready`
- `Claimed`
- `Preflight`
- `Rendering`
- `Collecting`
- `QualityCheck`
- `production_ready`
- `NeedsHuman`
- `Failed`
- `Cancelled`

A job is idempotent by source Creative Package digest + production profile + idempotency key.

### Production Task states

- `Pending`
- `Running`
- `Succeeded`
- `NeedsHuman`
- `Failed`
- `Cancelled`

Each task stores the template ID/digest, prompt digest, seed, declared dimensions/frame/fps, Comfy prompt ID, attempt count, output relative paths/digests and failure code.

## 11. Claim/lease model

Windows must claim a Core Production Job before execution. The claim returns a short-lived opaque lease token bound to job ID, executor ID and plan digest.

Rules:

- only one active executor lease per job;
- heartbeat renews the lease while rendering;
- expired leases can be safely reclaimed;
- result commits require the matching active lease + plan digest;
- arbitrary state changes are not exposed to Windows;
- a completed `production_ready` job is immutable.

## 12. Retry and recovery

Each shot has at most two ComfyUI execution attempts total:

- initial attempt;
- one retry only for explicitly retryable local failures such as transient queue/execution interruption.

Deterministic failures are not retried:

- missing/incorrect model;
- unknown node class;
- template digest mismatch;
- unsupported render intent;
- invalid output path;
- output hash/size validation failure;
- provenance mismatch.

Restart recovery reads Core state first. A task already committed as `Succeeded` is never re-rendered unless a future product version adds an explicit human-authorized regeneration operation.

## 13. Output validation

A successful shot output must:

- exist under the trusted production output root;
- use an allowed extension for the workflow profile;
- be non-empty;
- resolve to the expected production task;
- have a recomputed SHA-256 digest;
- have recorded byte length;
- carry no path traversal or symlink escape;
- have Comfy prompt/history evidence that resolves to the submitted task/template digest.

The deterministic gate does not claim to judge artistic quality, animal anatomy, motion quality or brand suitability. Those remain real-machine/human acceptance concerns.

## 14. Production Package v1

After every supported task succeeds, Core writes an immutable Production Package v1 manifest.

The package records:

- `schema_version = "1.0"`;
- `production_package_id`;
- `production_job_id`;
- `production_profile = "production.comfyui.v1"`;
- source Creative Package ID/digest;
- source Creative Job ID;
- plan digest;
- executor ID;
- ComfyUI endpoint policy (`loopback-only`);
- workflow-template IDs/digests;
- model roles/filenames/hashes from trusted manifest;
- per-task shot/beat mapping;
- prompt digests and seeds;
- Comfy prompt IDs;
- output relative paths/SHA-256/byte lengths;
- flattened creative/source evidence provenance;
- warnings/failures;
- completion timestamp;
- `quality_outcome = PASS`.

Large media remains on the Windows production root in 20.1; Core stores immutable manifest/provenance rather than duplicating all rendered video bytes to the Mac database/artifact store. The package therefore represents exact content-addressed output identities and trusted relative locations, not a second copy of media.

## 15. Windows Control Center

The existing Business Automation page gains a separate Production panel after Creative Intelligence.

The panel can:

- show `creative_ready` packages eligible for production;
- create a Production Job with the fixed profile;
- run read-only ComfyUI preflight;
- claim/start the job;
- show per-shot status/progress/failure code;
- expose output folder after success;
- show Production Package identity/digest;
- cancel an active job.

The UI cannot edit raw workflow JSON, model paths, endpoints, node classes or command lines.

## 16. Security invariants

2.3.20.1 must preserve all previous release invariants and additionally guarantee:

- ComfyUI loopback-only execution;
- no arbitrary workflow graph from user/model/API;
- no custom-node install or execution dependency in the formal profile;
- no automatic model download;
- no cloud/partner/API node usage;
- no shell/subprocess authority for local LLM output;
- no paid AI fallback;
- no remote renderer fallback;
- no direct modification of Comfy Desktop `resources\ComfyUI`;
- no path traversal/symlink escape for input/output files;
- immutable committed output identities;
- no auto-publish after render.

## 17. Test strategy

Implementation is TDD-first.

### RED contract tests

Add failures for:

- product version still 2.3.19.1;
- database schema still 12;
- missing Migration 13;
- missing production profile/models/repository/API;
- workflow templates accepting unknown nodes or changed model loaders;
- endpoint policy allowing non-loopback hosts;
- unsupported render intents incorrectly executing;
- arbitrary workflow/model/path/URL/command fields accepted from API payloads;
- missing Windows Production panel.

### Core tests

Cover:

- input eligibility;
- deterministic plan compilation;
- seed/prompt digests;
- idempotency;
- lease/heartbeat/reclaim;
- state machine legality;
- task result commit validation;
- package provenance;
- migration 12→13.

### Windows tests

Cover:

- exact workflow-template allowlist;
- API-format graph structure;
- model-role bindings;
- loopback-only Comfy transport;
- `/object_info` preflight parser;
- fake local Comfy server submit/history flow;
- output-root traversal/symlink rejection;
- WPF Measure/Arrange/UpdateLayout for the Production panel;
- published EXE self-test.

### Native CI/release gates

Run all required exact-head native workflows:

- Mac Core arm64;
- Mac Worker arm64 when shared package/runtime impact requires it;
- Windows Control Center native WPF;
- Windows prebuilt formal release gate including install/upgrade/recovery/rollback.

The final installer set is cumulative over 2.3.19.1 and must not require the user to install 19.1 first when the standard upgrade contract permits direct migration through schemas 10→11→12→13.

## 18. Non-goals

2.3.20.1 does not:

- add image-generation models not already present in the trusted manifest;
- automatically download models/custom nodes;
- perform final video editing, audio mixing, captions or multi-shot timeline assembly;
- judge subjective creative quality;
- publish to social platforms;
- call cloud Comfy or partner/API nodes;
- merge `main`, tag or create a GitHub Release.

## 19. Acceptance boundary

CI/package acceptance requires:

- all exact-head native gates PASS;
- formal installer lifecycle PASS;
- independent post-download hash/manifest/archive verification PASS;
- workflow-template static validation PASS;
- cumulative migration/runtime verification PASS.

Real-machine acceptance remains a separate daily user validation step and must include at least one actual local Wan2.2 render on the user Windows GPU before 2.3.20.1 can be called machine-validated.
