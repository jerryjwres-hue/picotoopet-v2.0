# PicotooPet 2.3.18.1 — Business Automation Bridge + Local Intelligence Foundation

## Status

Design target for product version `2.3.18.1`.

Base is the exact accepted 2.3.17.2 implementation head:

`1025a8cf2ca1053dec2d6fac533b46f080e7b730`

This version deliberately changes the post-17 roadmap. It does **not** make ComfyUI the center of automation. The product architecture is fixed as:

- Mac = control plane + intelligence plane.
- Windows PC = business-program/data plane + later GPU production plane.
- Local OSS 20B-class model on Mac = default reasoning engine for business analysis.
- Web GPT / paid AI = manual exception path only when the local quality gate cannot confidently continue.
- ComfyUI orchestration is deferred to a later production version after the business/intelligence bridge is stable.

## 1. Product goal

2.3.18.1 must establish a durable, replay-safe business automation loop:

`Windows business program → Work Package v1 → Mac Core → deterministic preprocessing → Mac Worker local intelligence → quality gate → Result Package v1 → Windows business program`

The first two real producer profiles are the user's existing program classes:

1. review/data analysis producers, such as Amazon review collection/analysis;
2. inspiration/idea producers, such as the Inspiration Assistant.

The architecture must remain generic so future Windows programs can use the same package contract without requiring new Mac Core business-specific endpoints.

## 2. Non-goals

2.3.18.1 does **not**:

- orchestrate ComfyUI rendering;
- generate or execute arbitrary ComfyUI workflow JSON;
- perform automatic paid-AI or Web GPT API calls;
- install or download a local LLM runtime or model;
- allow a Work Package to choose an arbitrary model, endpoint, prompt template, command, script, executable, path, or tool;
- give the local model shell, filesystem-write, browser, network-tool, Git, or subprocess capabilities;
- upload raw business datasets to third-party services;
- attempt a full creative-script/shot-production pipeline; that belongs to the next Creative Intelligence layer;
- merge `main`, tag, create GitHub Releases, or change the 2.3.17.x controlled software-publication boundary.

## 3. Recommended architecture

### 3.1 Windows Business Bridge

2.3.18.1 uses the existing signed/prebuilt Windows Control Center process as the bridge host. It does not introduce another always-on executable or Windows service.

Primary producer interface in 2.3.18.1 is a durable filesystem Inbox:

`%LOCALAPPDATA%\PicotooPet\BusinessBridge\Inbox`

A producer writes a complete package to a temporary sibling path and atomically renames it into Inbox only after all files are finished. The Control Center treats Inbox content as untrusted producer data, validates it, and uploads it through the existing authenticated Windows ↔ Mac Core control connection.

When the Control Center is closed, packages remain durable on disk and are submitted after the next start. This avoids coupling producer availability to network availability.

A future local Bridge API/CLI may be added later, but Work Package v1 is designed so both file Inbox and future API/CLI normalize to the same Mac contract.

### 3.2 Mac Core

Mac Core is the authoritative fact source for:

- Work Package identity and state;
- immutable uploaded artifact metadata;
- local-intelligence run state;
- quality decisions;
- Result Package identity and state;
- optional Deep-AI Handoff facts;
- audit/checkpoint history.

Mac Core never performs model inference inline.

### 3.3 Mac Worker

Mac Worker owns two bounded execution stages:

1. deterministic dataset preprocessing/profile construction;
2. local model inference through a closed Local Intelligence Adapter.

The Worker registers the local intelligence capability only when a trusted Mac-local model configuration is present and healthy.

### 3.4 Windows Result Outbox

Completed Result Packages are downloaded to:

`%LOCALAPPDATA%\PicotooPet\BusinessBridge\Outbox\<work_package_id>\`

The original producer can poll/watch this fixed directory and consume `result-package.json` plus bounded output artifacts. Delivery is idempotent; an identical result is never rewritten under a different identity.

## 4. Work Package v1

A Work Package is a deterministic ZIP package with exactly one top-level directory and this logical structure:

```text
<package-id>/
  work-package.json
  inputs/
    ...
```

`work-package.json` is strict JSON with `extra=forbid` semantics.

Required fields:

- `schema_version = "1.0"`
- `package_id` — UUID
- `idempotency_key` — producer-controlled stable key, bounded and opaque
- `producer_id` — fixed program identity such as `amazon-review-analyzer` or `inspiration-assistant`
- `producer_version`
- `created_at`
- `project_key` — bounded logical business project identifier
- `analysis_profile` — closed profile identifier
- `objective` — bounded business objective text treated as untrusted data, never as a system instruction
- `inputs[]`

Each input descriptor contains:

- logical `artifact_id`
- relative `path` under `inputs/`
- `media_type`
- `sha256`
- `size_bytes`
- optional `record_key_field`

Allowed input formats for 2.3.18.1:

- JSON
- JSONL/NDJSON
- UTF-8 CSV
- UTF-8 plain text

Package limits are fixed:

- maximum compressed package: 256 MiB;
- maximum uncompressed payload: 512 MiB;
- maximum 64 input files;
- maximum single uncompressed file: 256 MiB;
- no symlinks, hardlinks, absolute paths, traversal, duplicate archive paths, device files, or executable payloads.

Larger datasets must be partitioned into multiple Work Packages; 2.3.18.1 does not implement unlimited single-job ingestion.

## 5. Closed analysis profiles

2.3.18.1 ships two pilot profiles matching the current business programs:

### 5.1 `reviews.voice_of_customer.v1`

Purpose:

- identify recurring pain points;
- identify positive purchase drivers;
- detect rising themes and unusual complaints when timestamps are present;
- separate strong evidence from low-support observations;
- return ranked product opportunities with source evidence IDs.

### 5.2 `ideas.pattern_analysis.v1`

Purpose:

- group and compare inspiration/idea records;
- identify repeated hooks, structures, audience problems and angles;
- identify promising underused combinations;
- return ranked idea directions and evidence references.

Work Packages cannot define new prompt templates or analysis profiles. New profiles are source-controlled product capabilities.

Full script generation, creative brief generation and shot planning are intentionally deferred to the Creative Intelligence version after this foundation.

## 6. Deterministic preprocessing

The local LLM must not be used as a database engine.

Before inference, Mac Worker builds a bounded Analysis Context from source data using deterministic code. The exact profiler depends on the analysis profile but follows common rules:

- parse and validate source format;
- preserve stable source record IDs;
- normalize Unicode and line endings;
- remove exact duplicate records while retaining duplicate counts;
- calculate field-level and dataset-level counts;
- calculate simple frequency/time summaries when valid fields exist;
- select bounded representative evidence records deterministically;
- preserve anomalies/outliers instead of silently discarding them;
- build chunk manifests when the source exceeds one inference context;
- never invent missing values.

Preprocessing artifacts are immutable and hashed. The inference stage consumes only the generated Analysis Context, not arbitrary paths supplied by the producer.

## 7. Local Intelligence Adapter

### 7.1 Runtime neutrality

2.3.18.1 does not install a model runtime. It introduces a `LocalIntelligenceAdapter` interface whose first production adapter talks to a **Mac-loopback-only OpenAI-compatible HTTP endpoint**.

The trusted Mac-side configuration supplies:

- fixed loopback base URL;
- configured model identifier for the local OSS 20B-class model;
- bounded timeout/context/output settings.

The Work Package cannot override any of these values.

The endpoint must resolve to loopback (`127.0.0.1`, `::1`, or equivalent validated local host). Non-loopback model endpoints fail closed.

### 7.2 Model permissions

The local model receives text/context only. It gets:

- no shell;
- no subprocess;
- no browser;
- no network tool;
- no arbitrary filesystem access;
- no Git/GitHub tools;
- no ComfyUI control;
- no secrets.

Producer text and review content are explicitly framed as untrusted data and cannot alter the system-level analysis contract.

### 7.3 Prompt/template policy

Prompt templates are source-controlled and versioned by `analysis_profile`.

The model response must conform to a strict profile-specific JSON result schema. Free-form prose outside the JSON object is rejected by the parser.

Temperature and sampling settings are fixed per profile. 2.3.18.1 favors repeatability over creative variance.

## 8. Local inference execution model

Mac Worker registers a closed capability:

`local.intelligence.v1`

The queue task type is fixed:

`business.local_intelligence.v1`

A task payload contains only identifiers/digests needed to load trusted Core facts. It does not contain an arbitrary endpoint, model, prompt, path, command, or executable.

One work package may require multiple deterministic chunks. Chunk results are persisted individually, then a final synthesis pass consumes only validated chunk outputs and bounded aggregate facts.

Concurrency defaults to one local intelligence inference at a time in 2.3.18.1 to avoid memory pressure on the Mac. The design allows a later configured concurrency increase but does not expose it to Windows producers.

## 9. Quality Gate

Every model output must pass deterministic post-inference validation before it becomes a Result Package.

Mandatory checks include:

- JSON schema validity;
- result profile/version match;
- required sections present;
- confidence values within fixed range;
- all cited source record IDs exist in the immutable input set;
- no unknown artifact/path/model/tool references;
- bounded finding/opportunity counts;
- no output-size overflow;
- no internal prompt/system metadata leakage.

The quality state is one of:

- `PASS`
- `RETRY`
- `NEEDS_DEEP_AI`
- `NEEDS_HUMAN`
- `REJECT`

Local inference allows at most **two total model attempts** for one synthesis stage: initial attempt plus one deterministic correction retry when the failure is a reparable schema/evidence error. It never loops indefinitely.

Semantic uncertainty, contradictory evidence, insufficient evidence or repeated invalid output becomes `NEEDS_DEEP_AI` or `NEEDS_HUMAN`; it is not hidden by automatic retries.

## 10. Deep-AI Handoff

When quality becomes `NEEDS_DEEP_AI`, Mac Core may generate a **manual** Handoff Package. This version never sends it automatically.

The Handoff contains:

- sanitized problem statement;
- bounded deterministic dataset facts;
- bounded evidence excerpts selected by policy;
- local OSS 20B result;
- quality-gate reasons;
- exact questions for the stronger model;
- exact return JSON schema;
- source/result digests.

Raw full datasets, credentials, local absolute paths and unrelated records are excluded.

The Windows UI can export/copy the safe Handoff for manual submission to Web GPT. A future version may add approved paid-AI APIs, but 2.3.18.1 has no automatic paid call.

## 11. Result Package v1

A completed Result Package is immutable and bound to the source Work Package digest, preprocessing digest, local model configuration identity, prompt-template version and quality decision.

Common fields:

- `schema_version = "1.0"`
- `result_package_id`
- `work_package_id`
- `producer_id`
- `project_key`
- `analysis_profile`
- `status`
- `source_digest`
- `preprocess_digest`
- `model_adapter_version`
- `configured_model_id`
- `template_version`
- `quality_outcome`
- `completed_at`
- profile-specific structured result
- evidence references
- warnings
- optional `deep_ai_handoff_id`

The Result Package must never claim a source citation that cannot be resolved to an input record/artifact.

## 12. Durable states

Work Package lifecycle:

```text
Received
→ Validating
→ Uploading
→ Ready
→ Preprocessing
→ LocalInference
→ QualityCheck
→ Completed
```

Alternative terminal/attention states:

- `NeedsDeepAI`
- `NeedsHuman`
- `Rejected`
- `Failed`
- `Cancelled`

Windows delivery state is recorded independently so a completed Mac result can be retried safely if the Windows Outbox was unavailable.

All state transitions are checkpointed and replay-safe.

## 13. Transfer protocol

Business datasets are larger than ordinary control DTOs, so 2.3.18.1 introduces a bounded resumable artifact-upload protocol instead of embedding full files in JSON.

Flow:

1. Windows submits package manifest and archive digest.
2. Core creates/reuses an upload session from `package_id + source_digest`.
3. Windows sends fixed-size chunks with exact offset and chunk digest.
4. Core writes only into a package-specific staging area.
5. Finalize succeeds only when total size and full SHA-256 match.
6. Core validates archive structure and manifest file hashes before moving the package into immutable storage.

Recommended chunk size is 4 MiB. Duplicate exact chunks are idempotently accepted; wrong offsets/digests fail closed.

Download of Result Packages uses the same immutable digest principle but results are expected to be small and may use a bounded single response when under the configured threshold.

## 14. Persistence

Current 2.3.17.x database schema is 10. 2.3.18.1 adds **Migration 11** with durable tables for at least:

- `business_work_packages`
- `business_artifacts`
- `business_upload_sessions`
- `business_upload_chunks` or equivalent durable progress facts
- `local_intelligence_runs`
- `local_intelligence_chunks`
- `business_result_packages`
- `deep_ai_handoffs`

Large raw artifacts are stored on disk under a Core-owned immutable artifact root; SQLite stores identity, digest, size, relative Core-managed location and lifecycle facts. Large business datasets are not stored as SQLite BLOBs.

## 15. Windows UX

2.3.18.1 adds one native WPF page/section named **业务自动化** focused on business packages, not software-development Provider sessions.

It shows:

- producer;
- project key;
- analysis profile;
- package status;
- upload progress;
- local-intelligence status;
- local model capability health;
- quality outcome;
- result availability;
- Deep-AI Handoff availability;
- safe failure code/message.

Allowed fixed actions:

- Refresh
- Submit/retry a locally queued Inbox package
- Cancel before terminal completion
- Download/re-deliver a completed Result Package
- Export a safe manual Deep-AI Handoff

The page does not expose arbitrary prompt/model/endpoint/path/command/tool fields.

A real STA WPF Measure/Arrange/UpdateLayout smoke test is required.

## 16. Producer integration contract

The two current producer programs do not need to link against PicotooPet internals. Their minimum integration is:

1. generate a valid Work Package v1 ZIP;
2. atomically place it into the fixed Inbox;
3. remember `package_id`/`idempotency_key`;
4. watch/poll the fixed Outbox for the corresponding Result Package.

This contract is intentionally language-agnostic.

Reference producer examples/fixtures will be provided for:

- review-analysis package;
- inspiration-analysis package.

They are examples only, not additional background services.

## 17. Idempotency and recovery

The system must converge under retries and restarts.

- Same `package_id + source_digest` → same Work Package fact.
- Same `idempotency_key` with different source digest → conflict; never silently replace.
- Same completed inference identity → reuse existing validated result.
- Worker crash during inference → queue lease recovery may retry only within the fixed attempt budget.
- Core/Windows restart during chunk upload → resume from durable verified chunks.
- Windows restart after Mac completion but before Outbox delivery → re-deliver the same Result Package identity.
- Corrupt local Inbox/Outbox file → quarantine locally with safe reason; never overwrite a valid package.

## 18. Security and privacy boundaries

2.3.18.1 must preserve the existing closed execution model and additionally enforce:

- package/archive traversal defense;
- no executable payloads;
- no automatic model/runtime installation;
- no arbitrary local-model endpoint from producer data;
- loopback-only inference transport;
- no model tools;
- no arbitrary commands;
- no third-party data upload;
- no raw business data in normal logs;
- bounded/sanitized diagnostic facts;
- raw dataset content excluded from Windows approval/diagnostic pages unless explicitly opened through a bounded safe preview;
- Deep-AI Handoff sanitization before manual export;
- secrets never enter prompts, packages, results or logs.

## 19. Testing strategy

Implementation must be TDD-first.

### Core/contract tests

- Work Package strict schema and profile allowlist;
- package size/file-count/path/link/executable rejection;
- manifest SHA/size mismatch rejection;
- idempotency conflict behavior;
- resumable upload chunk ordering/digest/replay behavior;
- migration 11 and rollback fixture;
- durable state transitions;
- Result Package provenance binding;
- Deep-AI Handoff sanitization.

### Deterministic preprocessing tests

- JSON/JSONL/CSV/TXT parsing;
- exact duplicate accounting;
- stable source IDs;
- deterministic representative selection;
- bounded chunk creation;
- malformed records and partial datasets;
- no silent data invention.

### Local model tests

CI uses a deterministic fake loopback OpenAI-compatible server. It must test:

- valid structured result;
- malformed JSON then one repair attempt;
- invalid/nonexistent evidence IDs;
- timeout;
- connection unavailable;
- non-loopback endpoint rejection;
- oversized output;
- prompt-injection text inside reviews/ideas does not change tool/system policy;
- second invalid attempt becomes attention state.

CI does **not** load the real OSS 20B model and consumes no paid allowance.

### Windows tests

- Inbox atomic package discovery;
- quarantine of unsafe/corrupt package;
- upload resume;
- Outbox idempotent delivery;
- native WPF binding and layout smoke;
- no arbitrary model/prompt/path/command input surface;
- install/upgrade/recovery/rollback lifecycle.

## 20. Native CI and packages

This version changes all three runtime surfaces:

- Mac Core: migration, artifact transfer, business facts, result/handoff APIs;
- Mac Worker: deterministic preprocessing + Local Intelligence Adapter;
- Windows: Business Bridge Inbox/Outbox + WPF business automation surface.

Therefore final delivery requires all four exact-head native gates:

- Mac Core arm64 CI;
- Mac Worker arm64 CI;
- Windows WPF native CI;
- Windows formal prebuilt release CI.

Final deliverables must include precompiled Windows, Mac Core and Mac Worker packages, SHA-256 sidecars, package-level independent verification and a Chinese real-machine acceptance guide. User machines do not compile source or install SDKs.

## 21. Real-machine acceptance

The first real acceptance should use a small non-sensitive fixture or an explicitly selected sample from one of the two producer categories.

PASS requires:

1. Work Package written to Windows Inbox is detected and safely uploaded.
2. Mac Core persists the package and artifact digests.
3. Mac Worker recognizes the configured local OSS 20B-class capability.
4. Deterministic preprocessing completes.
5. Local model inference runs only against the Mac loopback endpoint.
6. Quality Gate validates evidence references.
7. Result Package returns to the Windows Outbox.
8. Result remains present and identical after Windows/Mac restart.
9. No paid AI, Web GPT automation, external model endpoint, arbitrary command or ComfyUI execution occurs.
10. If the local model is intentionally unavailable, the job waits/fails safely with a precise capability/configuration state rather than falling back to paid AI.

A second optional acceptance may deliberately force `NEEDS_DEEP_AI` and verify safe manual Handoff generation without actually submitting business data externally.

## 22. Roadmap after 2.3.18.1

The intended sequence becomes:

### 2.3.19.1 — Creative Intelligence

`business insights / inspiration → idea ranking → creative brief → script → shot plan`

This consumes Result Package v1 instead of inventing a second data bridge.

### 2.3.20.1 — ComfyUI Production Orchestrator

`approved shot plan → Windows local ComfyUI → preview → QC → final media`

ComfyUI remains a GPU production executor, not the system's decision-making center.

### Later — End-to-end business automation and optional paid-AI escalation

Only after deterministic/local-model paths are proven should the system add separately approved paid-AI APIs or unattended escalation.

## 23. Success definition

2.3.18.1 is successful when PicotooPet can accept structured output from the user's Windows business programs, process it primarily on Mac using deterministic logic plus the configured local OSS 20B-class model, enforce evidence/quality rules, and return a durable structured Result Package to Windows without involving ComfyUI or paid AI.

That establishes the reusable intelligence backbone needed for later creative generation and GPU production automation.