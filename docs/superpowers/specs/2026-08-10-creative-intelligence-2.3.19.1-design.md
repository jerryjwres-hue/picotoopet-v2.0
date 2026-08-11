# PicotooPet 2.3.19.1 — Creative Intelligence

## Status

Approved design direction for product version `2.3.19.1`.

Implementation lineage is stacked on the exact 2.3.18.1 feature head:

`524c6e38a56ca489d6fbef25e42dca9c81bf8525`

This version extends the business-intelligence backbone created in 2.3.18.1. It does **not** add another Windows↔Mac data bridge and it does **not** make ComfyUI the decision engine.

The product architecture remains:

- Mac Core = durable control/fact plane.
- Mac Worker + local `gpt-oss:20b` = default intelligence/creative reasoning plane.
- Windows = business-program ingress/egress and later GPU production plane.
- Web GPT / paid AI = manual exception path only.
- ComfyUI = deferred GPU production executor for 2.3.20.1.

## 1. Product goal

2.3.19.1 turns validated business intelligence into a durable, evidence-linked creative plan:

`2.3.18.1 PASS Result Package(s) → Creative Job → Idea Ranking → Creative Brief → Script → Shot Plan → Creative Package v1`

The successful terminal state is `creative_ready`.

`creative_ready` means the Creative Package passed the 2.3.19.1 structural/provenance gates and is suitable as input to a later production orchestrator. It does **not** mean rendered, ComfyUI-executable, publish-ready, or automatically approved.

## 2. Why this boundary

2.3.18.1 already provides the reusable producer contract:

`Work Package v1 → local intelligence → Result Package v1`

2.3.19.1 consumes that contract instead of inventing a second raw-data ingestion path. The creative layer reasons over validated findings and bounded evidence references rather than re-running raw review/idea ingestion.

## 3. Non-goals

2.3.19.1 does not:

- execute ComfyUI or generate executable ComfyUI workflow JSON;
- expose ComfyUI port 8188 to LAN;
- install/download models, LoRAs, custom nodes, Ollama, or another LLM runtime;
- automatically call Web GPT or paid AI APIs;
- let Windows select arbitrary model IDs, endpoints, system prompts, tools, commands, scripts, executable paths, or sampling parameters;
- give the local model shell, subprocess, browser/network tools, Git/GitHub, arbitrary filesystem-write, or ComfyUI authority;
- create/push Git branches or PRs as part of creative generation;
- merge `main`, tag, create GitHub Releases, publish media, or claim objective creative quality where only semantic/human judgment is possible.

## 4. Creative Job

Mac Core adds a durable `CreativeJob`. A job consumes one to eight immutable 2.3.18.1 Result Packages.

Every source Result Package must:

- exist in Core-managed immutable result storage;
- have `quality_outcome = PASS`;
- have source Work Package state `Completed`;
- belong to the same `project_key`;
- use an allowed 2.3.18.1 analysis profile;
- retain resolvable evidence references.

A preferred job can combine a review-analysis Result Package with an inspiration-analysis Result Package so customer demand and creative pattern evidence remain separately traceable.

### 4.1 Creative objective

A job may contain one optional `creative_objective`, maximum 2000 UTF-8 characters. This is **untrusted business intent**, never a system prompt. It can describe goals such as emphasizing a pain point, targeting a broad audience, or avoiding a claim category. It cannot change model identity, endpoint, system instructions, schemas, tools, paths, commands, retry budgets, safety policy, or production execution policy.

If omitted, a deterministic default objective is derived from bound Result Package/project facts.

## 5. Closed creative profile

2.3.19.1 ships exactly one first-class profile:

`creative.content_plan.v1`

It owns source-controlled templates and strict schemas for:

1. `idea_ranking.v1`
2. `creative_brief.v1`
3. `script.v1`
4. `shot_plan.v1`

Windows cannot define new creative profiles or templates.

## 6. Source normalization and finding identity

2.3.18.1 Result Package findings have ranked structured findings with evidence IDs but do **not** expose a standalone `finding_id`. 2.3.19.1 must not rewrite the historical 18.1 contract.

Mac Core therefore derives a stable read-only `source_finding_ref` for every source finding:

`<result_package_id>:finding:<rank>`

and separately binds:

- source Result Package ID;
- source Result Package digest;
- finding rank;
- canonical finding content digest;
- original `evidence_ids[]`.

If an 18.1 Result Package contains duplicate/invalid ranks or a finding cannot be canonically normalized, it is ineligible for Creative Intelligence and fails closed.

The model can cite only the derived `source_finding_ref` values and the already-existing evidence IDs. It cannot manufacture new source identities.

## 7. Stage 1 — Idea Ranking

`IdeaRankingResult` contains 3–10 ranked concepts. Each concept includes:

- deterministic job-scoped `idea_id`;
- `rank`;
- `title`;
- `audience_problem`;
- `hook`;
- `angle`;
- `value_proposition`;
- `format_hint`;
- `confidence`;
- `source_finding_refs[]`;
- `source_evidence_ids[]`;
- `claim_risk = LOW | MEDIUM | HIGH`;
- warnings.

Every concept must reference at least one bound finding and one resolvable evidence ID. Novel combinations are allowed, but factual claims must remain distinguishable from creative synthesis.

## 8. Stage 2 — Creative Brief

The default winner is the rank-1 idea. 2.3.19.1 favors unattended throughput and does not add an arbitrary prompt-edit workflow between stages.

`CreativeBriefResult` contains:

- selected `idea_id`;
- target audience;
- customer problem;
- value proposition;
- primary hook;
- emotional tone;
- content format;
- desired duration range;
- key message hierarchy;
- required proof/evidence references;
- prohibited/unsupported claims;
- CTA intent;
- continuity notes;
- source finding/evidence references.

The brief preserves the difference between evidence-backed facts and creative choices.

## 9. Stage 3 — Script

`CreativeScriptResult` is a production-oriented structure, not free-form prose. It contains:

- `script_id`;
- title;
- target duration seconds;
- ordered `beats[]`;
- optional voiceover;
- optional on-screen text;
- visual intent per beat;
- CTA beat;
- evidence-backed claim references;
- unsupported-claim warnings.

Each beat has a deterministic `beat_id`. Deterministic checks include unique ordered beat IDs, duration bounds, evidence linkage for factual claims, and absence of internal prompt/config/tool leakage. The gate does not pretend to prove emotional appeal.

## 10. Stage 4 — Shot Plan

`ShotPlanResult` converts beats into renderer-neutral production instructions. Each shot contains:

- `shot_id`;
- `beat_id`;
- order;
- intended duration;
- subject description;
- environment/background intent;
- action/motion intent;
- framing/camera intent;
- lighting/style intent;
- continuity keys;
- required product/brand facts;
- source evidence IDs for factual visual claims;
- optional text/voiceover reference;
- production notes;
- `render_intent`.

Allowed descriptive `render_intent` values are:

- `GENERATIVE_VIDEO`
- `GENERATIVE_IMAGE`
- `IMAGE_TO_VIDEO`
- `PRODUCT_ASSET_COMPOSITE`
- `TEXT_CARD`
- `EXISTING_ASSET`

These values never execute a renderer.

Shot Plan v1 cannot contain ComfyUI node IDs/workflow JSON, checkpoint/LoRA paths, custom-node install commands, Python/shell commands, or external download URLs.

## 11. Creative Package v1

Successful completion writes one immutable ZIP under a Core-managed creative artifact root:

```text
<creative-package-id>/
  creative-package.json
```

The manifest contains:

- `schema_version = "1.0"`;
- `creative_package_id`;
- `creative_job_id`;
- `project_key`;
- `creative_profile = "creative.content_plan.v1"`;
- bound source Result Package IDs/digests;
- derived source finding refs/digests;
- creative objective digest;
- configured local model ID;
- model adapter version;
- stage template versions;
- stage result digests;
- quality outcome;
- idea rankings;
- creative brief;
- script;
- shot plan;
- flattened provenance/evidence references;
- warnings;
- completion timestamp.

The package identity is immutable and restart-safe.

## 12. Provenance chain

The critical invariant is:

`shot → beat → creative brief → ranked idea → source_finding_ref → source evidence`

Every factual production claim must resolve backwards to the exact 18.1 Result Package and original evidence ID. Unknown finding refs/evidence IDs are deterministic quality failures.

## 13. Local creative execution

Mac Worker adds the closed capability:

`creative.intelligence.v1`

Fixed queue task type:

`creative.content_plan.v1`

Task payload contains identifiers/digests only, such as `creative_job_id`, `source_set_digest`, and `creative_profile`. It does not contain arbitrary prompts, model IDs, endpoints, paths, commands, tools, or ComfyUI workflow data.

The trusted loopback-only OpenAI-compatible adapter introduced in 18.1 is reused. The default configured model remains `gpt-oss:20b` unless trusted Mac-side configuration changes it.

## 14. Stage execution and retry policy

Each stage is independently checkpointed.

For every stage:

- initial model attempt: 1;
- at most one correction retry for schema/provenance/format-repairable failures;
- total model attempts per stage: maximum 2.

A persisted valid stage is adopted after restart. It is not regenerated unless its immutable input identity changes; a changed input creates a new job/revision identity rather than overwriting history. There is no unbounded regeneration loop.

## 15. Deterministic Creative Quality Gate

The gate validates software-verifiable facts:

- strict schema/version;
- allowed enums;
- rank/order uniqueness;
- duration/count/text-size bounds;
- stage references resolve to earlier immutable stage facts;
- every `source_finding_ref` resolves to a bound normalized finding;
- every evidence ID resolves to a bound source result;
- factual claims have evidence linkage or explicit unsupported/creative marking;
- no prompt/config/secret leakage;
- no arbitrary executable/path/URL/ComfyUI workflow payload;
- final Shot Plan covers required script beats;
- no duplicate shot/beat identities.

Outcomes remain:

- `PASS`
- `RETRY`
- `NEEDS_DEEP_AI`
- `NEEDS_HUMAN`
- `REJECT`

Creative attractiveness, humor, emotional impact, and aesthetic taste are not asserted as deterministic facts. Low confidence, conflicting concepts, unsupported claims, or unresolved semantic uncertainty can become `NEEDS_HUMAN` or `NEEDS_DEEP_AI`.

## 16. Manual Deep-AI exception path

A failed creative stage may create a sanitized manual Creative Deep-AI Handoff containing only bounded job/project facts, creative objective, prior validated stages, bounded source findings/evidence excerpts, failed local result, deterministic quality reasons, exact return schema, and digests.

It excludes credentials, local absolute paths, full raw datasets, unrelated records, hidden system prompts, and any automatic external submission. 2.3.19.1 does not automatically call paid AI.

## 17. Persistence — Migration 12

Current schema is 11. 2.3.19.1 adds Migration 12 with at least:

- `creative_jobs`
- `creative_job_sources`
- `creative_source_findings`
- `creative_stage_runs`
- `creative_packages`
- `creative_deep_ai_handoffs`

SQLite stores bounded identities, state, digests, normalized finding facts, JSON facts, and managed relative paths. It does not duplicate raw 18.1 datasets as BLOBs. A Creative Job source set is immutable after creation.

## 18. State model

```text
Ready
→ IdeaRanking
→ BriefGeneration
→ ScriptGeneration
→ ShotPlanning
→ QualityCheck
→ creative_ready
```

Attention/terminal alternatives:

- `NeedsDeepAI`
- `NeedsHuman`
- `Rejected`
- `Failed`
- `Cancelled`

Stage state is separately durable so restart does not restart the full chain.

## 19. Windows UX

The existing **业务自动化** page gains a separated **Creative Intelligence / 创意智能** section.

It shows project key, bound Result Package IDs, creative profile, job status, current stage, local creative capability health, selected top idea, package availability, warnings/attention, and safe failure facts.

Fixed actions only:

- `准备创意方案`
- `刷新创意状态`
- `取消所选创意任务`
- `导出 Creative Package`
- `导出 Creative Deep-AI Handoff`

Preparing can select one to eight eligible PASS Result Packages from one project and optionally provide the bounded creative objective. No free model/system-prompt/endpoint/tool/command/path/ComfyUI workflow inputs are allowed.

The UI must state:

`creative_ready != rendered != publish-ready`

All read-only bindings use explicit `Mode=OneWay`; real STA `Measure/Arrange/UpdateLayout` coverage is mandatory.

## 20. API boundary

Authenticated bounded endpoints live under `/api/v1/creative/...` for:

- eligible PASS Result Packages;
- create/prepare Creative Job;
- list/get jobs;
- cancel nonterminal job;
- Creative Package metadata/download;
- manual Creative Deep-AI Handoff metadata/download.

Create accepts only source Result Package IDs, closed profile ID, optional bounded objective, and idempotency identity. It cannot accept arbitrary prompt/model/endpoint/path/command/tool/workflow fields.

## 21. Idempotency and recovery

A deterministic source-set digest binds:

- sorted source Result Package IDs/digests;
- normalized source finding refs/digests;
- project key;
- creative profile;
- normalized creative objective digest;
- stage-template version set.

Same idempotency key + same source-set digest reuses the job. Same key + different digest conflicts. Completed stage identity + same input digest is reused. Final Creative Package is immutable; a different package digest under the same identity is a conflict.

## 22. Security/privacy boundary

2.3.19.1 preserves all 18.1 restrictions and adds:

- only PASS/Completed Result Packages are eligible;
- all sources must share one project;
- maximum eight sources;
- no raw Work Package path from Windows;
- no producer-selected model/endpoint/system prompt/tool/command/executable;
- no model tools;
- loopback-only model transport;
- no automatic paid AI;
- no ComfyUI execution;
- no arbitrary URLs/download instructions in Shot Plan;
- no raw business data in normal logs/UI;
- no internal prompt/config/secrets in Creative Package/Handoff;
- bounded text/list sizes;
- provenance failures fail closed.

## 23. TDD and native verification

Implementation is TDD-first.

Core/domain RED/GREEN coverage must include Migration 12, only PASS/Completed eligibility, cross-project rejection, max-eight sources, stable finding-ref derivation and digest binding, duplicate/invalid source-rank rejection, idempotency reuse/conflict, objective bounds, state transitions, and immutable package identity.

Creative stage tests cover idea schema/ranks/provenance, brief selected-idea references, script beat identity/order/duration/claims, Shot Plan beat coverage/order/duration/allowed render intent, unknown refs, one correction retry, second failure attention, semantic uncertainty attention, and crash recovery reuse.

CI local-model tests use a deterministic fake loopback server and verify no real paid call, no tools/functions, non-loopback rejection, prompt-injection containment, output bounds, invalid JSON/reference containment, and that producer objective cannot alter model/endpoint/template/tool policy.

Windows tests cover eligible source selection, same-project restriction, no arbitrary execution/config input surface, bounded atomic Creative Package download, real STA WPF layout/binding, and 18.1 Inbox/Outbox non-regression.

## 24. Product version, CI and packages

Product version becomes `2.3.19.1`; database schema becomes 12.

Expected runtime impact:

- Mac Core: Migration 12, creative facts/API/storage;
- Mac Worker: creative coordinator/capability;
- Windows: creative UI/client/actions.

Final delivery requires current exact-head success for Mac Core arm64 CI, Mac Worker arm64 CI, Windows WPF native CI, and Windows formal prebuilt release CI.

Deliverables include precompiled Windows, Mac Core, Mac Worker packages, SHA-256 sidecars/combined manifest, independent package verification, Chinese manual acceptance, and non-sensitive creative fixture/result samples where useful. User machines do not compile source or install SDKs.

Implementation PR remains Draft/Open/Unmerged. No main merge, tag, or GitHub Release.

## 25. Real-machine acceptance

After 18.1 local intelligence is healthy and at least one Result Package is `Completed/PASS`:

1. install Mac Core → Mac Worker → Windows 2.3.19.1;
2. verify version and schema 12;
3. rerun 18.1 diagnostic/business non-regression;
4. choose one or more eligible PASS Result Packages from one project;
5. create one `creative.content_plan.v1` job;
6. observe Idea Ranking → Brief → Script → Shot Plan → QualityCheck;
7. reach `creative_ready`;
8. export the exact Creative Package;
9. restart Windows/Core/Worker and confirm identities remain and completed stages are not re-run;
10. confirm no ComfyUI job, paid AI call, shell command, Git publication, main write, tag, or Release occurred.

An optional negative acceptance forces invalid structure and verifies the two-attempt ceiling plus sanitized manual Creative Deep-AI Handoff.

## 26. Roadmap after 2.3.19.1

### 2.3.20.1 — ComfyUI Production Orchestrator

Consumes only validated `creative_ready` Creative Package/Shot Plan facts:

`creative_ready → renderer-neutral Shot Plan → Windows local ComfyUI adapter → preview → deterministic media QC → final media`

The production layer chooses audited ComfyUI workflow adapters. Creative Package never carries arbitrary executable workflow JSON.

## 27. Success definition

2.3.19.1 succeeds when validated 18.1 business intelligence is transformed primarily by the Mac-local `gpt-oss:20b` path into an immutable, evidence-traceable Creative Package containing ranked ideas, a creative brief, a structured script, and a renderer-neutral Shot Plan, with bounded retries and safe attention states, without invoking ComfyUI or paid AI.
