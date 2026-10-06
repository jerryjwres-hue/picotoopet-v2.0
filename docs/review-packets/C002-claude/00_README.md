# C002 Claude Review Packet

Purpose: token-efficient, read-only review packet for Claude.

Branch: `feature/goal-video-return-intake-ui`

## Rules

- These files are REVIEW SNAPSHOTS only.
- Source of truth remains the original repository paths listed below.
- Do not implement or edit these snapshot copies.
- Do not redesign existing architecture.
- Mac Core remains source of truth.
- Do not duplicate Creative or Production.
- Research Gateway remains read-only.
- Never bypass security, release, or asset gates.
- Focus only on actionable C002 defects and missing tests.
- Minimize token use.

## Review target

C002 closes the remaining manual flow:

Goal Center -> handoff ZIP + bound prompt -> manual Web GPT -> user copies return ->
Windows paste/submit -> existing Mac Core C001 validation -> existing Creative adoption ->
existing Production job -> Windows continuation status.

## Source mapping

- `01_TASK_SPEC.md` <- `docs/superpowers/plans/2026-10-06-goal-video-return-intake-ui.md`
- `02_GoalCenterContracts.cs` <- `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/GoalCenterContracts.cs`
- `03_MacCoreClient.cs` <- `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs`
- `04_ControlCenterSession.Goals.cs` <- `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Goals.cs`
- `05_OperatorHomePageViewModel.cs` <- `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorHomePageViewModel.cs`
- `06_GoalCenterPanel.xaml` <- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/GoalCenterPanel.xaml`
- `07_GoalCenterPanel.xaml.cs` <- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/GoalCenterPanel.xaml.cs`
- `08_autonomous_goals.py` <- `src/picotoopet_core/api/routes/autonomous_goals.py`
- `09_video_return.py` <- `src/picotoopet_core/autonomous/video_return.py`
- `10_video_continuation.py` <- `src/picotoopet_core/autonomous/video_continuation.py`

## Claude task

Perform a read-only review of this packet.

Check:
- architecture boundaries
- security / authority leakage
- parser boundary
- payload preservation
- replay / idempotency behavior
- error handling
- Windows status projection
- missing tests

Do not implement. Do not summarize unchanged code.

Return only:

```text
VERDICT: PASS | FAIL
BLOCKERS:
IMPORTANT:
TEST GAPS:
```


## R002 current-code review

The earlier numbered snapshots 02-07 were captured before C002 implementation and are stale.
For R002, DO NOT use 02-07 to decide whether C002 exists.

Review only:
- 01_TASK_SPEC.md
- 08_autonomous_goals.py
- 09_video_return.py
- 10_video_continuation.py
- 11_C002_IMPLEMENTATION.diff

The implementation diff is from commit:
b8210df7ce8fb4d05ae5c1f87bfd709669b01d68

R002 goal:
- verify the actual C002 Windows implementation against the task spec and existing C001 backend
- distinguish pre-existing C001 backend hardening findings from C002 regressions
- report only actionable blockers / important findings / test gaps
