# G005 Final Video 36-Scenario — Pinned C011 Windows Acceptance v2

Repository: jerryjwres-hue/picotoopet-v2.0
Branch / Draft PR: test/final-video-e2e-acceptance-v1 / #68
Controlling authority: Issue #77 comment 6180755650.
Pinned C011 SHA: ec468b9975a3b1cd706e6e74223bfb05f7733a86
Pinned C011 test: windows/desktop/tests/PicotooPet.FinalDeliveryIntegration.SmokeTests/PicotooPet.FinalDeliveryIntegration.SmokeTests.csproj
Existing Windows C011 SUCCESS: 38651165244.

## Historical baseline vs independent G005 result

Before C011, the original run 38648246757 reported
PASS=1 FAIL=0 BLOCKED=32 UNVERIFIED=3, with qa_gated_e2e_pass=0.

G005 now provides a **separate C# test method for each of 30 automatable FV cases**, each with its
own real service/coordinator assertion and a case-specific marker. In the third actual Windows
G005 test run 38657259327, its C# program completed with 30 PASS, 0 FAIL,
3 BLOCKED, 3 UNVERIFIED, and 28 C011-controlled-Core scenario PASS.
That workflow as a whole was not green because the old wrapping script treated intentional
UNVERIFIED outcomes as suite errors; a G005-only policy correction was then committed.

The suite is not represented as 36/36 fully deployed E2E and its final GitHub Actions SUCCESS
must be confirmed separately. No manual GUI, live Mac Core network, actual installed Windows
application, or adversarial PID crash was executed by the G005 suite.

## Per-scenario implementation evidence

The C# runner lives in:
windows/desktop/tests/PicotooPet.G005.FinalVideoE2E.SmokeTests/Program.cs

Actions invokes C009A, C009B, C011 frozen assemblies and then the G005 independent project.
The C011 checkout is pinned by full SHA; G005 test code is copied **only** into its disposable
checkout. G005 project compile-links the genuine C010A Fixture.cs and LifecycleTests.cs from
that exact checkout and calls actual PostProductionDeliveryCoordinator, C010A VerifyAsync,
FinalArtifactReceiptStore, GoalDeliveryCandidateVerifier, and FFmpeg/ffprobe. No QA
contract/catalog/receipt implementation is duplicated.

The independent G005 evidence contains:
- final-video-e2e-results/G005.log: 36 distinct FV-### outcomes plus assertions count.
- final-video-e2e-results/g005-independent-36.json: id, status, scope, oracle,
  assertion count, blocker and error per ID.
- final-video-e2e-results/final-video-e2e-results.json: 36-case conservation and
  production SHA provenance.
- C009A.log, C009B.log and C011.log: real upstream native Windows gate markers.

FV-001..FV-011, FV-013..FV-030 and FV-036 execute independently (30 distinct PASS cases).
FV-006 is unsupported **true caption** rejection; FV-004/FV-005 use text overlay and
must never silently substitute it for true captions. FV-029 uses actual corrupted media
and native full decode. FV-030 uses all three C005 size profiles and QA receipt/open,
with real FFmpeg. Other C011 tests use a controlled Core authority; results are labeled
C011_QA_CONTROLLED_CORE, **not live Mac Core network E2E**.

Independent supplemental assertions separately exercise concurrent double Open refusal
and stale Goal/job switch via the actual C011 coordinator, but do **not** upgrade
published GUI FV-032 from UNVERIFIED. These emit:
G005_CONTROLLED_CORE_CONCURRENT_SINGLE_OPEN=PASS
G005_CONTROLLED_CORE_STALE_GOAL_JOB_SWITCH=PASS

## Remaining 6 of 36 without full PASS

| ID | State | Reason |
| --- | --- | --- |
| FV-012 | BLOCKED | True PID crash during C009A's mid-commit partial/master manifest boundary not executed; merely deleting a temp fixture is not a replacement. |
| FV-031 | BLOCKED | Full adversarial AAC silent-interval alignment with malformed media not independently verified; codec policy alone insufficient. |
| FV-035 | BLOCKED | True native missing FFmpeg/ffprobe binary or invalid PATH lifecycle not isolated/tested; synthetic injected process failures would not prove it. |
| FV-032 | UNVERIFIED | Installed/published GUI Open surface with concurrent user interactions, though coordinator-only concurrency is separately asserted. |
| FV-033 | UNVERIFIED | Actual published Windows executable launch in fresh LOCALAPPDATA and GUI automation absent. |
| FV-034 | UNVERIFIED | External force-kill/new PID process restart, recovery and orphan-process check not executed. |

**Additionally**, live Mac Core network connectivity and authority lifecycle remain
UNVERIFIED across all controlled-Core scenarios; passing local Windows integration
is not evidence of real HTTP/backend availability.

## Release gate

Do not release until the six above are resolved under their real environment,
and the live Mac Core network, published Windows GUI and process restart boundaries
are demonstrated. Workflow success means the submitted executable assertions and the
truthful six non-PASS classifications were accepted; it does not mean full release signoff.

No merge/rebase/force-push/tag/release. Production files and other owners' branches untouched.
