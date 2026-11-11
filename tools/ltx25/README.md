# PicotooPet | LTX-2.5 Ingredients continuity pilot (isolated)

This is a **research-only** controller. It does **not** replace Mac Core, Windows Worker, production permissions or frozen Creative Package.

## Scope and source of truth

- Windows PowerShell 5.1 + FFmpeg + existing user-paired LTX Desktop 1.3.1 Remote on `http://127.0.0.1:41955`.
- Existing real Maotai image `IMG_3576.jpeg` has SHA256 `cafe5cfec5e859f416d576809417e4de68f7a3178ee9a532da5f2272c5f9f694`.
- Generated `S02.mp4` and `S05.mp4` from user pilot are **fictional** imagery, not owner-photographed rooms or bowls. They must **not** be represented as factual location/prop evidence. Only S02 is selected as the experimental canonical bowl; S05 is deliberately excluded to avoid mixing two bowl identities.
- Sources: [Director Agent](https://github.com/62656456/ai-film-skills/blob/main/skills/director-agent/SKILL.md), [AI Storyboard Director](https://github.com/62656456/ai-film-skills/blob/main/skills/ai-storyboard-director/SKILL.md), [Cinematography](https://github.com/fal-ai-community/skills/blob/main/skills/cinematography/SKILL.md), [LTX official Ingredients IC-LoRA integration](https://docs.ltx.io/open-source-model/integration-tools/ic-lo-ra-adapters/), [LTX Desktop 1.3.1 API](https://github.com/Lightricks/LTX-Desktop/tree/v1.3.1/backend/remote).
- The public Skill files are **source rules/checklists**, not model agents run by this script. The exported contract applies their film-planning principles deterministically. The only inference performed after explicit opt-in is a single official LTX Ingredients generation.

## Modes and side effects

| Mode | Effect |
| --- | --- |
| `-Mode Prepare` | **No GPU**. Verify real image SHA; extract S02/S05 JPG candidates; produce visual comparison board, shot contract and Skills provenance. Open reference folder. |
| `-Mode Probe` | **No GPU**. Same prep plus paired loopback API GET `/api/ic-loras` and `/api/generation-queue`; distinguish Ingredients LoRA **LTX-2.5 variant installed** from merely present in catalog. |
| `-Mode Pilot` | Only after explicit operator command, if `ltx-2.5__ingredients` is installed, text encoder and video mode are local and queue empty, upload two reference images and make **at most one** `POST /api/generations/ic-lora-recipes/ingredients`; write receipt. Unknown result blocks repeats. Generates **one 540p/5s** A-B-C consistency proof shot, **not** the final 48-second film. |
| `-Mode Status` | **No GPU**. Read known generation by ID, export successful MP4 with verified signed loopback asset URL, print SHA256. |

### Paths

- Primary script: `D:\opc in D\LTX\脚本\PicotooPet-Continuity.ps1` (install by downloading a pinned GitHub commit).
- Project: `D:\opc in D\LTX\电影项目\茅台晚餐_连续性V2\05_Ingredients连续性实验`.
- Existing six original shots and rough cut remain in `D:\AI\LTX25\films\Maotai_Dinner_48s` (read only).
- Only two extracted JPEGs + a comparison JPG, JSON manifest/contract, and optionally one generated MP4 are added. Nothing moves/copies huge models.

### Stop and safety

- Stop if missing source SHA, LTX DPAPI session, downloaded exact 2.5 adapter, empty GPU queue, local encode setting or if any previous generation receipt/uncertain marker exists.
- `Pilot` does not run from `Prepare` or `Probe`.
- The experiment keeps formal GPU HOLD as-is. It does not approve Maotai Creative v2 keyframes or change production authorization.
- Imported ComfyUI JSON is not used to execute; Desktop has its own Ingredients recipe API. This avoids cloning 40GB checkpoints into a second Comfy environment for a first pilot.
- A short consistent clip is only an exploratory candidate: human visual QC and narrative acceptance remain required.

### Acceptance after first experimental shot

Review **same biological Maotai** (nose, eyebrow patterns, coat, ears), **same selected synthetic bowl** (material, shape, size), **same room geometry**, **cause-before-response audio**, **one coherent eyeline**, no extra paws/ghost faces, and no duplicate dish. If any fails, do not scale to additional shots or call the 48s film publishable.

The present 48s original remains technically generated/assembled **PASS**, while cross-shot story continuity and release remain **FAIL / NOT ACCEPTED**.
