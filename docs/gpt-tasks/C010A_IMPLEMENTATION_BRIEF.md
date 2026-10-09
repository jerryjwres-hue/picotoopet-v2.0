# GPT Task — C010A Deterministic QA Implementation Brief

Docs-only. Do not implement code.

Branch:
design/c010a-implementation-brief-v1

Read:
- docs/architecture/video/G006_FINAL_VIDEO_QA_RECEIPT_V1.md
- C009A concrete files on this branch:
  - PostProductionMasterContracts.cs
  - PostProductionMasterArtifactCatalog.cs
  - PostProductionMasterCompositorService.cs
  - PostProductionMasterSourceVerifier.cs
- docs/architecture/video/S005_WINDOWS_AUDIO_MUX_RESULT.md

Goal:
turn G006 into a precise implementation-ready C010A task using actual C009A type names/manifest fields, not hypothetical names.

Must map:
- candidate input: exact C009 MasterVideoArtifact when post-production required; C004 FinalVideoArtifact only when both narration/overlay false
- exact lineage fields available in MasterManifest
- exact managed roots and digest-scoped lookup
- deterministic ffprobe contract
- full ffmpeg decode-to-null contract
- H.264/yuv420p
- width/height/24fps profile mapping
- frame-aware runtime tolerance
- narration_required <-> audio presence
- AAC-LC/48k/mono
- no unexpected streams
- SHA/bytes
- PASS-only immutable Delivery Receipt
- qa_input_digest / receipt_digest
- restart reuse/conflict/tamper
- real Windows test matrix

Also inspect whether C010A should reuse any generic C009B process/media primitive once C009B lands, and state the reuse boundary without guessing a concrete class name.

Do not change C009A/C009B/C004/C007/C008/Goal Center.

Deliver:
docs/architecture/video/C010A_IMPLEMENTATION_BRIEF_V1.md

End with:
READY_TO_IMPLEMENT
DEPENDENCIES
FILES OWNERSHIP
EXACT INPUT CONTRACT
EXACT RECEIPT CONTRACT
TESTS
BLOCKERS
