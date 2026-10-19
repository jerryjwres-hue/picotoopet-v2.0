using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.PostProductionDelivery.SmokeTests;

/// <summary>Only synthetic, managed files. No FFmpeg, C010, network or real Goal database.</summary>
internal static class CoordinatorIntegrationTests
{
    private const string Digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    public static async Task RunAsync()
    {
        foreach (var narration in new[] { false, true })
        {
            foreach (var overlays in new[] { false, true })
            {
                using var fixture = new Fixture();
                await fixture.ModeAsync(narration, overlays).ConfigureAwait(false);
            }
        }

        using (var fixture = new Fixture())
        {
            await fixture.RequiredFailureNeverFallsBackAsync().ConfigureAwait(false);
        }
        using (var fixture = new Fixture())
        {
            await fixture.RestartFromDurableFilesAsync().ConfigureAwait(false);
        }
        using (var fixture = new Fixture())
        {
            await fixture.SwitchAndCancellationAsync().ConfigureAwait(false);
        }
        using (var fixture = new Fixture())
        {
            await fixture.DisposeDuringReconciliationAsync().ConfigureAwait(false);
        }
        using (var fixture = new Fixture())
        {
            await fixture.NoQaAuthorityFailsClosedAsync().ConfigureAwait(false);
        }
        using (var fixture = new Fixture())
        {
            await fixture.UnapprovedReceiptNeverReadyAsync().ConfigureAwait(false);
        }
        using (var fixture = new Fixture())
        {
            await fixture.OpenRejectsChangedAuthorityOrReceiptAsync().ConfigureAwait(false);
        }
        Console.WriteLine("POSTPRODUCTION_DELIVERY_COORDINATOR_INTEGRATION=PASS");
    }

    private static void Check(bool condition, string reason)
    {
        if (!condition) throw new InvalidOperationException("C009C_INTEGRATION: " + reason);
    }

    private static string Sha(string text) => Sha(Encoding.UTF8.GetBytes(text));
    private static string Sha(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private static GoalVideoContinuationRecord Continuation(string goal, string job) =>
        new(goal, Digest, Digest, "creative-job", "creative", Digest,
            "Ready", job, "production_ready");

    private static NarrationPlanResponseRecord NarrationPlan(string job, bool required)
    {
        var segments = required
            ? new[] { new NarrationSegmentPlanRecord(
                "segment-1", "beat-1", 1, "spoken text", Sha("spoken text"), 0, 1000) }
            : [];
        var plan = new NarrationPlanRecord(
            "1.0", job, "creative", Digest, Digest, 2000,
            NarrationPlanContract.TtsProfileId, NarrationPlanContract.VoiceProfileId,
            required, segments);
        return new NarrationPlanResponseRecord(plan, NarrationPlanContract.ComputeDigest(plan));
    }

    private static CaptionOverlayPlanResponseRecord OverlayPlan(string job, bool required)
    {
        var cues = required
            ? new[] { new CaptionOverlayCueRecord(
                "overlay-1", "beat-1", 1, "overlay", "overlay text", Sha("overlay text"), 0, 1000) }
            : [];
        var plan = new CaptionOverlayPlanRecord(
            "1.0", job, "creative", Digest, Digest, 2000, "video.square.v1",
            CaptionOverlayConstants.CaptionStyleProfileId, CaptionOverlayConstants.OverlayStyleProfileId,
            CaptionOverlayConstants.FontProfileId, false, required, [], cues);
        // The coordinator validates this bounded C008B response as C009A does.
        return new CaptionOverlayPlanResponseRecord(plan, Digest);
    }

    private sealed class FakeAssembler : IFinalVideoAssembler
    {
        private readonly Func<string, CancellationToken, Task<FinalVideoArtifact>> _callback;
        public int Calls;
        public FakeAssembler(Func<string, CancellationToken, Task<FinalVideoArtifact>> callback) =>
            _callback = callback;
        public Task<FinalVideoArtifact> AssembleAsync(string job, CancellationToken ct = default)
        {
            Interlocked.Increment(ref Calls);
            return _callback(job, ct);
        }
    }

    private sealed class FakeLauncher : IFinalVideoLauncher
    {
        public int Opens;
        public string? LastPath;
        public void Open(string path)
        {
            Interlocked.Increment(ref Opens);
            LastPath = path;
        }
    }

    private sealed class Fixture : IDisposable
    {
        private readonly string _root = Path.Combine(Path.GetTempPath(), "c009c-integration-" + Guid.NewGuid().ToString("N"));
        private readonly string _finalRoot;
        private readonly string _masterRoot;
        private readonly GoalDeliveryCandidateVerifier _verifier;
        private readonly FakeLauncher _launcher = new();
        private bool _failMaster;
        private bool _delayFirstAssembler;
        private readonly TaskCompletionSource<bool> _releaseFirst = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _assembleCallCount;
        private int _composeCalls;
        private int _qaCalls;
        private bool _qaWired = true;
        private bool _qaDeny;
        private bool _swapReceiptAtOpen;
        private bool _authorityDrift;
        private readonly Dictionary<string, C011QaDeliveryAuthority> _authorities = new(StringComparer.Ordinal);
        private readonly string _receiptRoot;

        public Fixture()
        {
            _finalRoot = Path.Combine(_root, "FinalVideos");
            _masterRoot = Path.Combine(_root, "Master", "v1");
            Directory.CreateDirectory(_finalRoot);
            Directory.CreateDirectory(_masterRoot);
            _receiptRoot = Path.Combine(_root, "receipts");
            Directory.CreateDirectory(_receiptRoot);
            _verifier = new GoalDeliveryCandidateVerifier(_finalRoot, _masterRoot);
        }

        public async Task ModeAsync(bool narrationRequired, bool overlaysRequired)
        {
            const string job = "mode-job";
            await using var coordinator = NewCoordinator(narrationRequired, overlaysRequired);
            var goal = "mode-goal";
            var continuation = Continuation(goal, job);
            for (var i = 0; i < 20; i++)
            {
                coordinator.Observe(goal, continuation);
            }
            // C011: a C004 fallback / C009 master is never final authority; only a QA-approved
            // candidate reaches DeliveryReady, and Open requires the exact receipt below.
            await AwaitPhaseAsync(coordinator, goal, continuation, GoalDeliveryPhase.DeliveryReady)
                .ConfigureAwait(false);
            Check(coordinator.CurrentSnapshot.CanOpen, "QA-approved candidate must be openable");
            Check(_qaCalls >= 1, "QA verifier must have run before Ready");
            Check(await coordinator.OpenCurrentAsync().ConfigureAwait(false), "candidate must open");
            Check(_launcher.Opens == 1, "exactly one launcher invocation");
            Check(_composeCalls == 1, "observe must be single-flight");
            Check(_launcher.LastPath!.StartsWith(
                narrationRequired || overlaysRequired ? _masterRoot : _finalRoot,
                StringComparison.OrdinalIgnoreCase), "selected managed artifact root");

            // Changing the bytes *after* Ready must forbid Open, with no fallback.
            await File.AppendAllTextAsync(_launcher.LastPath!, "tamper").ConfigureAwait(false);
            Check(!await coordinator.OpenCurrentAsync().ConfigureAwait(false), "click-time tamper rejected");
            Check(_launcher.Opens == 1, "tampered candidate must not launch");
            Check(coordinator.CurrentSnapshot.Phase == GoalDeliveryPhase.Failed, "tamper closes ready state");
        }

        public async Task RequiredFailureNeverFallsBackAsync()
        {
            _failMaster = true;
            const string job = "required-failure";
            const string goal = "goal-required";
            await using var coordinator = NewCoordinator(true, false);
            var continuation = Continuation(goal, job);
            await AwaitPhaseAsync(coordinator, goal, continuation, GoalDeliveryPhase.Failed).ConfigureAwait(false);
            Check(!coordinator.CurrentSnapshot.CanOpen, "required failure cannot open C004");
            Check(!await coordinator.OpenCurrentAsync().ConfigureAwait(false), "master failure never falls back");
            Check(_launcher.Opens == 0, "required failure cannot launch");
        }

        public async Task RestartFromDurableFilesAsync()
        {
            const string job = "restart-job";
            const string goal = "restart-goal";
            var c = Continuation(goal, job);
            await using (var first = NewCoordinator(false, true))
            {
                await AwaitPhaseAsync(first, goal, c, GoalDeliveryPhase.DeliveryReady).ConfigureAwait(false);
            }
            var previousComposes = _composeCalls;
            await using (var second = NewCoordinator(false, true))
            {
                // The new coordinator has no candidate/running/failed memory.
                Check(second.CurrentSnapshot.Phase == GoalDeliveryPhase.Idle, "restart starts empty");
                await AwaitPhaseAsync(second, goal, c, GoalDeliveryPhase.DeliveryReady).ConfigureAwait(false);
                Check(_composeCalls == previousComposes + 1, "plans/manifests drive new reconcile");
                Check(await second.OpenCurrentAsync().ConfigureAwait(false), "restart candidate reverified");
                Check(_launcher.Opens == 1, "restart exact candidate opened");
            }
        }

        public async Task SwitchAndCancellationAsync()
        {
            _delayFirstAssembler = true;
            const string firstGoal = "old-goal";
            const string firstJob = "old-job";
            const string newGoal = "new-goal";
            const string newJob = "new-job";
            await using var coordinator = NewCoordinator(false, false);
            var old = Continuation(firstGoal, firstJob);
            var next = Continuation(newGoal, newJob);
            coordinator.Observe(firstGoal, old);
            // Ensure the first reconcile reaches the artificial delayed assembler.
            for (var i = 0; i < 200 && Volatile.Read(ref _assembleCallCount) == 0; i++)
            {
                await Task.Delay(10).ConfigureAwait(false);
            }
            Check(_assembleCallCount > 0, "first goal reconcile started");
            coordinator.Observe(newGoal, next);
            await AwaitPhaseAsync(coordinator, newGoal, next, GoalDeliveryPhase.DeliveryReady)
                .ConfigureAwait(false);
            _releaseFirst.TrySetResult(true);
            await Task.Delay(100).ConfigureAwait(false);
            Check(coordinator.CurrentSnapshot.GoalId == newGoal
                && coordinator.CurrentSnapshot.ProductionJobId == newJob,
                "old completion must not overwrite new Goal");
            Check(coordinator.CurrentSnapshot.Phase == GoalDeliveryPhase.DeliveryReady,
                "new Goal remains QA-approved after stale completion");
            Check(await coordinator.OpenCurrentAsync().ConfigureAwait(false), "new Goal candidate opens");
            Check(_launcher.LastPath!.Contains(Sha(newJob)[..32], StringComparison.Ordinal),
                "opened current job, not stale job");
        }

        public async Task DisposeDuringReconciliationAsync()
        {
            _delayFirstAssembler = true;
            var coordinator = NewCoordinator(false, false);
            const string goal = "shutdown-goal";
            const string job = "shutdown-job";
            coordinator.Observe(goal, Continuation(goal, job));
            for (var i = 0; i < 200 && Volatile.Read(ref _assembleCallCount) == 0; i++)
            {
                await Task.Delay(10).ConfigureAwait(false);
            }
            Check(_assembleCallCount > 0, "cancellation fixture must enter reconcile");
            await coordinator.DisposeAsync().ConfigureAwait(false);
            Check(coordinator.CurrentSnapshot.Phase != GoalDeliveryPhase.Failed,
                "shutdown cancellation must never publish Failed");
            Check(_launcher.Opens == 0, "shutdown cancellation cannot open");
        }

        private PostProductionDeliveryCoordinator NewCoordinator(bool narration, bool overlays)
        {
            var assembler = new FakeAssembler(async (job, ct) =>
            {
                var call = Interlocked.Increment(ref _assembleCallCount);
                if (_delayFirstAssembler && call == 1)
                {
                    await _releaseFirst.Task.WaitAsync(ct).ConfigureAwait(false);
                }
                return await MakeFallbackAsync(job).ConfigureAwait(false);
            });
            return new PostProductionDeliveryCoordinator(
                assembler,
                (job, _) => Task.FromResult(NarrationPlan(job, narration)),
                (job, _) => Task.FromResult(OverlayPlan(job, overlays)),
                (_, _) => Task.FromResult(new NarrationArtifact("synthetic", [])),
                (_, _, _) => Task.FromResult(new TextOverlayArtifact(
                    "synthetic", Digest, Digest, "video.square.v1", "synthetic",
                    "synthetic", Digest, 1, false, false)),
                async (input, ct) =>
                {
                    Interlocked.Increment(ref _composeCalls);
                    if (_failMaster) throw new InvalidOperationException("synthetic master unavailable");
                    if (input.NarrationPlan.Plan.NarrationRequired
                        || input.OverlayPlan.Plan.OverlaysRequired)
                    {
                        var master = await MakeMasterAsync(
                            input.C004, input.NarrationPlan, input.OverlayPlan, ct).ConfigureAwait(false);
                        return new MasterCompositionResult(true, null, master);
                    }
                    return new MasterCompositionResult(false, input.C004, null);
                },
                _verifier, _launcher,
                _qaWired ? AuthorityAsync : null,
                _qaWired ? VerifyQaAsync : null);
        }

        // ── Test-scoped C011 authority: contract-consistent Core facts, stable per job ──
        private Task<C011QaDeliveryAuthority> AuthorityAsync(string goal, string job, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            var key = goal + "\u001f" + job;
            lock (_authorities)
            {
                if (!_authorities.TryGetValue(key, out var authority))
                {
                    var created = new DateTimeOffset(2026, 1, 1, 0, 0, 0, TimeSpan.Zero);
                    var plan = new ProductionPlanRecord("1.0", "production.comfyui.v1", job, "creative",
                        Digest, "project", "video.square.v1", 2000,
                        [new ProductionTaskPlanRecord("00000000-0000-0000-0000-000000000001", "shot", 1,
                            "TEXT_CARD", "Executable", "text-card.v1", "text card", "fixed", 1, 640, 640, 24, 49, 2000, null)]);
                    authority = new C011QaDeliveryAuthority(
                        Continuation(goal, job),
                        new ProductionJobRecord(job, "creative", Digest, "project", "video.square.v1", Digest,
                            "production_ready", null, null, null, null, "idem", created, created, null),
                        plan,
                        new ProductionPackageRecord("package", job, "creative", Digest, Digest, "unused",
                            JsonSerializer.SerializeToElement(new { }), "PASS", created));
                    _authorities[key] = authority;
                }
                if (_authorityDrift)
                {
                    return Task.FromResult(authority with
                    {
                        Goal = authority.Goal with { ReturnSha256 = Sha("drifted-return") },
                    });
                }
                return Task.FromResult(authority);
            }
        }

        private static readonly string[] QaChecks =
        [
            "lineage.v1", "managed-file.v1", "sha-bytes.v1", "mp4-probe.v1", "full-decode.v1",
            "video-stream.v1", "output-profile.v1", "runtime.v1", "audio-contract.v1",
            "unexpected-streams.v1", "overlay-provenance.v1",
        ];

        /// <summary>
        /// Test-scoped stand-in for C010A: it is fail-closed too. It re-hashes the selected managed file,
        /// checks lineage against the Core authority input and only then issues a receipt whose digest
        /// follows the same canonical rule as the production receipt. No decode/GPU is claimed here.
        /// </summary>
        private async Task<FinalVideoQaResult> VerifyQaAsync(FinalVideoQaInputV1 input, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            Interlocked.Increment(ref _qaCalls);
            if (_qaDeny) throw new InvalidDataException("synthetic QA denial");
            var c004 = input.MasterInput.C004;
            var master = input.MasterArtifact;
            var narration = input.MasterInput.NarrationPlan;
            var overlay = input.MasterInput.OverlayPlan;
            var path = master?.FilePath ?? c004.FilePath;
            var bytes = await File.ReadAllBytesAsync(path, ct).ConfigureAwait(false);
            var sha = Sha(bytes);
            if (sha != (master?.Sha256 ?? c004.Sha256) || bytes.LongLength != (master?.Bytes ?? c004.Bytes)
                || input.ProductionJob.ProductionJobId != c004.ProductionJobId
                || input.GoalContinuation.ProductionJobId != c004.ProductionJobId)
            {
                throw new InvalidDataException("synthetic QA lineage/bytes mismatch");
            }
            var kind = master is null ? "c004_fallback_v1" : "c009_master_v1";
            var qaInput = Sha(string.Join("|", kind, c004.ProductionJobId, sha, narration.NarrationPlanDigest,
                overlay.CaptionOverlayPlanDigest, master?.MasterInputDigest ?? ""));
            var receipt = new FinalArtifactReceiptV1(
                "1.0", "final-video.qa.windows.v1", qaInput, Digest, "PASS",
                input.GoalContinuation.GoalId, input.GoalContinuation.HandoffSha256,
                input.GoalContinuation.ReturnSha256, input.GoalContinuation.CreativeJobId,
                input.GoalContinuation.CreativePackageId, input.GoalContinuation.CreativePackageDigest,
                c004.ProductionJobId, narration.Plan.ProductionPlanDigest, c004.ProductionPackageId,
                c004.ProductionPackageDigest, narration.Plan.TargetRuntimeMs, overlay.Plan.OutputProfileId,
                narration.Plan.NarrationRequired, narration.NarrationPlanDigest, null, [],
                false, overlay.Plan.OverlaysRequired, overlay.CaptionOverlayPlanDigest,
                null, null, null, Digest, c004.Sha256, c004.Bytes,
                kind, "synthetic-root-v1", master is null ? "c004" : "c009",
                sha, bytes.LongLength, null, null, null, master?.MasterInputDigest, null,
                Path.GetFileName(path), sha, bytes.LongLength,
                new FinalQaObservedMedia("mp4", 2_000_000, 1,
                    new FinalQaVideoFacts(0, "h264", "yuv420p", 640, 640, 24, 1, 2_000_000, 49), null),
                QaChecks, new DateTimeOffset(2026, 1, 1, 0, 0, 0, TimeSpan.Zero));
            receipt = receipt with { ReceiptDigest = ReceiptDigest(receipt) };
            var receiptPath = Path.Combine(_receiptRoot, receipt.QaInputDigest + ".json");
            if (!File.Exists(receiptPath))
            {
                await File.WriteAllTextAsync(receiptPath, receipt.ReceiptDigest, ct).ConfigureAwait(false);
            }
            if (_swapReceiptAtOpen && Volatile.Read(ref _qaCalls) > 1)
            {
                receipt = receipt with { ReceiptDigest = Sha("swapped-receipt") };
            }
            return new FinalVideoQaResult(receipt, receiptPath, Reused: Volatile.Read(ref _qaCalls) > 1);
        }

        // Same canonical rule as the production receipt digest: snake_case, minus digest and timestamp.
        private static string ReceiptDigest(FinalArtifactReceiptV1 receipt)
        {
            var options = new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
                UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Disallow,
                RespectRequiredConstructorParameters = true,
                RespectNullableAnnotations = true,
                MaxDepth = 32,
            };
            var node = JsonSerializer.SerializeToNode(receipt, options)!.AsObject();
            node.Remove("receipt_digest");
            node.Remove("verified_at");
            return Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(node))).ToLowerInvariant();
        }

        // ── C011 regressions ─────────────────────────────────────────────────────────
        public async Task NoQaAuthorityFailsClosedAsync()
        {
            _qaWired = false;
            const string goal = "goal-noqa";
            const string job = "job-noqa";
            await using var coordinator = NewCoordinator(false, false);
            var continuation = Continuation(goal, job);
            await AwaitPhaseAsync(coordinator, goal, continuation, GoalDeliveryPhase.Failed).ConfigureAwait(false);
            Check(!coordinator.CurrentSnapshot.CanOpen, "no QA authority: C004 must not be openable");
            Check(!await coordinator.OpenCurrentAsync().ConfigureAwait(false), "no QA authority: Open refused");
            Check(_launcher.Opens == 0, "no QA authority: nothing launched");
            Check(_qaCalls == 0, "no QA authority: verifier never reached");
        }

        public async Task UnapprovedReceiptNeverReadyAsync()
        {
            _qaDeny = true;
            const string goal = "goal-deny";
            const string job = "job-deny";
            await using var coordinator = NewCoordinator(false, false);
            var continuation = Continuation(goal, job);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(12));
            while (!timeout.IsCancellationRequested)
            {
                var state = coordinator.Observe(goal, continuation);
                Check(state.Phase != GoalDeliveryPhase.DeliveryReady && !state.CanOpen,
                    "unapproved candidate must never become Ready/openable");
                if (state.Phase is GoalDeliveryPhase.Failed or GoalDeliveryPhase.QaFailed) break;
                await Task.Delay(20).ConfigureAwait(false);
            }
            Check(coordinator.CurrentSnapshot.Phase is GoalDeliveryPhase.Failed or GoalDeliveryPhase.QaFailed,
                "QA denial must close the candidate");
            Check(!await coordinator.OpenCurrentAsync().ConfigureAwait(false) && _launcher.Opens == 0,
                "QA denial: Open refused, nothing launched");
        }

        public async Task OpenRejectsChangedAuthorityOrReceiptAsync()
        {
            const string goal = "goal-open";
            const string job = "job-open";
            var continuation = Continuation(goal, job);

            // Receipt identity swapped by the click-time verifier -> exact receipt required.
            _swapReceiptAtOpen = true;
            await using (var swapped = NewCoordinator(false, false))
            {
                await AwaitPhaseAsync(swapped, goal, continuation, GoalDeliveryPhase.DeliveryReady).ConfigureAwait(false);
                Check(!await swapped.OpenCurrentAsync().ConfigureAwait(false), "swapped receipt must not open");
                Check(!swapped.CurrentSnapshot.CanOpen, "swapped receipt closes Ready");
            }
            _swapReceiptAtOpen = false;

            // Core authority drifts after Ready -> stale in-memory Ready has no authority.
            Interlocked.Exchange(ref _qaCalls, 0);
            await using (var drifted = NewCoordinator(false, false))
            {
                await AwaitPhaseAsync(drifted, goal, continuation, GoalDeliveryPhase.DeliveryReady).ConfigureAwait(false);
                _authorityDrift = true;
                Check(!await drifted.OpenCurrentAsync().ConfigureAwait(false), "changed authority must not open");
            }
            _authorityDrift = false;
            Check(_launcher.Opens == 0, "rejected opens never launch");

            // Control: an untouched approved candidate still opens exactly once.
            using var control = new Fixture();
            await control.OpenOnceAsync().ConfigureAwait(false);
        }

        public async Task OpenOnceAsync()
        {
            const string goal = "goal-control";
            const string job = "job-control";
            await using var coordinator = NewCoordinator(false, false);
            await AwaitPhaseAsync(coordinator, goal, Continuation(goal, job), GoalDeliveryPhase.DeliveryReady)
                .ConfigureAwait(false);
            Check(await coordinator.OpenCurrentAsync().ConfigureAwait(false), "exact receipt opens");
            Check(_launcher.Opens == 1, "control opens exactly once");
        }

        private async Task<FinalVideoArtifact> MakeFallbackAsync(string job)
        {
            var hash = Sha(job)[..32];
            var movie = Path.Combine(_finalRoot, "final-" + hash + ".mp4");
            var manifest = Path.Combine(_finalRoot, "final-" + hash + ".final-video.json");
            if (!File.Exists(movie)) await File.WriteAllTextAsync(movie, "visual-" + job).ConfigureAwait(false);
            if (!File.Exists(manifest)) await File.WriteAllTextAsync(manifest, "manifest-" + job).ConfigureAwait(false);
            return new FinalVideoArtifact(job, "package", Digest, movie, manifest, Sha(await File.ReadAllBytesAsync(movie)),
                new FileInfo(movie).Length, true);
        }

        private async Task<MasterVideoArtifact> MakeMasterAsync(
            FinalVideoArtifact source, NarrationPlanResponseRecord narration,
            CaptionOverlayPlanResponseRecord overlay, CancellationToken ct)
        {
            var job = source.ProductionJobId;
            var directory = Path.Combine(_masterRoot, job + "-" + Sha(job)[..16], Digest);
            Directory.CreateDirectory(directory);
            var movie = Path.Combine(directory, "master.mp4");
            var manifest = Path.Combine(directory, "master-manifest.json");
            if (!File.Exists(movie)) await File.WriteAllTextAsync(movie, "master-" + job, ct).ConfigureAwait(false);
            if (!File.Exists(manifest)) await File.WriteAllTextAsync(manifest, "master-manifest-" + job, ct).ConfigureAwait(false);
            return new MasterVideoArtifact(job, source.ProductionPackageId, source.ProductionPackageDigest,
                narration.Plan.ProductionPlanDigest, Digest, overlay.Plan.OutputProfileId,
                narration.Plan.TargetRuntimeMs, movie, manifest, Sha(await File.ReadAllBytesAsync(movie, ct)),
                new FileInfo(movie).Length, narration.Plan.NarrationRequired,
                overlay.Plan.OverlaysRequired ? PostProductionMasterProfiles.C008BVisualKind
                    : PostProductionMasterProfiles.C004VisualKind, true);
        }

        private static async Task AwaitPhaseAsync(
            PostProductionDeliveryCoordinator coordinator, string goal,
            GoalVideoContinuationRecord continuation, GoalDeliveryPhase expected)
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(12));
            while (!timeout.IsCancellationRequested)
            {
                var state = coordinator.Observe(goal, continuation);
                if (state.Phase == expected) return;
                if (state.Phase is GoalDeliveryPhase.Failed or GoalDeliveryPhase.QaFailed
                    && expected is not (GoalDeliveryPhase.Failed or GoalDeliveryPhase.QaFailed))
                {
                    throw new InvalidOperationException("C009C unexpected failure in " + expected);
                }
                await Task.Delay(20).ConfigureAwait(false);
            }
            throw new TimeoutException("C009C did not reach " + expected);
        }

        public void Dispose()
        {
            _releaseFirst.TrySetResult(true);
            try { Directory.Delete(_root, recursive: true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
