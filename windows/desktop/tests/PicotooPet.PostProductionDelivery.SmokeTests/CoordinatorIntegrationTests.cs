using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
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

        public Fixture()
        {
            _finalRoot = Path.Combine(_root, "FinalVideos");
            _masterRoot = Path.Combine(_root, "Master", "v1");
            Directory.CreateDirectory(_finalRoot);
            Directory.CreateDirectory(_masterRoot);
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
            var expected = narrationRequired || overlaysRequired
                ? GoalDeliveryPhase.MasteredReady : GoalDeliveryPhase.FallbackReady;
            await AwaitPhaseAsync(coordinator, goal, continuation, expected).ConfigureAwait(false);
            Check(coordinator.CurrentSnapshot.CanOpen, "ready candidate must be openable");
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
                await AwaitPhaseAsync(first, goal, c, GoalDeliveryPhase.MasteredReady).ConfigureAwait(false);
            }
            var previousComposes = _composeCalls;
            await using (var second = NewCoordinator(false, true))
            {
                // The new coordinator has no candidate/running/failed memory.
                Check(second.CurrentSnapshot.Phase == GoalDeliveryPhase.Idle, "restart starts empty");
                await AwaitPhaseAsync(second, goal, c, GoalDeliveryPhase.MasteredReady).ConfigureAwait(false);
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
            await AwaitPhaseAsync(coordinator, newGoal, next, GoalDeliveryPhase.FallbackReady)
                .ConfigureAwait(false);
            _releaseFirst.TrySetResult(true);
            await Task.Delay(100).ConfigureAwait(false);
            Check(coordinator.CurrentSnapshot.GoalId == newGoal
                && coordinator.CurrentSnapshot.ProductionJobId == newJob,
                "old completion must not overwrite new Goal");
            Check(coordinator.CurrentSnapshot.Phase == GoalDeliveryPhase.FallbackReady,
                "new Goal remains ready after stale completion");
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
                _verifier, _launcher);
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
                if (state.Phase == GoalDeliveryPhase.Failed && expected != GoalDeliveryPhase.Failed)
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
