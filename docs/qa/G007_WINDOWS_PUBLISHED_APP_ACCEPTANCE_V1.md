# G007 Windows Published-App Acceptance v1 — Issue #81

## Authority and scope

Frozen C011 source: ec468b9975a3b1cd706e6e74223bfb05f7733a86. Branch: test/windows-published-app-acceptance-v1. Only G007-owned tests, workflow and documentation may change.

Actual release command: windows/desktop/scripts/Build-Phase2WindowsRelease.ps1 -ValidationScope Full. It uses .NET 10.0.302 and runs the full Release solution build and Phase2 Core smoke before native publish, desktop executable self-test and formal installer packaging. Never substitute Debug, a test runner, synthetic Maotai PNG or UiPreview.

Issue #78 blocks formal release: PHASE2_CORE_SMOKE=FAIL, missing independent torso_neutral.png. The G007 workflow runs the ORIGINAL Full builder from a separate checkout at the frozen commit, and classifies FV-033 BLOCKED only if the actual log contains both markers. Any unexpected release error is a CI failure, not the expected blocker.

IMPORTANT: This G007 workflow is not whitelisted in the official release builder's approved github_workflow_ref set. A diagnostic ZIP produced here (should the resource issue clear) is not a formal approved installer. Do not upload or distribute it as an approved release.

## Machine-readable native Windows evidence

The new workflow checks out G007 test sources and frozen C011 source separately, without merge/rebase. It emits published-app-acceptance.json and native-full-release-builder.log. The JSON binds actual builder evidence by SHA256, includes source SHA, Windows runner session ID, .NET SDK version, actual release outcome, 3 individually classified FV cases and a separate live-Mac-Core state. CI asserts each identity and refuses fabricated GUI/PID or live-Core PASS. Workflow SUCCESS means truthful classification, not completion of all three release cases.

FV-032 = UNVERIFIED until a real installed published WPF GUI produces synchronized physical/UIAutomation concurrent Open events, exactly one launcher invocation, correct receipt and click-time SHA validation. A headless coordinator call does not suffice.

FV-033 = BLOCKED while the formal Maotai Full smoke fails. Once solved, FV-033 stays UNVERIFIED until a genuine approved release archive, fresh Windows profile installation, actual published app launch, full installed resource checks, shortcuts and LOCALAPPDATA isolation are independently evidenced.

FV-034 = UNVERIFIED until real published executable PIDs are captured and forcibly terminated at post-C004/pre-master, committed-master/pre-receipt and post-receipt checkpoints, with distinct new PIDs on restart and verification of immutable Master/Receipt, child process cleanup and safe Open.

Live Mac Core network: UNVERIFIED until a genuine remote authenticated Core connection, fresh Goal/job authority, plan changes, reconnect and failure/recovery are observed. Controlled fake-Core injection is not that evidence.

## Future interactive Windows acceptance runbook

1. Clear Issue #78 by legitimate independent Maotai V2 artwork; leave the original full smoke and publication policy unchanged.
2. Obtain the official Full package from the allowlisted windows-phase2-release.yml workflow; retain the ZIP, SHA256 sidecar, release-manifest, goal integrity stamp, published source SHA and original run ID. Check native_ci_verified, user_install_allowed, full_release, source SHA, release workflow provenance, package hash, contents and signature status.
3. Use a freshly provisioned Windows user account or clean disposable VM, not merely a modified LOCALAPPDATA environment variable. Run packaged Install-Phase2Prebuilt.ps1 and VERIFY_PHASE2_WINDOWS.vbs; prove published executable and resources launch, shortcut names and paths. Record executable hash and PID.
4. Authenticate against a real Mac Core service. Create a genuine production-ready Goal and inspect exact C004, C009, C010A receipt paths and digests. Never insert a fake Core authority for published acceptance.
5. FV-032: capture real visible Goal Center Open clicks (rapid and concurrent), WPF UIAutomation events, only one actual shell invocation, current Goal/job, candidate hash and receipt. If interactive desktop unavailable, UNVERIFIED.
6. FV-034: with separate disposable Goal fixtures, record published executable old PID, force-kill it mid-operation at each of three checkpoints, and restart with a different new PID. Record surviving child processes and orphan temporary files, output Master bytes/SHA, receipt hashes and exact click-time Open result. A simulated cancellation is not a real PID kill.
7. For each FV ID, store an independent oracle, actual inputs and expected/observed results, timestamps, SHA256, Windows/app version, log paths and screenshots. Redact user-specific paths. Only mark PASS after executable observation and independent assertions. Keep BLOCKED or UNVERIFIED for unmet preconditions.

No production/UI changes, unrelated branch writes, merger/rebase, force push, tag or release.
