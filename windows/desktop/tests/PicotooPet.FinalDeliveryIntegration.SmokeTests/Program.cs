using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;
using PicotooPet.FinalVideoQa.SmokeTests;

namespace PicotooPet.FinalDeliveryIntegration.SmokeTests;

internal static class Program
{
    private static async Task<int> Main()
    {
        foreach (var narration in new[] { false, true })
        foreach (var overlay in new[] { false, true })
        {
            await ModeAsync(narration, overlay);
            Console.WriteLine($"C011_MODE_N{(narration ? 1 : 0)}_O{(overlay ? 1 : 0)}=PASS");
        }
        await ReceiptTamperAsync();
        Console.WriteLine("C011_RECEIPT_TAMPER=PASS");
        await ChangedAuthorityAsync();
        Console.WriteLine("C011_CHANGED_PROVENANCE=PASS");
        await RequiredMasterMissingAsync();
        Console.WriteLine("C011_REQUIRED_MASTER_NO_FALLBACK=PASS");
        await MissingQaGateAsync();
        Console.WriteLine("C011_MISSING_QA_GATE=PASS");
        await FullDecodeFailureAsync();
        Console.WriteLine("C011_FULL_DECODE_REJECTION=PASS");
        await RestartAsync();
        Console.WriteLine("C011_DURABLE_RESTART=PASS");
        await TransientPostproductionRecoveryAsync();
        Console.WriteLine("C011_TRANSIENT_POSTPRODUCTION_RETRY=PASS");
        await GuiOnlyReadsPersistedQaAsync();
        Console.WriteLine("P0_GUI_ONLY_READS_PERSISTED_QA=PASS");
        await GuiRevokedProjectionCannotOpenAsync();
        Console.WriteLine("P0_GUI_REVOKED_QA_INDEX=PASS");
        await ConcurrentOpenAsync();
        Console.WriteLine("C011_SINGLE_ASYNC_OPEN=PASS");
        await JobSwitchAsync();
        Console.WriteLine("C011_JOB_SWITCH=PASS");
        await DisposeCancellationAsync();
        Console.WriteLine("C011_CANCEL_DISPOSE=PASS");
        Console.WriteLine("FINAL_VIDEO_QA_GATED_INTEGRATION=PASS");
        return 0;
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("C011_ASSERT_" + message);
    }

    private sealed class Assembler(FinalVideoArtifact artifact) : IFinalVideoAssembler
    {
        public Task<FinalVideoArtifact> AssembleAsync(string jobId, CancellationToken ct = default)
        {
            ct.ThrowIfCancellationRequested();
            Check(jobId == artifact.ProductionJobId, "WRONG_JOB_ASSEMBLER");
            return Task.FromResult(artifact);
        }
    }

    private sealed class Launcher : IFinalVideoLauncher
    {
        public int Opens;
        public string? LastPath;
        public void Open(string path)
        {
            Interlocked.Increment(ref Opens);
            LastPath = path;
        }
    }

    private static PostProductionDeliveryCoordinator Coordinator(
        Fixture fixture,
        Launcher launcher,
        bool narration, bool overlay,
        Func<string, string, CancellationToken, Task<C011QaDeliveryAuthority>>? authorityOverride = null,
        Func<FinalVideoQaInputV1, CancellationToken, Task<FinalVideoQaResult>>? qaOverride = null,
        bool includeGate = true,
        bool throwOnCompose = false,
        bool returnMissingMaster = false,
        bool decodeFailure = false,
        VerifiedGoalDeliveryProjectionStore? projection = null,
        bool backgroundProduction = true,
        Func<bool>? transientComposeFailure = null,
        Func<DateTimeOffset>? utcNow = null,
        TimeSpan? retryDelay = null)
    {
        var source = fixture.Input;
        var baseline = LifecycleTests.Input(fixture, null);
        var authority = new C011QaDeliveryAuthority(
            baseline.GoalContinuation, baseline.ProductionJob,
            baseline.ProductionPlan, baseline.ProductionPackage);
        var verifier = new GoalDeliveryCandidateVerifier(
            Path.Combine(fixture.Root, "finals"), fixture.MasterRoot);
        var qa = LifecycleTests.Service(fixture, new QaRunner(narration) { DecodeFailure = decodeFailure });
        return new PostProductionDeliveryCoordinator(
            new Assembler(source.C004),
            (job, ct) => Task.FromResult(source.NarrationPlan),
            (job, ct) => Task.FromResult(source.OverlayPlan),
            (plan, ct) => Task.FromResult(source.NarrationArtifact
                ?? throw new InvalidDataException("C011_MISSING_NARRATION")),
            (c004, plan, ct) => Task.FromResult(source.OverlayArtifact
                ?? throw new InvalidDataException("C011_MISSING_OVERLAY")),
            async (input, ct) =>
            {
                // ── A controllable I/O outage models missing ffmpeg / temporarily missing media roots. ──
                if (throwOnCompose || transientComposeFailure?.Invoke() == true)
                    throw new IOException("synthetic composer rejection");
                var result = await fixture.Service.ComposeAsync(input, ct).ConfigureAwait(false);
                return returnMissingMaster ? new MasterCompositionResult(true, null, null) : result;
            },
            verifier, launcher,
            includeGate ? authorityOverride ?? ((goal, job, ct) =>
                Task.FromResult(authority)) : null,
            includeGate ? qaOverride ?? qa.VerifyAsync : null,
            durableProjection: projection, backgroundProduction: backgroundProduction,
            utcNow: utcNow, retryDelay: retryDelay);
    }

    private static async Task<GoalDeliverySnapshot> WaitAsync(
        PostProductionDeliveryCoordinator coordinator,
        GoalVideoContinuationRecord continuation,
        GoalDeliveryPhase expected)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        while (!timeout.IsCancellationRequested)
        {
            var state = coordinator.Observe(continuation.GoalId, continuation);
            if (state.Phase == expected) return state;
            if (state.Phase is GoalDeliveryPhase.Failed or GoalDeliveryPhase.QaFailed
                && expected is not (GoalDeliveryPhase.Failed or GoalDeliveryPhase.QaFailed))
            {
                throw new InvalidOperationException("C011_UNEXPECTED_" + state.Phase);
            }
            await Task.Delay(25);
        }
        throw new TimeoutException("C011_WAIT_" + expected);
    }

    private static async Task ModeAsync(bool narration, bool overlay)
    {
        using var f = await Fixture.CreateAsync(narration, overlay);
        var input = LifecycleTests.Input(f, null);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, narration, overlay);
        var ready = await WaitAsync(c, input.GoalContinuation, GoalDeliveryPhase.DeliveryReady);
        Check(ready.CanOpen, "RECEIPT_ONLY_OPEN");
        Check(await c.OpenCurrentAsync(), "APPROVED_OPEN");
        Check(launcher.Opens == 1, "ONE_OPEN");
        var expectedMaster = narration || overlay;
        Check(launcher.LastPath!.Contains(expectedMaster ? "master.mp4" : "final-", StringComparison.Ordinal),
            "STRICT_CANDIDATE");
        await File.AppendAllTextAsync(launcher.LastPath!, "tampered-after-qa");
        Check(!await c.OpenCurrentAsync(), "CLICK_TIME_SHA");
        Check(launcher.Opens == 1, "TAMPER_NO_LAUNCH");
        Check(!c.CurrentSnapshot.CanOpen, "TAMPER_FAIL_CLOSED");
    }

    private static async Task ReceiptTamperAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var launcher = new Launcher();
        var input = LifecycleTests.Input(f, null);
        await using var c = Coordinator(f, launcher, false, false);
        await WaitAsync(c, input.GoalContinuation, GoalDeliveryPhase.DeliveryReady);
        var qa = LifecycleTests.Service(f, new NeverRunner());
        var result = await qa.VerifyAsync(input);
        await File.AppendAllTextAsync(result.ReceiptPath, "tampered");
        Check(!await c.OpenCurrentAsync(), "RECEIPT_TAMPER_MUST_REJECT");
        Check(launcher.Opens == 0, "RECEIPT_TAMPER_NO_LAUNCH");
    }

    private static async Task ChangedAuthorityAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var original = LifecycleTests.Input(f, null);
        var altered = false;
        var auth = new C011QaDeliveryAuthority(original.GoalContinuation, original.ProductionJob,
            original.ProductionPlan, original.ProductionPackage);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, false, false,
            (goal, job, ct) => Task.FromResult(altered
                ? auth with { Goal = auth.Goal with { ReturnSha256 = Fixture.ShaValue("different-return") } }
                : auth));
        await WaitAsync(c, original.GoalContinuation, GoalDeliveryPhase.DeliveryReady);
        altered = true;
        Check(!await c.OpenCurrentAsync(), "STALE_CORE_AUTHORITY");
        Check(launcher.Opens == 0, "STALE_AUTHORITY_NO_LAUNCH");
    }

    private static async Task RequiredMasterMissingAsync()
    {
        using var f = await Fixture.CreateAsync(true, false);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, true, false, returnMissingMaster: true);
        var input = LifecycleTests.Input(f, null);
        await WaitAsync(c, input.GoalContinuation, GoalDeliveryPhase.Failed);
        Check(!c.CurrentSnapshot.CanOpen && !await c.OpenCurrentAsync(), "REQUIRED_MASTER_FAIL_CLOSED");
        Check(launcher.Opens == 0, "NO_C004_ESCAPE");
    }

    private static async Task MissingQaGateAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, false, false, includeGate: false);
        var input = LifecycleTests.Input(f, null);
        await WaitAsync(c, input.GoalContinuation, GoalDeliveryPhase.Failed);
        Check(!c.CurrentSnapshot.CanOpen && launcher.Opens == 0, "QA_MISSING_NO_FALLBACK");
    }

    private static async Task FullDecodeFailureAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, false, false, decodeFailure: true);
        var input = LifecycleTests.Input(f, null);
        await WaitAsync(c, input.GoalContinuation, GoalDeliveryPhase.QaFailed);
        Check(!c.CurrentSnapshot.CanOpen && launcher.Opens == 0, "DECODE_NO_APPROVAL");
    }

    private static async Task RestartAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var continuation = LifecycleTests.Input(f, null).GoalContinuation;
        var launcher = new Launcher();
        await using (var original = Coordinator(f, launcher, false, false))
        {
            await WaitAsync(original, continuation, GoalDeliveryPhase.DeliveryReady);
        }
        await using (var restored = Coordinator(f, launcher, false, false))
        {
            Check(restored.CurrentSnapshot.Phase == GoalDeliveryPhase.Idle, "RESTART_EMPTY_MEMORY");
            await WaitAsync(restored, continuation, GoalDeliveryPhase.DeliveryReady);
            Check(await restored.OpenCurrentAsync(), "RESTART_VERIFIED_RECEIPT");
            Check(launcher.Opens == 1, "RESTART_ONE_LAUNCH");
        }
    }


    private static async Task TransientPostproductionRecoveryAsync()
    {
        using var fixture = await Fixture.CreateAsync(false, false);
        var continuation = LifecycleTests.Input(fixture, null).GoalContinuation;
        var launcher = new Launcher();
        var now = new DateTimeOffset(2026, 10, 29, 0, 0, 0, TimeSpan.Zero);
        var unavailable = true;
        await using var coordinator = Coordinator(fixture, launcher, false, false,
            transientComposeFailure: () => unavailable, utcNow: () => now,
            retryDelay: TimeSpan.FromMinutes(2));

        // ── A source-backed transient outage can fail before C011 receipt exists. ──
        await WaitAsync(coordinator, continuation, GoalDeliveryPhase.Failed);
        Check(!coordinator.CurrentSnapshot.CanOpen && launcher.Opens == 0,
            "TRANSIENT_FAILURE_NO_UNVERIFIED_OPEN");
        await Task.Delay(100);
        unavailable = false;
        Check(coordinator.Observe(continuation.GoalId, continuation).Phase == GoalDeliveryPhase.Failed,
            "TRANSIENT_COOLDOWN_NO_IMMEDIATE_RETRY");

        // ── A later read-only observation reuses frozen sources after cooldown, no GPU path. ──
        now = now.AddMinutes(3);
        await WaitAsync(coordinator, continuation, GoalDeliveryPhase.DeliveryReady);
        Check(coordinator.CurrentSnapshot.CanOpen, "TRANSIENT_RETRY_REQUIRES_QA");
        Check(await coordinator.OpenCurrentAsync(), "TRANSIENT_RETRY_VERIFIED_OPEN");
        Check(launcher.Opens == 1, "TRANSIENT_RETRY_ONE_OPEN");
    }

    private static async Task GuiOnlyReadsPersistedQaAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var baseline = LifecycleTests.Input(f, null);
        var original = baseline.GoalContinuation;
        var launcher = new Launcher();
        var store = new VerifiedGoalDeliveryProjectionStore(
            Path.Combine(f.Root, "p0-durable-delivery"));
        // ── Both processes must observe identical durable Core authority, not fixture timestamps. ──
        var canonical = new C011QaDeliveryAuthority(
            baseline.GoalContinuation, baseline.ProductionJob,
            baseline.ProductionPlan, baseline.ProductionPackage);
        Task<C011QaDeliveryAuthority> SameCore(
            string goal, string job, CancellationToken ct) => Task.FromResult(canonical);

        // ── Only the headless producer assembles C004 and commits an actual C010 QA receipt. ──
        await using (var background = Coordinator(
            f, launcher, false, false, authorityOverride: SameCore,
            projection: store, backgroundProduction: true))
        {
            await WaitAsync(background, original, GoalDeliveryPhase.DeliveryReady);
        }
        var persisted = await store.ReadAsync(original.GoalId, original.ProductionJobId!, CancellationToken.None);
        Check(persisted is not null, "WORKER_DID_NOT_PERSIST_QA");

        // ── WPF restore is read-only; a forbidden composer would throw immediately. ──
        await using (var gui = Coordinator(
            f, launcher, false, false, authorityOverride: SameCore,
            throwOnCompose: true, projection: store, backgroundProduction: false))
        {
            Check(gui.CurrentSnapshot.Phase == GoalDeliveryPhase.Idle, "GUI_INITIAL_IDLE");
            await WaitAsync(gui, original, GoalDeliveryPhase.DeliveryReady);
            Check(await gui.OpenCurrentAsync(), "GUI_QA_RECEIPT_OPEN");
            Check(launcher.Opens == 1, "GUI_SINGLE_OPEN");

            // ── Open must rehash bytes, even when the GUI snapshot was previously Ready. ──
            await File.AppendAllTextAsync(persisted!.Candidate.FilePath, "tampered");
            Check(!await gui.OpenCurrentAsync(), "GUI_TAMPERED_VIDEO_REFUSED");
            Check(launcher.Opens == 1, "GUI_TAMPER_DOES_NOT_LAUNCH");
        }
    }

    private static async Task GuiRevokedProjectionCannotOpenAsync()
    {
        using var fixture = await Fixture.CreateAsync(false, false);
        var baseline = LifecycleTests.Input(fixture, null);
        var continuation = baseline.GoalContinuation;
        var root = Path.Combine(fixture.Root, "p0-revocable-qa");
        var store = new VerifiedGoalDeliveryProjectionStore(root);
        var authority = new C011QaDeliveryAuthority(
            baseline.GoalContinuation, baseline.ProductionJob,
            baseline.ProductionPlan, baseline.ProductionPackage);
        var launcher = new Launcher();

        // ── Only the worker writes a real PASS receipt and immutable projection. ────
        Task<C011QaDeliveryAuthority> SameCore(
            string goal, string job, CancellationToken ct) => Task.FromResult(authority);
        await using (var worker = Coordinator(
            fixture, launcher, false, false, authorityOverride: SameCore,
            projection: store, backgroundProduction: true))
        {
            await WaitAsync(worker, continuation, GoalDeliveryPhase.DeliveryReady);
        }

        // ── GUI restores a valid snapshot, but Open must not trust stale memory. ─
        await using (var gui = Coordinator(
            fixture, launcher, false, false, authorityOverride: SameCore,
            throwOnCompose: true, projection: store, backgroundProduction: false))
        {
            await WaitAsync(gui, continuation, GoalDeliveryPhase.DeliveryReady);
            var indexFiles = Directory.GetFiles(root, "*.json", SearchOption.TopDirectoryOnly);
            Check(indexFiles.Length == 1, "GUI_REVOKED_INDEX_FIXTURE");
            File.Delete(indexFiles[0]);

            Check(!await gui.OpenCurrentAsync(), "GUI_REVOKED_INDEX_REFUSED");
            Check(launcher.Opens == 0, "GUI_REVOKED_INDEX_NO_SHELL");
            Check(!gui.CurrentSnapshot.CanOpen, "GUI_REVOKED_INDEX_CLOSED");
        }
    }

    private static async Task ConcurrentOpenAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var input = LifecycleTests.Input(f, null);
        var auth = new C011QaDeliveryAuthority(input.GoalContinuation, input.ProductionJob,
            input.ProductionPlan, input.ProductionPackage);
        var calls = 0;
        var gate = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        async Task<C011QaDeliveryAuthority> BlockOnOpen(string goal, string job, CancellationToken ct)
        {
            if (Interlocked.Increment(ref calls) > 1) await gate.Task.WaitAsync(ct);
            return auth;
        }
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, false, false, authorityOverride: BlockOnOpen);
        await WaitAsync(c, input.GoalContinuation, GoalDeliveryPhase.DeliveryReady);
        var first = c.OpenCurrentAsync();
        Check(!first.IsCompleted, "OPEN_NON_BLOCKING");
        Check(!await c.OpenCurrentAsync(), "SECOND_CLICK_REFUSED");
        gate.SetResult(true);
        Check(await first, "FIRST_OPEN_AFTER_GATE");
        Check(launcher.Opens == 1, "ONLY_ONE_SHELL_CALL");
    }

    private static async Task JobSwitchAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var input = LifecycleTests.Input(f, null);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, false, false);
        await WaitAsync(c, input.GoalContinuation, GoalDeliveryPhase.DeliveryReady);
        var switched = input.GoalContinuation with
        {
            GoalId = "new-goal", ProductionJobId = "new-job"
        };
        var snapshot = c.Observe("new-goal", switched);
        Check(!snapshot.CanOpen, "NEW_JOB_MUST_RESET");
        Check(!await c.OpenCurrentAsync(), "OLD_RECEIPT_CANNOT_OPEN_NEW_JOB");
        Check(launcher.Opens == 0, "SWITCH_NO_LAUNCH");
    }

    private static async Task DisposeCancellationAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var input = LifecycleTests.Input(f, null);
        var launcher = new Launcher();
        var gate = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var entered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        async Task<C011QaDeliveryAuthority> SlowAuthority(string goal, string job, CancellationToken ct)
        {
            entered.TrySetResult(true);
            await gate.Task.WaitAsync(ct);
            throw new InvalidOperationException("cancelled authority cannot finish");
        }
        var c = Coordinator(f, launcher, false, false, authorityOverride: SlowAuthority);
        c.Observe(input.GoalContinuation.GoalId, input.GoalContinuation);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await c.DisposeAsync();
        Check(c.CurrentSnapshot.Phase != GoalDeliveryPhase.Failed, "CANCELLATION_NOT_FAILURE");
        Check(launcher.Opens == 0, "NO_CANCELLED_LAUNCH");
    }
}
