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

2.3.19.1 must turn validated business intelligence into a durable, evidence-linked creative plan:

`2.3.18.1 PASS Result Package(s) → Creative Job → Idea Ranking → Creative Brief → Script → Shot Plan → Creative Package v1`

The successful terminal state is:

`creative_ready`

`creative_ready` explicitly means:

- the creative package passed the 2.3.19.1 structural/provenance quality gates;
- it is suitable as input to a later production orchestrator;
- it is **not** a ComfyUI workflow;
- it is **not** rendered media;
- it is **not** automatically approved for publication.

## 2. Why this boundary

2.3.18.1 already provides the correct reusable contract for Windows business programs:

`Work Package v1 → local intelligence → Result Package v1`

2.3.19.1 must consume that contract rather than invent a second raw-data ingestion mechanism. This keeps raw review/idea datasets out of the creative layer by default and preserves the original evidence chain.

The creative layer should reason over validated findings and selected evidence excerpts, not re-run the whole data ingestion pipeline.

## 3. Non-goals

2.3.19.1 does **not**:

- execute ComfyUI;
- generate executable ComfyUI API workflow JSON;
- open ComfyUI port 8188 to the LAN;
- install/download models, LoRAs, custom nodes, Ollama, or another local LLM runtime;
- automatically call Web GPT or any paid AI API;
- allow Windows producers to select arbitrary model IDs, endpoints, system prompts, tools, commands, scripts, executable paths, or sampling parameters;
- give the local model shell, subprocess, browser, network tools, Git/GitHub, arbitrary filesystem-write, or ComfyUI authority;
- create/push Git branches or PRs as part of creative generation;
- merge `main`, tag, create GitHub Releases, or publish media;
- claim objective creative quality where only human/semantic judgment is possible.

## 4. Recommended architecture

### 4.1 Creative Job as the durable unit

Mac Core adds a durable `CreativeJob` fact. A job consumes one to eight immutable 2.3.18.1 Result Packages.

All source Result Packages must:

- exist in Core-managed immutable result storage;
- have `quality_outcome = PASS`;
- have Work Package state `Completed`;
- belong to the same `project_key`;
- use an allowed 2.3.18.1 analysis profile;
- retain resolvable evidence references.

A job may combine, for example:

- one `reviews.voice_of_customer.v1` Result Package containing customer pain points; and
- one `ideas.pattern_analysis.v1` Result Package containing inspiration patterns.

This is the preferred path for high-value creative synthesis because customer demand and creative pattern evidence remain separately traceable.

### 4.2 Creative objective

A Creative Job may contain one bounded `creative_objective` text field, maximum 2000 UTF-8 characters.

This field is treated as **untrusted business intent**, not a system prompt. It can describe goals such as:

- emphasize a specific customer pain point;
- create short-form product-education concepts;
- avoid a known claim category;
- target a broad audience segment.

It cannot alter model identity, system instructions, schemas, tools, paths, commands, retry budgets, safety rules, or production execution policy.

If omitted, the job derives a default objective from the bound Result Packages and project context.

## 5. Closed creative profile

2.3.19.1 ships one first-class creative profile:

`creative.content_plan.v1`

It owns the complete source-controlled stage templates and schemas for:

1. `idea_ranking.v1`
2. `creative_brief.v1`
3. `script.v1`
4. `shot_plan.v1`

Windows cannot define new creative profile IDs or prompt templates.

Future profiles can be added as source-controlled product capabilities without changing the Result Package bridge.

## 6. Stage 1 — Idea Ranking

Input:

- immutable PASS Result Package facts;
- bounded evidence references and excerpts carried by those results;
- project key;
- bounded creative objective.

Output is a strict `IdeaRankingResult` containing 3–10 ranked concepts.

Each concept includes at least:

- `idea_id` — deterministic job-scoped logical ID;
- `rank`;
- `title`;
- `audience_problem`;
- `hook`;
- `angle`;
- `value_proposition`;
- `format_hint`;
- `confidence`;
- `source_finding_ids`;
- `source_evidence_ids`;
- `claim_risk` — `LOW | MEDIUM | HIGH`;
- `warnings`.

Every ranked concept must be grounded in at least one bound source finding and at least one resolvable source evidence ID.

The model may propose a novel combination, but it must distinguish the novel creative synthesis from source-supported factual claims.

## 7. Stage 2 — Creative Brief

The default winner is the rank-1 idea unless a future product version introduces explicit human selection. 2.3.19.1 does not add arbitrary edit boxes for replacing the ranked idea with free-form model instructions.

`CreativeBriefResult` contains:

- selected `idea_id`;
- target audience;
- customer problem;
- promise/value proposition;
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

The brief must preserve the difference between:

- evidence-backed business facts; and
- creative choices inferred from those facts.

## 8. Stage 3 — Script

`CreativeScriptResult` is a production-oriented script, not free-form prose.

It contains:

- `script_id`;
- `title`;
- target duration seconds;
- ordered `beats[]`;
- optional voiceover text;
- optional on-screen text;
- visual intent per beat;
- CTA beat;
- evidence-backed claim references;
- unsupported-claim warnings.

Each beat has a deterministic `beat_id` so the Shot Plan can reference it without copying/guessing text identities.

The script quality gate checks deterministic facts such as:

- unique ordered beat IDs;
- duration bounds;
- all factual claims point to known source evidence or are clearly marked as creative/non-factual language;
- no internal prompt/config metadata leakage;
- no executable instructions or tool calls.

It does not pretend to prove that a script is emotionally compelling; semantic uncertainty may become `NeedsHuman` or `NeedsDeepAI`.

## 9. Stage 4 — Shot Plan

`ShotPlanResult` converts script beats into renderer-neutral production instructions.

Each shot contains:

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
- source evidence IDs when the shot visually represents a factual claim;
- optional text/voiceover reference;
- production notes;
- `render_intent` enum.

Allowed `render_intent` values in v1 are descriptive only, for example:

- `GENERATIVE_VIDEO`
- `GENERATIVE_IMAGE`
- `IMAGE_TO_VIDEO`
- `PRODUCT_ASSET_COMPOSITE`
- `TEXT_CARD`
- `EXISTING_ASSET`

These values do not execute a renderer. They are a stable abstraction for 2.3.20.1.

Shot Plan v1 must not contain:

- ComfyUI node IDs;
- ComfyUI workflow JSON;
- checkpoint/LoRA filesystem paths;
- custom-node install commands;
- Python/shell commands;
- URLs instructing external downloads.

## 10. Creative Package v1

Successful completion writes one immutable `Creative Package v1` ZIP under a Core-managed creative artifact root.

Logical shape:

```text
<creative-package-id>/
  creative-package.json
```

The manifest includes:

- `schema_version = "1.0"`
- `creative_package_id`
- `creative_job_id`
- `project_key`
- `creative_profile = "creative.content_plan.v1"`
- bound source Result Package IDs and digests
- creative objective digest
- configured local model ID
- model adapter version
- each stage template version
- each stage result digest
- quality outcome
- `idea_rankings`
- `creative_brief`
- `script`
- `shot_plan`
- flattened provenance/evidence references
- warnings
- completion timestamp

The package identity must be immutable and idempotently reusable after restart.

## 11. Evidence/provenance chain

The critical 19.1 invariant is:

`shot → beat → creative brief → ranked idea → source finding → source evidence`

The system must be able to resolve every factual production claim backwards to the exact 18.1 Result Package and original evidence identity.

Mac Core stores stage input/output digests and source-package digests. The local model never gets permission to fabricate new source evidence identities.

Unknown `source_finding_id` or `source_evidence_id` is a deterministic quality failure.

## 12. Local Intelligence execution

Mac Worker adds a closed capability:

`creative.intelligence.v1`

Fixed queue task type:

`creative.content_plan.v1`

Task payload contains only identifiers/digests required to load trusted Core facts, such as:

- `creative_job_id`
- `source_set_digest`
- `creative_profile`

It does not carry arbitrary prompts, model IDs, endpoints, paths, commands, tools, ComfyUI workflow data, or executable content.

The same trusted loopback-only OpenAI-compatible adapter introduced in 18.1 remains the default transport, with configured local model identity `gpt-oss:20b` unless Mac-side trusted configuration changes it.

## 13. Stage execution and retry policy

Each of the four creative stages is independently checkpointed.

For each stage:

- initial model attempt: 1;
- deterministic correction retry when and only when the error is schema/provenance/format repairable: maximum 1;
- maximum total model attempts per stage: 2.

A successful completed stage is never re-run after process restart unless its exact immutable input identity changed, in which case the system must create a new job/revision identity rather than silently overwrite history.

A Worker crash after a persisted valid stage result must adopt that result on recovery.

There is no unbounded regeneration loop.

## 14. Deterministic Creative Quality Gate

The quality gate validates what software can reliably establish:

- strict schema/version match;
- allowed enum values;
- rank/order uniqueness;
- duration/count bounds;
- every stage reference resolves to an earlier immutable stage fact;
- every source finding/evidence ID resolves to the bound PASS Result Packages;
- factual claims have evidence linkage or an explicit unsupported/creative marker;
- no tool/system prompt/config/secrets leakage;
- no arbitrary executable/path/URL/ComfyUI workflow payload;
- output and text sizes remain within fixed limits;
- final Shot Plan covers all required script beats;
- no impossible duplicate shot/beat identities.

Quality outcomes are:

- `PASS`
- `RETRY`
- `NEEDS_DEEP_AI`
- `NEEDS_HUMAN`
- `REJECT`

Creative attractiveness, humor, emotional impact, and aesthetic taste are not misrepresented as deterministic facts. Low confidence, conflicting concepts, unsupported claims, or unresolved semantic problems may become `NEEDS_HUMAN` or `NEEDS_DEEP_AI`.

## 15. Deep-AI exception path

If a creative stage reaches `NEEDS_DEEP_AI`, Mac Core may produce a sanitized **manual Creative Deep-AI Handoff**.

It contains only bounded information needed to resolve the failed stage:

- job/project identity;
- creative objective;
- prior validated creative stages;
- bounded source findings/evidence excerpts;
- failed local result;
- deterministic quality reasons;
- exact requested return schema;
- source/stage digests.

It excludes:

- credentials/tokens;
- local absolute paths;
- full raw business datasets;
- unrelated records;
- hidden system prompts;
- automatic external submission instructions.

2.3.19.1 does not automatically call paid AI.

## 16. Persistence — Migration 12

Current 2.3.18.1 database schema is 11. 2.3.19.1 adds **Migration 12**.

Durable facts include at least:

- `creative_jobs`
- `creative_job_sources`
- `creative_stage_runs`
- `creative_packages`
- `creative_deep_ai_handoffs`

SQLite stores bounded identities, state, digests, JSON facts and managed relative paths. It does not store large raw media or duplicate the original 18.1 raw datasets as BLOBs.

A Creative Job source set is immutable after job creation.

## 17. State model

Creative Job lifecycle:

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

Stage state is separately durable so a restart does not restart the whole creative chain.

## 18. Windows UX

The existing **业务自动化** page remains the business-facing surface. 2.3.19.1 adds a clearly separated **Creative Intelligence / 创意智能** section instead of creating another unrelated application.

It displays:

- project key;
- bound Result Package IDs;
- creative profile;
- creative job status;
- current stage;
- local creative capability health;
- selected top idea title;
- package availability;
- warnings/attention state;
- safe failure code/message.

Fixed actions only:

- `准备创意方案`
- `刷新创意状态`
- `取消所选创意任务`
- `导出 Creative Package`
- `导出 Creative Deep-AI Handoff` when available

`准备创意方案` may let the user choose one to eight eligible PASS Result Packages from the same project and optionally provide the bounded creative objective. It cannot accept free-form model/system prompt/endpoint/tool/command/path/ComfyUI workflow fields.

The UI must clearly display:

`creative_ready != rendered != publish-ready`

All read-only record bindings must use explicit `Mode=OneWay`; a real STA WPF `Measure/Arrange/UpdateLayout` regression test is required.

## 19. API boundary

Mac Core adds authenticated bounded endpoints under `/api/v1/creative/...` for:

- list eligible PASS Result Packages;
- prepare/create a Creative Job;
- list/get Creative Jobs;
- cancel a nonterminal job;
- read Creative Package metadata;
- download Creative Package;
- read/download manual Creative Deep-AI Handoff.

Create accepts only source Result Package IDs, the closed profile ID and optional bounded creative objective. It does not accept arbitrary prompt/model/endpoint/path/command/tool/workflow fields.

## 20. Idempotency and recovery

A deterministic job source-set digest binds:

- sorted source Result Package IDs/digests;
- project key;
- creative profile;
- normalized creative objective digest;
- stage-template version set.

Same idempotency key + same source-set digest reuses the same Creative Job.

Same idempotency key + different source-set digest conflicts and never overwrites history.

Completed stage identity + same input digest is reused after restart.

Final `Creative Package v1` is immutable; a different package digest under the same package/job identity is a conflict.

## 21. Security/privacy boundary

2.3.19.1 must preserve all 18.1 restrictions and additionally enforce:

- only PASS Result Packages can enter creative generation;
- source packages must belong to the same project;
- no raw Work Package path may be supplied by Windows;
- no producer-selected model/endpoint/system prompt/tool/command/executable;
- no model tools;
- loopback-only model transport;
- no automatic paid AI;
- no ComfyUI execution;
- no arbitrary URLs/download instructions in renderer-neutral Shot Plan fields;
- no raw business data in normal logs/UI;
- no internal prompt/config/secrets in Creative Package or handoff;
- bounded text/list sizes throughout;
- evidence/provenance references fail closed.

## 22. TDD and native verification

Implementation is TDD-first.

Required RED/GREEN coverage includes:

### Core/domain

- Migration 12 tables/indexes and replay;
- only PASS/Completed Result Packages are eligible;
- cross-project source selection rejected;
- source set max 8;
- idempotency reuse/conflict;
- objective bounds and treatment as data;
- exact state transitions;
- immutable package identity.

### Creative stages

- idea ranking schema/ranks/evidence;
- brief references only valid ranked idea/source facts;
- script beat IDs/order/duration/claims;
- shot-plan beat coverage, shot order/duration, allowed `render_intent`;
- unknown finding/evidence IDs rejected/retried;
- schema repair gets at most one retry;
- second repairable failure becomes attention, not a loop;
- semantic uncertainty becomes attention;
- crash recovery reuses persisted valid stage facts.

### Local model security

CI uses a deterministic fake loopback model server. It verifies:

- no real paid model call;
- no tools/functions;
- non-loopback endpoint rejected;
- prompt injection inside source result text cannot redefine system policy;
- output size bounded;
- invalid JSON/unknown references are contained;
- producer objective cannot change model/endpoint/template/tool policy.

### Windows

- eligible Result Package selection;
- same-project restriction reflected in UI/client behavior;
- no arbitrary model/prompt/endpoint/path/command/tool/ComfyUI workflow inputs;
- Creative Package download is bounded and atomic;
- real STA WPF binding/layout smoke;
- existing 18.1 Inbox/Outbox business bridge remains non-regressed.

## 23. Product version, CI and packaging

Product version becomes `2.3.19.1`; database schema becomes 12.

Impact is expected on all three runtime surfaces:

- Mac Core: Migration 12, creative facts/API/package storage;
- Mac Worker: creative stage coordinator and closed creative capability;
- Windows: Creative Intelligence UI/client/actions.

Final delivery therefore requires current exact-head success for:

- Mac Core arm64 CI;
- Mac Worker arm64 CI;
- Windows WPF native CI;
- Windows formal prebuilt release CI.

Final delivery must include:

- precompiled Windows 2.3.19.1 package + SHA-256;
- Mac Core arm64 2.3.19.1 package + SHA-256;
- Mac Worker arm64 2.3.19.1 package + SHA-256;
- combined SHA manifest;
- independent package verification;
- Chinese manual acceptance guide;
- non-sensitive creative fixture/result samples as appropriate.

User machines do not compile source and do not install SDKs.

The implementation PR remains Draft/Open/Unmerged. No `main` merge, tag or GitHub Release is performed.

## 24. Real-machine acceptance

After 18.1 local intelligence is healthy and at least one Result Package is `Completed/PASS`, real-machine acceptance for 19.1 should:

1. install Mac Core → Mac Worker → Windows 2.3.19.1;
2. verify product version and schema 12;
3. rerun the 18.1 safe diagnostic/business path for non-regression;
4. choose one or more eligible PASS Result Packages from one project;
5. create one `creative.content_plan.v1` job;
6. observe stage progression through Idea Ranking → Brief → Script → Shot Plan → QualityCheck;
7. reach `creative_ready`;
8. download/export the exact Creative Package;
9. restart Windows/Core/Worker and confirm the same job/stage/package identities remain and completed stages are not re-run;
10. confirm no ComfyUI job, paid AI call, shell command, Git publication, `main` write, tag or Release occurred.

An optional negative acceptance can force invalid fake/local model structure and verify the two-attempt ceiling plus sanitized manual Creative Deep-AI Handoff.

## 25. Roadmap after 2.3.19.1

### 2.3.20.1 — ComfyUI Production Orchestrator

Consumes only validated `creative_ready` Creative Package / Shot Plan facts:

`creative_ready → renderer-neutral shot plan → Windows local ComfyUI adapter → preview → deterministic media QC → final media`

The production layer chooses audited ComfyUI workflow adapters; the Creative Package never contains arbitrary executable workflow JSON.

### Later

- creative/human revision workflow if real usage proves it necessary;
- richer project memory and past-content performance feedback;
- separately approved paid-AI escalation;
- end-to-end content production and publishing controls.

## 26. Success definition

2.3.19.1 succeeds when validated 18.1 business intelligence can be transformed primarily by the Mac-local `gpt-oss:20b` path into an immutable, evidence-traceable Creative Package containing ranked ideas, a creative brief, a structured script and a renderer-neutral Shot Plan, with bounded retries and safe attention states, without invoking ComfyUI or paid AI.
