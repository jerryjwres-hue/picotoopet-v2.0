using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;
using PicotooPet.FinalVideoQa.SmokeTests;

namespace PicotooPet.G005.FinalVideoE2E;

// G005 only. This is an independently executed FV-001..FV-036 test case driver;
// C011 source and C010A Fixture/LifecycleTests are compile-linked from the
// exact pinned C011 checkout. No QA service, catalog or receipt implementation
// is duplicated or replaced. The injected Core authority is CONTROLLED, never
// represented as a live Mac Core HTTP session.
internal static class Program
{
    private static readonly List<Result> Results = new();
    private static readonly AsyncLocal<int> Assertions = new();
    private const string Sha = "ec468b9975a3b1cd706e6e74223bfb05f7733a86";
    private static string _root = "";

    private sealed record Result(string id, string status, string scope, string assertion,
        int assertions, string? blocker, string? error, string evidence);

    private static async Task<int> Main(string[] args)
    {
        var index = Array.IndexOf(args, "--report");
        if (index < 0 || index + 1 >= args.Length)
        {
            Console.Error.WriteLine("G005_USAGE: --report <path>");
            return 2;
        }
        _root = Path.GetFullPath(args[index + 1]);
        Directory.CreateDirectory(Path.GetDirectoryName(_root)!);
        await Run("FV-001", "C011_QA_CONTROLLED_CORE", "no postproduction exact fallback+open", () => Mode(false, false));
        await Run("FV-002", "C011_QA_CONTROLLED_CORE", "stale unrelated master never selected", StaleMaster);
        await Run("FV-003", "C011_QA_CONTROLLED_CORE", "narration only mandatory C009 selection", () => Mode(true, false));
        await Run("FV-004", "C011_QA_CONTROLLED_CORE", "overlay only mandatory C009 selection", () => Mode(false, true));
        await Run("FV-005", "C011_QA_CONTROLLED_CORE", "narration and overlay mandatory C009 selection", () => Mode(true, true));
        await Run("FV-006", "C010A_REAL_POLICY", "true captions unsupported; reject", CaptionsUnsupported);
        await Run("FV-007", "C011_QA_CONTROLLED_CORE", "required master absent never fallback", MissingMaster);
        await Run("FV-008", "C011_QA_CONTROLLED_CORE", "narration failure and new coordinator recovery", () => FailureRecover(true, false, "narration"));
        await Run("FV-009", "C011_QA_CONTROLLED_CORE", "overlay failure and new coordinator recovery", () => FailureRecover(false, true, "overlay"));
        await Run("FV-010", "C011_QA_CONTROLLED_CORE", "composition error bounded; new coordinator retry", () => FailureRecover(true, false, "mux"));
        await Run("FV-011", "C011_QA_CONTROLLED_CORE", "C010A decode error forbids PASS receipt and launch", DecodeFailure);
        Block("FV-012", "TRUE_PROCESS_CRASH_MID_ATOMIC_COMMIT_NOT_EXECUTED", "Requires adversarial external PID kill inside atomic C009A commit, not fixture deletion");
        await Run("FV-013", "C011_QA_CONTROLLED_CORE", "master before failed receipt then fresh coordinator completes QA", MasterBeforeQaRecovery);
        await Run("FV-014", "C011_QA_CONTROLLED_CORE", "fresh coordinator restart recovers receipt", Restart);
        await Run("FV-015", "C011_QA_CONTROLLED_CORE", "C004 content SHA tamper before postproduction", () => UpstreamTamper("c004"));
        await Run("FV-016", "C011_QA_CONTROLLED_CORE", "WAV content SHA tamper before postproduction", () => UpstreamTamper("wav"));
        await Run("FV-017", "C011_QA_CONTROLLED_CORE", "overlay media SHA tamper before postproduction", () => UpstreamTamper("overlay"));
        await Run("FV-018", "C011_QA_CONTROLLED_CORE", "click-time master MP4 mutated after approved receipt", () => TamperAtClick("master"));
        await Run("FV-019", "C011_QA_CONTROLLED_CORE", "click-time master manifest mutated", () => TamperAtClick("manifest"));
        await Run("FV-020", "C011_QA_CONTROLLED_CORE", "click-time PASS receipt digest/contents mutated", () => TamperAtClick("receipt"));
        await Run("FV-021", "C011_QA_CONTROLLED_CORE", "Goal creative/production authority mismatch cannot approve", WrongAuthority);
        await Run("FV-022", "C011_QA_CONTROLLED_CORE", "wrong C009 MasterInputDigest refused", WrongMasterDigest);
        await Run("FV-023", "C011_QA_CONTROLLED_CORE", "upstream manifest SHA changes after PASS; stale QA receipt cannot open", ChangedManifest);
        await Run("FV-024", "C011_QA_CONTROLLED_CORE", "receipt directory identity conflict cannot authorize open", () => TamperAtClick("receipt-unknown"));
        await Run("FV-025", "C011_QA_CONTROLLED_CORE", "ready to click bytes change triggers fresh SHA denial", () => TamperAtClick("c004"));
        await Run("FV-026", "C011_QA_CONTROLLED_CORE", "missing managed file at click cannot launch stale path", () => TamperAtClick("missing"));
        await Run("FV-027", "C011_QA_CONTROLLED_CORE", "same candidate bytes, changed manifest rejected at click", () => TamperAtClick("c004-manifest"));
        await Run("FV-028", "C011_QA_CONTROLLED_CORE", "malformed ffprobe through actual QA service denied", BadProbe);
        await Run("FV-029", "C010A_REAL_NATIVE_MEDIA", "actual header-readable corrupt video full decode rejected", RealCorruptDecode);
        await Run("FV-030", "C011_REAL_NATIVE_MEDIA_CONTROLLED_CORE", "three C005 real profile combinations QA and open", ThreeProfiles);
        Block("FV-031", "COMPLETE_REAL_AAC_TIMELINE_CORRUPTION_NOT_TESTED", "Upstream audio policy component tests do not prove adversarial silent-interval alignment E2E");
        Unverified("FV-032", "PUBLISHED_GUI_CONCURRENT_CLICK_NOT_EXECUTED");
        Unverified("FV-033", "INSTALLED_PUBLISHED_APP_FRESH_LOCALAPPDATA_NOT_EXECUTED");
        Unverified("FV-034", "ADVERSARIAL_PID_FORCE_KILL_AND_RESTART_NOT_EXECUTED");
        Block("FV-035", "REAL_MISSING_FFMPEG_PATH_NOT_INJECTED", "A synthetic process error does not prove native missing-binary lifecycle");
        await Run("FV-036", "C011_QA_CONTROLLED_CORE", "untrusted forged receipt cannot authorize Open", () => TamperAtClick("receipt-forged"));

        var count = Results.Count;
        CheckNoDuplicates(count);
        var counts = new
        {
            total = count,
            pass = Results.Count(x => x.status == "PASS"),
            fail = Results.Count(x => x.status == "FAIL"),
            blocked = Results.Count(x => x.status == "BLOCKED"),
            unverified = Results.Count(x => x.status == "UNVERIFIED"),
            qa_gated_e2e_pass = Results.Count(x => x.status == "PASS" && x.scope.StartsWith("C011_", StringComparison.Ordinal))
        };
        var report = new
        {
            schema_version = "g005-independent-fv36.v1",
            c011_sha = Sha,
            environment = "GitHub Windows runner; controlled Core authority (NOT live Mac Core)",
            created_utc = DateTimeOffset.UtcNow,
            counts,
            cases = Results
        };
        await File.WriteAllTextAsync(_root, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
        Console.WriteLine($"FV_G005_SUMMARY PASS={counts.pass} FAIL={counts.fail} BLOCKED={counts.blocked} UNVERIFIED={counts.unverified}");
        Console.WriteLine($"FV_G005_QA_GATED_CONTROLLED_CORE_PASS={counts.qa_gated_e2e_pass}");
        return counts.fail == 0 ? 0 : 1;
    }

    private static void CheckNoDuplicates(int count)
    {
        if (count != 36 || Results.Select(x => x.id).Distinct(StringComparer.Ordinal).Count() != 36
            || !Enumerable.Range(1, 36).All(n => Results.Any(x => x.id == $"FV-{n:D3}")))
            throw new InvalidOperationException("G005_MISSING_OR_DUPLICATE_SCENARIO");
    }

    private static void Check(bool ok, string reason)
    {
        Assertions.Value++;
        if (!ok) throw new InvalidOperationException("FV_ASSERT_" + reason);
    }

    private static async Task Run(string id, string scope, string oracle, Func<Task> action)
    {
        Assertions.Value = 0;
        try
        {
            await action();
            Check(Assertions.Value > 0, "scenario needs actual independent oracle");
            var n = Assertions.Value;
            Results.Add(new(id, "PASS", scope, oracle, n, null, null, $"{id}=PASS"));
            Console.WriteLine($"{id}=PASS scope={scope} assertions={n}");
        }
        catch (Exception error)
        {
            Results.Add(new(id, "FAIL", scope, oracle, Assertions.Value, null,
                error.GetType().Name + ":" + error.Message, $"{id}=FAIL"));
            Console.WriteLine($"{id}=FAIL type={error.GetType().Name}");
        }
    }
    private static void Block(string id, string code, string description)
    {
        Results.Add(new(id, "BLOCKED", "REQUIRES_ADVERSARIAL_OR_REAL_ENV", description, 0, code, null, $"{id}=BLOCKED"));
        Console.WriteLine($"{id}=BLOCKED reason={code}");
    }
    private static void Unverified(string id, string code)
    {
        Results.Add(new(id, "UNVERIFIED", "MANUAL_OR_LIVE_INTEGRATION", code, 0, code, null, $"{id}=UNVERIFIED"));
        Console.WriteLine($"{id}=UNVERIFIED reason={code}");
    }

    private sealed class Launcher : IFinalVideoLauncher
    {
        public int Calls;
        public string? LastPath;
        public void Open(string path) { Interlocked.Increment(ref Calls); LastPath = path; }
    }
    private sealed class Assembler(FinalVideoArtifact artifact) : IFinalVideoAssembler
    {
        public Task<FinalVideoArtifact> AssembleAsync(string job, CancellationToken ct = default)
        {
            ct.ThrowIfCancellationRequested();
            if (job != artifact.ProductionJobId) throw new InvalidDataException("wrong job");
            return Task.FromResult(artifact);
        }
    }
    private sealed record Faults(string? Failure = null, bool MissingMaster = false,
        bool DecodeFailure = false, bool BadProbe = false, bool WrongMasterDigest = false,
        bool BadAuthority = false, bool NoQaGate = false);

    private static PostProductionDeliveryCoordinator Coordinator(Fixture f, Launcher launcher,
        Faults? faults = null, IMasterVideoProcessRunner? runner = null)
    {
        faults ??= new Faults();
        var source = f.Input;
        var baseline = LifecycleTests.Input(f, null);
        var authority = new C011QaDeliveryAuthority(
            baseline.GoalContinuation, baseline.ProductionJob, baseline.ProductionPlan, baseline.ProductionPackage);
        var verifier = new GoalDeliveryCandidateVerifier(Path.Combine(f.Root, "finals"), f.MasterRoot);
        var qa = LifecycleTests.Service(f,
            runner ?? (faults.BadProbe ? new BadProbeRunner() : new QaRunner(source.NarrationPlan.Plan.NarrationRequired) { DecodeFailure = faults.DecodeFailure }));
        return new PostProductionDeliveryCoordinator(
            new Assembler(source.C004),
            (job, ct) => Task.FromResult(source.NarrationPlan),
            (job, ct) => Task.FromResult(source.OverlayPlan),
            (plan, ct) => faults.Failure == "narration"
                ? Task.FromException<NarrationArtifact>(new IOException("injected narration error"))
                : Task.FromResult(source.NarrationArtifact ?? throw new InvalidDataException("missing test narration")),
            (c004, plan, ct) => faults.Failure == "overlay"
                ? Task.FromException<TextOverlayArtifact>(new IOException("injected overlay error"))
                : Task.FromResult(source.OverlayArtifact ?? throw new InvalidDataException("missing test overlay")),
            async (input, ct) =>
            {
                if (faults.Failure == "mux") throw new IOException("injected mux error");
                var master = await f.Service.ComposeAsync(input, ct);
                if (faults.MissingMaster) return new MasterCompositionResult(true, null, null);
                if (faults.WrongMasterDigest && master.Artifact is { } artifact)
                    return master with { Artifact = artifact with { MasterInputDigest = new string('f', 64) } };
                return master;
            },
            verifier, launcher,
            faults.NoQaGate ? null : (goal, job, ct) =>
                Task.FromResult(faults.BadAuthority
                    ? authority with { Goal = authority.Goal with { ReturnSha256 = Fixture.ShaValue("other-return") } }
                    : authority),
            faults.NoQaGate ? null : qa.VerifyAsync);
    }

    private sealed class BadProbeRunner : IMasterVideoProcessRunner
    {
        public Task<MasterVideoProcessResult> RunAsync(ProcessStartInfo start, TimeSpan timeout, CancellationToken ct)
            => Task.FromResult(new MasterVideoProcessResult(0, false, start.FileName == "ffprobe.exe" ? "{}" : ""));
    }

    private static async Task<GoalDeliverySnapshot> Wait(Fixture f,
        PostProductionDeliveryCoordinator c, GoalDeliveryPhase phase)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var continuation = LifecycleTests.Input(f, null).GoalContinuation;
        while (!timeout.IsCancellationRequested)
        {
            var s = c.Observe(continuation.GoalId, continuation);
            if (s.Phase == phase) return s;
            if (s.Phase is GoalDeliveryPhase.Failed or GoalDeliveryPhase.QaFailed
                && phase is not (GoalDeliveryPhase.Failed or GoalDeliveryPhase.QaFailed))
                throw new InvalidOperationException($"FV_UNEXPECTED_PHASE={s.Phase},want={phase}");
            await Task.Delay(20);
        }
        throw new TimeoutException($"FV_WAIT_{phase}");
    }
    private static async Task<GoalDeliverySnapshot> WaitFailure(Fixture f, PostProductionDeliveryCoordinator c)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var continuation = LifecycleTests.Input(f, null).GoalContinuation;
        while (!timeout.IsCancellationRequested)
        {
            var s = c.Observe(continuation.GoalId, continuation);
            if (s.Phase is GoalDeliveryPhase.Failed or GoalDeliveryPhase.QaFailed) return s;
            await Task.Delay(20);
        }
        throw new TimeoutException("FV_WAIT_FAILURE");
    }
    private static async Task Mode(bool narration, bool overlay)
    {
        using var f = await Fixture.CreateAsync(narration, overlay);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher);
        var ready = await Wait(f, c, GoalDeliveryPhase.DeliveryReady);
        Check(ready.CanOpen && ready.Phase == GoalDeliveryPhase.DeliveryReady, "receipt gated ready");
        Check(await c.OpenCurrentAsync(), "one approved open");
        Check(launcher.Calls == 1 && launcher.LastPath is not null, "single launcher invocation");
        Check(launcher.LastPath.Contains(narration || overlay ? "master.mp4" : "final-", StringComparison.OrdinalIgnoreCase),
            "correct C009 or C004 candidate");
    }
    private static async Task StaleMaster()
    {
        using var f = await Fixture.CreateAsync(false, false);
        using var historical = await Fixture.CreateAsync(true, false);
        var stale = await historical.Service.ComposeAsync(historical.Input);
        Check(stale.Artifact is not null, "old C009 exists, separate authority");
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher);
        await Wait(f, c, GoalDeliveryPhase.DeliveryReady);
        Check(await c.OpenCurrentAsync(), "valid current C004 fallback");
        Check(launcher.LastPath == f.Input.C004.FilePath, "historical master not selected");
    }
    private static async Task CaptionsUnsupported()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var input = LifecycleTests.Input(f, null);
        var bad = input with { MasterInput = f.Input with {
            OverlayPlan = f.Input.OverlayPlan with {
                Plan = f.Input.OverlayPlan.Plan with { CaptionsRequired = true }
            }
        } };
        await LifecycleTests.Throws("CAPTION_PROFILE_UNSUPPORTED",
            () => LifecycleTests.Service(f, new NeverRunner()).VerifyAsync(bad));
        Check(!Directory.Exists(Path.Combine(f.Root, "receipts")), "unsupported captions no receipt");
    }
    private static async Task MissingMaster()
    {
        using var f = await Fixture.CreateAsync(true, false);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, new Faults(MissingMaster: true));
        var failed = await WaitFailure(f, c);
        Check(!failed.CanOpen && !await c.OpenCurrentAsync(), "missing required master no fallback");
        Check(launcher.Calls == 0, "no shell");
    }
    private static async Task FailureRecover(bool narration, bool overlay, string failing)
    {
        using var f = await Fixture.CreateAsync(narration, overlay);
        var launcher = new Launcher();
        await using (var broken = Coordinator(f, launcher, new Faults(Failure: failing)))
        {
            var failed = await WaitFailure(f, broken);
            Check(failed.Phase == GoalDeliveryPhase.Failed && !failed.CanOpen, "injected dependency fails closed");
            Check(!await broken.OpenCurrentAsync() && launcher.Calls == 0, "no failed launch");
        }
        await using (var recovered = Coordinator(f, launcher))
        {
            var ready = await Wait(f, recovered, GoalDeliveryPhase.DeliveryReady);
            Check(ready.CanOpen && await recovered.OpenCurrentAsync(), "new coordinator retries");
            Check(launcher.Calls == 1, "recovery only opens exact candidate");
        }
    }
    private static async Task DecodeFailure()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var launch = new Launcher();
        await using var c = Coordinator(f, launch, new Faults(DecodeFailure: true));
        var failed = await WaitFailure(f, c);
        Check(failed.Phase == GoalDeliveryPhase.QaFailed, "decode QA failure state");
        Check(!failed.CanOpen && !await c.OpenCurrentAsync() && launch.Calls == 0, "decode fail closed");
        Check(!Directory.Exists(Path.Combine(f.Root, "receipts")), "no fake PASS");
    }
    private static async Task MasterBeforeQaRecovery()
    {
        using var f = await Fixture.CreateAsync(true, false);
        var launch = new Launcher();
        await using (var first = Coordinator(f, launch, new Faults(DecodeFailure: true)))
        {
            Check((await WaitFailure(f, first)).Phase == GoalDeliveryPhase.QaFailed, "QA failure after master");
            Check(f.Composer.Calls == 1, "master exists before receipt");
            Check(!Directory.Exists(Path.Combine(f.Root, "receipts")), "no PASS after QA failed");
        }
        await using (var restart = Coordinator(f, launch))
        {
            Check((await Wait(f, restart, GoalDeliveryPhase.DeliveryReady)).CanOpen, "new coordinator recomputes QA");
            Check(f.Composer.Calls == 1, "reuses genuine durable C009A master");
            Check(await restart.OpenCurrentAsync() && launch.Calls == 1, "approved open only after QA");
        }
    }
    private static async Task Restart()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var launch = new Launcher();
        await using (var original = Coordinator(f, launch))
            Check((await Wait(f, original, GoalDeliveryPhase.DeliveryReady)).CanOpen, "first receipt ready");
        await using var restarted = Coordinator(f, launch);
        Check(restarted.CurrentSnapshot.Phase == GoalDeliveryPhase.Idle, "fresh process-like coordinator memory");
        Check((await Wait(f, restarted, GoalDeliveryPhase.DeliveryReady)).CanOpen, "exact persisted receipt restored");
        Check(await restarted.OpenCurrentAsync() && launch.Calls == 1, "restart approved");
    }
    private static async Task UpstreamTamper(string kind)
    {
        var narr = kind == "wav";
        var over = kind == "overlay";
        using var f = await Fixture.CreateAsync(narr, over);
        var file = kind switch
        {
            "c004" => f.Input.C004.FilePath,
            "wav" => f.Input.NarrationArtifact!.Segments[0].WavPath,
            _ => f.Input.OverlayArtifact!.FilePath
        };
        await File.AppendAllTextAsync(file, "g005-tamper");
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher);
        var failed = await WaitFailure(f, c);
        Check(!failed.CanOpen && !await c.OpenCurrentAsync(), "invalid source disallows delivery");
        Check(launcher.Calls == 0, "source SHA failure no shell");
        Check(!Directory.Exists(Path.Combine(f.Root, "receipts")), "no PASS receipt on invalid upstream");
    }
    private static async Task TamperAtClick(string kind)
    {
        var required = kind is "master" or "manifest";
        using var f = await Fixture.CreateAsync(required, false);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher);
        var ready = await Wait(f, c, GoalDeliveryPhase.DeliveryReady);
        Check(ready.CanOpen, "real service approved before test tamper");
        var master = (await f.Service.ComposeAsync(f.Input)).Artifact;
        var input = LifecycleTests.Input(f, master);
        var receipt = await LifecycleTests.Service(f, new NeverRunner()).VerifyAsync(input);
        string changed;
        switch (kind)
        {
            case "master": changed = master!.FilePath; await File.AppendAllTextAsync(changed, "tamper"); break;
            case "manifest": changed = master!.ManifestPath; await File.AppendAllTextAsync(changed, "tamper"); break;
            case "receipt": changed = receipt.ReceiptPath; await File.AppendAllTextAsync(changed, "tamper"); break;
            case "receipt-unknown":
                changed = receipt.ReceiptPath;
                var unknown = JsonNode.Parse(await File.ReadAllTextAsync(changed))!.AsObject();
                unknown["untrusted_added"] = true;
                await File.WriteAllTextAsync(changed, unknown.ToJsonString());
                break;
            case "receipt-forged":
                changed = receipt.ReceiptPath;
                await File.WriteAllTextAsync(changed, "{\"outcome\":\"PASS\",\"receipt_digest\":\"" + new string('f',64) + "\"}");
                break;
            case "c004": changed = f.Input.C004.FilePath; await File.AppendAllTextAsync(changed, "byte-flip"); break;
            case "missing": changed = f.Input.C004.FilePath; File.Move(changed, changed + ".moved"); break;
            case "c004-manifest": changed = f.Input.C004.ManifestPath; await File.AppendAllTextAsync(changed, "changed-manifest"); break;
            default: throw new InvalidOperationException("unexpected mutation");
        }
        Check(!await c.OpenCurrentAsync(), "click-time tamper never launches");
        Check(launcher.Calls == 0, "zero post-tamper launches");
        Check(!c.CurrentSnapshot.CanOpen, "invalidate ready after tamper");
    }
    private static async Task WrongAuthority()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, new Faults(BadAuthority: true));
        var s = await WaitFailure(f, c);
        Check(!s.CanOpen && !await c.OpenCurrentAsync(), "mismatched Goal authority denied");
        Check(launcher.Calls == 0, "no stale authority shell launch");
    }
    private static async Task WrongMasterDigest()
    {
        using var f = await Fixture.CreateAsync(true, false);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher, new Faults(WrongMasterDigest: true));
        var s = await WaitFailure(f, c);
        Check(!s.CanOpen && !await c.OpenCurrentAsync(), "wrong master digest is denied");
        Check(launcher.Calls == 0, "no stale digest launch");
    }
    private static async Task ChangedManifest()
    {
        using var f = await Fixture.CreateAsync(true, false);
        var launcher = new Launcher();
        await using var c = Coordinator(f, launcher);
        Check((await Wait(f, c, GoalDeliveryPhase.DeliveryReady)).CanOpen, "pre-manifest-change Ready");
        await File.AppendAllTextAsync(f.Input.NarrationArtifact!.ManifestPath, "provenance-sha-changed");
        Check(!await c.OpenCurrentAsync() && launcher.Calls == 0, "stale upstream manifest receipt rejected");
        Check(!c.CurrentSnapshot.CanOpen, "stale QA ready invalidated");
    }
    private static async Task BadProbe()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var launch = new Launcher();
        await using var c = Coordinator(f, launch, new Faults(BadProbe: true));
        var failed = await WaitFailure(f, c);
        Check(failed.Phase == GoalDeliveryPhase.QaFailed && !failed.CanOpen, "invalid native probe JSON bounded QA error");
        Check(!await c.OpenCurrentAsync() && launch.Calls == 0, "probe never authorizes shell");
        Check(!Directory.Exists(Path.Combine(f.Root,"receipts")), "invalid probe no receipt");
    }
    private static async Task RealCorruptDecode()
    {
        await RealMedia.CorruptionAndProcessLimitsAsync();
        Check(OperatingSystem.IsWindows(), "real Windows corruption/decode fixture actually executed");
    }
    private static async Task ThreeProfiles()
    {
        foreach(var (profile, width, height) in new[] {
            ("video.landscape.v1",832,480),("video.vertical.v1",480,832),("video.square.v1",640,640)})
        {
            using var f = await Fixture.CreateAsync(true, false, profile: profile, real: true);
            var launcher = new Launcher();
            await using var c = Coordinator(f, launcher, runner: new FixedMasterVideoProcessRunner());
            Check((await Wait(f, c, GoalDeliveryPhase.DeliveryReady)).CanOpen, "real media QA+receipt"+profile);
            var master = (await f.Service.ComposeAsync(f.Input)).Artifact!;
            var receipt = await LifecycleTests.Service(f, new NeverRunner()).VerifyAsync(LifecycleTests.Input(f, master));
            Check(receipt.Receipt.ObservedMedia.Video.Width == width &&
                  receipt.Receipt.ObservedMedia.Video.Height == height, "real 24fps media profile size"+profile);
            Check(receipt.Receipt.ObservedMedia.Video.FpsNumerator == 24 * receipt.Receipt.ObservedMedia.Video.FpsDenominator,
                 "real fps"+profile);
            Check(await c.OpenCurrentAsync() && launcher.Calls == 1, "one native QA-gated Open"+profile);
        }
    }
}
