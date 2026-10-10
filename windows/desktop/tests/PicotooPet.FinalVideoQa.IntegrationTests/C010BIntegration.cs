using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

// Independent C010B acceptance. Actual C010A types are referenced from the composed
// C010A checkout; Fixture.cs and LifecycleTests.cs are linked, never copied or edited.
// The friend assembly name is set by this project's csproj to access C010A's real
// test injection constructor and frozen policy, not to define an alternative QA API.
namespace PicotooPet.FinalVideoQa.SmokeTests;

internal static class C010BIntegration
{
    private static int _passed;
    private static int _failed;

    public static async Task<int> Main(string[] args)
    {
        await Case("candidate-selection-pass-only-4-modes", CandidateSelectionAsync);
        await Case("no-fallback-wrong-candidate", NoFallbackAsync);
        await Case("wrong-goal-production-and-plan-lineage", WrongLineageAsync);
        await Case("receipt-restart-no-decode", RestartReuseAsync);
        await Case("receipt-tamper-conflict", ReceiptTamperAsync);
        await Case("receipt-directory-conflict", DirectoryConflictAsync);
        await Case("qa-digest-new-provenance", DigestConflictAsync);
        await Case("qa-manifest-digest-independent-of-master", ManifestDigestAsync);
        await Case("failed-decode-no-pass-receipt", DecodeFailureAsync);
        await Case("failed-probe-no-pass-receipt", ProbeFailureAsync);
        await Case("artifact-tamper-after-pass", ArtifactTamperAsync);
        await Case("media-policy-negative-facts", MediaPolicyAsync);
        if (args.Contains("--real", StringComparer.Ordinal))
        {
            await Case("windows-real-four-delivery-shapes", RealWindowsAsync);
            await Case("windows-header-readable-corrupted-packets-rejected", RealCorruptMediaAsync);
            await Case("windows-process-timeout-and-cancel", RealProcessBoundariesAsync);
        }
        Console.WriteLine($"C010B_INTEGRATION_SUMMARY=passed={_passed};failed={_failed};real={args.Contains("--real", StringComparer.Ordinal)}");
        return _failed == 0 ? 0 : 1;
    }

    private static async Task Case(string name, Func<Task> test)
    {
        try
        {
            await test().ConfigureAwait(false);
            Interlocked.Increment(ref _passed);
            Console.WriteLine($"C010B_PASS {name}");
        }
        catch (Exception error)
        {
            Interlocked.Increment(ref _failed);
            Console.Error.WriteLine($"C010B_FAIL {name} error_type={error.GetType().Name} error_code={(error is FinalVideoQaException q ? q.Code : "UNEXPECTED")}");
        }
    }

    private static async Task<(MasterVideoArtifact? Master, FinalVideoQaInputV1 Input)> ComposeAsync(Fixture f)
    {
        var master = (await f.Service.ComposeAsync(f.Input).ConfigureAwait(false)).Artifact;
        return (master, LifecycleTests.Input(f, master));
    }

    private static Task<FinalVideoQaResult> VerifyAsync(Fixture f, FinalVideoQaInputV1 input, IMasterVideoProcessRunner runner)
        => LifecycleTests.Service(f, runner).VerifyAsync(input);

    private static void Check(bool predicate, string name) => LifecycleTests.Assert(predicate, name);

    private static async Task CandidateSelectionAsync()
    {
        foreach (var narr in new[] { false, true })
        foreach (var overlay in new[] { false, true })
        {
            using var f = await Fixture.CreateAsync(narr, overlay);
            var (master, input) = await ComposeAsync(f);
            Check((master is not null) == (narr || overlay), "C009A master presence follows actual plans");
            var result = await VerifyAsync(f, input, new QaRunner(narr));
            Check(result.Receipt.Outcome == "PASS" && !result.Reused, "only verified PASS is persisted");
            Check(result.Receipt.CandidateKind == (narr || overlay ? "c009_master_v1" : "c004_fallback_v1"),
                  "actual C010A candidate kind");
            Check(result.Receipt.NarrationRequired == narr && result.Receipt.OverlaysRequired == overlay, "plan flags bound");
            Check(result.Receipt.HasValidOutcome(), "receipt outcome fixed"); // local test-only extension below
            Check(File.Exists(result.ReceiptPath), "PASS file must exist");
            var root = Path.Combine(f.Root, "receipts");
            Check(Directory.EnumerateFiles(root, "final-artifact-receipt.json", SearchOption.AllDirectories).Count() == 1,
                  "only one immutable receipt");
            var json = await File.ReadAllTextAsync(result.ReceiptPath);
            Check(!json.Contains(f.Root, StringComparison.OrdinalIgnoreCase)
                  && !json.Contains(Fixture.NarrationText, StringComparison.Ordinal)
                  && !json.Contains(Fixture.OverlayText, StringComparison.Ordinal),
                  "no local absolute paths or authored text in receipt");
        }
    }

    private static async Task NoFallbackAsync()
    {
        foreach (var (narr, overlay) in new[] { (true, false), (false, true), (true, true) })
        {
            using var f = await Fixture.CreateAsync(narr, overlay);
            var (master, input) = await ComposeAsync(f);
            var actualMaster = master ?? throw new InvalidOperationException("master prerequisite");
            await LifecycleTests.Throws("MASTER_REQUIRED",
                () => VerifyAsync(f, input with { MasterArtifact = null }, new NeverRunner()));
            await LifecycleTests.Throws("LINEAGE_MISMATCH",
                () => VerifyAsync(f, input with { MasterArtifact = actualMaster with { MasterInputDigest = new string('f', 64) } },
                    new NeverRunner()));
            await LifecycleTests.Throws("LINEAGE_MISMATCH",
                () => VerifyAsync(f, input with { MasterArtifact = actualMaster with { FilePath = f.Input.C004.FilePath } },
                    new NeverRunner()));
            Check(!Directory.Exists(Path.Combine(f.Root, "receipts")), "wrong candidate must never receipt fallback C004");
        }
        using var bare = await Fixture.CreateAsync(false, false);
        using var historical = await Fixture.CreateAsync(true, false);
        var stale = (await ComposeAsync(historical)).Master;
        var (_, baseInput) = await ComposeAsync(bare);
        await LifecycleTests.Throws("INPUT_INVALID",
            () => VerifyAsync(bare, baseInput with { MasterArtifact = stale }, new NeverRunner()));
    }

    private static async Task WrongLineageAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var (_, input) = await ComposeAsync(f);
        var cases = new (string Name, FinalVideoQaInputV1 Invalid, string Error)[]
        {
            ("goal_job", input with { GoalContinuation = input.GoalContinuation with { ProductionJobId = "other-job" } }, "LINEAGE_MISMATCH"),
            ("creative_digest", input with { GoalContinuation = input.GoalContinuation with { CreativePackageDigest = new string('f', 64) } }, "LINEAGE_MISMATCH"),
            ("creative_status", input with { GoalContinuation = input.GoalContinuation with { CreativeStatus = "creative_failed" } }, "LINEAGE_MISMATCH"),
            ("production_status", input with { ProductionJob = input.ProductionJob with { Status = "running" } }, "LINEAGE_MISMATCH"),
            ("production_plan", input with { ProductionJob = input.ProductionJob with { PlanDigest = new string('f', 64) } }, "LINEAGE_MISMATCH"),
            ("package_plan", input with { ProductionPackage = input.ProductionPackage with { PlanDigest = new string('f', 64) } }, "LINEAGE_MISMATCH"),
            ("package_id", input with { ProductionPackage = input.ProductionPackage with { ProductionPackageId = "wrong" } }, "LINEAGE_MISMATCH"),
            ("unpassed_package", input with { ProductionPackage = input.ProductionPackage with { QualityOutcome = "FAIL" } }, "LINEAGE_MISMATCH"),
            ("profile", input with { ProductionPlan = input.ProductionPlan with { OutputProfileId = "invalid" } }, "LINEAGE_MISMATCH")
        };
        foreach (var (name, invalid, expected) in cases)
        {
            await LifecycleTests.Throws(expected, () => VerifyAsync(f, invalid, new NeverRunner()));
            Console.WriteLine($"C010B_NEGATIVE_LINEAGE={name}:PASS");
        }
        Check(!Directory.Exists(Path.Combine(f.Root, "receipts")), "bad lineage never writes a PASS receipt");
    }

    private static async Task RestartReuseAsync()
    {
        using var f = await Fixture.CreateAsync(true, true);
        var (_, input) = await ComposeAsync(f);
        var first = await VerifyAsync(f, input, new QaRunner(true));
        var firstBytes = await File.ReadAllBytesAsync(first.ReceiptPath);
        var restart = await VerifyAsync(f, input, new NeverRunner());
        Check(!first.Reused && restart.Reused, "actual store returns reused after restart");
        Check(first.ReceiptPath == restart.ReceiptPath && first.Receipt.QaInputDigest == restart.Receipt.QaInputDigest,
              "same digest-scoped receipt");
        var restartBytes = await File.ReadAllBytesAsync(restart.ReceiptPath);
        Check(first.Receipt.ReceiptDigest == restart.Receipt.ReceiptDigest &&
              firstBytes.SequenceEqual(restartBytes), "immutable content");
        Check(FinalQaIdentity.ReceiptDigest(first.Receipt with { VerifiedAt = DateTimeOffset.MinValue }) ==
              first.Receipt.ReceiptDigest, "timestamp does not enter receipt digest");
        Check(FinalQaIdentity.ReceiptDigest(first.Receipt with {
            ObservedMedia = first.Receipt.ObservedMedia with { FormatDurationUs = 9 }
        }) != first.Receipt.ReceiptDigest, "media facts do enter receipt digest");
    }

    private static async Task ReceiptTamperAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var (_, input) = await ComposeAsync(f);
        var first = await VerifyAsync(f, input, new QaRunner(false));
        var original = await File.ReadAllTextAsync(first.ReceiptPath);
        var baseNode = JsonNode.Parse(original)!.AsObject();
        var cases = new Dictionary<string, string>
        {
            ["malformed_json"] = "{",
            ["truncated_empty_object"] = "{}",
            ["unknown_field"] = Change(baseNode, o => o["unsupported"] = true),
            ["receipt_hash_tamper"] = Change(baseNode, o => o["receipt_digest"] = new string('a', 64)),
            ["outcome_tamper"] = Change(baseNode, o => o["outcome"] = "FAIL"),
            ["qa_input_digest_tamper"] = Change(baseNode, o => o["qa_input_digest"] = new string('f', 64)),
            ["unexpected_check"] = Change(baseNode, o => o["passed_check_ids"]![0] = "fabricated-check"),
            ["duplicate_json_property"] = original.Insert(original.IndexOf('{') + 1, "\"outcome\":\"PASS\",")
        };
        foreach (var (name, corrupted) in cases)
        {
            await File.WriteAllTextAsync(first.ReceiptPath, corrupted);
            await LifecycleTests.Throws("RECEIPT_CONFLICT", () => VerifyAsync(f, input, new NeverRunner()));
            Console.WriteLine($"C010B_NEGATIVE_RECEIPT={name}:PASS");
        }
        await File.WriteAllTextAsync(first.ReceiptPath, original);
        Check((await VerifyAsync(f, input, new NeverRunner())).Reused, "receipt restoration reusable");
    }

    private static string Change(JsonObject original, Action<JsonObject> action)
    {
        var copy = (JsonObject)original.DeepClone();
        action(copy);
        return copy.ToJsonString();
    }

    private static async Task DirectoryConflictAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var (_, input) = await ComposeAsync(f);
        var first = await VerifyAsync(f, input, new QaRunner(false));
        var dir = Path.GetDirectoryName(first.ReceiptPath)!;
        var extra = Path.Combine(dir, "unexpected");
        await File.WriteAllTextAsync(extra, "extra");
        await LifecycleTests.Throws("RECEIPT_CONFLICT", () => VerifyAsync(f, input, new NeverRunner()));
        File.Delete(extra);
        File.Delete(first.ReceiptPath);
        await LifecycleTests.Throws("RECEIPT_CONFLICT", () => VerifyAsync(f, input, new NeverRunner()));
        Check(Directory.Exists(dir), "immutable final directory never overwritten");
    }

    private static async Task DigestConflictAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var (_, input) = await ComposeAsync(f);
        var first = await VerifyAsync(f, input, new QaRunner(false));
        var changed = await VerifyAsync(f,
            input with { GoalContinuation = input.GoalContinuation with { ReturnSha256 = Fixture.ShaValue("changed-return") } },
            new QaRunner(false));
        Check(!changed.Reused && changed.Receipt.QaInputDigest != first.Receipt.QaInputDigest,
              "changed verified lineage gives distinct qa_input_digest");
        Check(changed.ReceiptPath != first.ReceiptPath && File.Exists(first.ReceiptPath),
              "old receipt preserved immutable under original digest");
        var repeat = await VerifyAsync(f, input, new NeverRunner());
        Check(repeat.Reused && repeat.ReceiptPath == first.ReceiptPath, "old exact lineage remains independently reusable");
        // A legitimate updated C005 frame plan must recompute all real C007/C008 digests.
        // This is NOT a fake digest mismatch: it is a fully consistent new lineage.
        var nextPlan = input.ProductionPlan with { Tasks = [
            input.ProductionPlan.Tasks[0] with { FrameCount = 48 }
        ] };
        var nextPlanDigest = FinalQaIdentity.Hash(JsonSerializer.SerializeToNode(nextPlan)!);
        var nextNarrationPlan = input.MasterInput.NarrationPlan.Plan with { ProductionPlanDigest = nextPlanDigest };
        var nextNarration = new NarrationPlanResponseRecord(
            nextNarrationPlan, NarrationPlanContract.ComputeDigest(nextNarrationPlan));
        var nextOverlayPlan = input.MasterInput.OverlayPlan.Plan with { ProductionPlanDigest = nextPlanDigest };
        var nextOverlay = new CaptionOverlayPlanResponseRecord(
            nextOverlayPlan, PostProductionMasterSourceVerifier.ComputeOverlayPlanDigest(nextOverlayPlan));
        var legitimate = input with {
            ProductionPlan = nextPlan,
            ProductionJob = input.ProductionJob with { PlanDigest = nextPlanDigest },
            ProductionPackage = input.ProductionPackage with { PlanDigest = nextPlanDigest },
            MasterInput = input.MasterInput with { NarrationPlan = nextNarration, OverlayPlan = nextOverlay }
        };
        var newPlanReceipt = await VerifyAsync(f, legitimate, new QaRunner(false));
        Check(!newPlanReceipt.Reused && newPlanReceipt.Receipt.QaInputDigest != first.Receipt.QaInputDigest,
            "valid frame-plan change creates new digest");
        Check(File.Exists(first.ReceiptPath) && File.Exists(newPlanReceipt.ReceiptPath),
            "old and new plan receipts both remain immutable");
        await LifecycleTests.Throws("LINEAGE_MISMATCH", () => VerifyAsync(f,
            input with { ProductionJob = input.ProductionJob with { PlanDigest = new string('0', 64) } },
            new NeverRunner()));
    }

    private static async Task ManifestDigestAsync()
    {
        foreach (var narr in new[] { true, false })
        {
            using var f = await Fixture.CreateAsync(narr, !narr);
            var (_, input) = await ComposeAsync(f);
            var first = await VerifyAsync(f, input, new QaRunner(narr));
            var originalMasterDigest = first.Receipt.MasterInputDigest;
            var sourceManifest = narr ? f.Input.NarrationArtifact!.ManifestPath : f.Input.OverlayArtifact!.ManifestPath!;
            var node = JsonNode.Parse(await File.ReadAllTextAsync(sourceManifest))!.AsObject();
            node["created_at"] = "2020-01-01T00:00:00+00:00";
            await File.WriteAllTextAsync(sourceManifest, node.ToJsonString());
            var mp = input.MasterArtifact!.ManifestPath;
            var masterNode = JsonNode.Parse(await File.ReadAllTextAsync(mp))!.AsObject();
            var sourceHash = Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(sourceManifest))).ToLowerInvariant();
            masterNode[narr ? "narration_manifest_sha256" : "c008b_manifest_sha256"] = sourceHash;
            await File.WriteAllTextAsync(mp, masterNode.ToJsonString());
            var second = await VerifyAsync(f, input, new QaRunner(narr));
            Check(second.Receipt.MasterInputDigest == originalMasterDigest, "C009 master input digest unchanged");
            Check(second.Receipt.QaInputDigest != first.Receipt.QaInputDigest, "C010 input digest binds manifest change");
            Check(second.ReceiptPath != first.ReceiptPath && File.Exists(first.ReceiptPath),
                  "manifest change does not overwrite previously-certified immutable receipt");
        }
    }

    private static async Task DecodeFailureAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var (_, input) = await ComposeAsync(f);
        var runner = new RejectingRunner(false, failDecode: true, failProbe: false);
        await LifecycleTests.Throws("DECODE_FAILED", () => VerifyAsync(f, input, runner));
        Check(runner.Probes == 1 && runner.Decodes == 1, "real C010A invoked separate probe and full decode");
        Check(!Directory.Exists(Path.Combine(f.Root, "receipts")), "decode failure cannot publish PASS receipt");
    }

    private static async Task ProbeFailureAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var (_, input) = await ComposeAsync(f);
        var runner = new RejectingRunner(false, failDecode: false, failProbe: true);
        await LifecycleTests.Throws("PROBE_FAILED", () => VerifyAsync(f, input, runner));
        Check(runner.Probes == 1 && runner.Decodes == 0, "probe failure cannot run decoder");
        Check(!Directory.Exists(Path.Combine(f.Root, "receipts")), "probe failure cannot publish PASS receipt");
    }

    private static async Task ArtifactTamperAsync()
    {
        using var f = await Fixture.CreateAsync(false, false);
        var (_, input) = await ComposeAsync(f);
        var first = await VerifyAsync(f, input, new QaRunner(false));
        var bytes = await File.ReadAllBytesAsync(f.Input.C004.FilePath);
        bytes[^1] ^= 0x5a;
        await File.WriteAllBytesAsync(f.Input.C004.FilePath, bytes);
        await LifecycleTests.Throws("ARTIFACT_INVALID", () => VerifyAsync(f, input, new NeverRunner()));
        Check(File.Exists(first.ReceiptPath), "tampered candidate does not rewrite original immutable receipt");
    }

    private static Task MediaPolicyAsync()
    {
        const string nominal = """
        {"streams":[{"index":0,"codec_type":"video","codec_name":"h264","pix_fmt":"yuv420p","width":832,"height":480,"r_frame_rate":"24/1","avg_frame_rate":"24/1","duration":"2.041667","nb_read_packets":"49","disposition":{"attached_pic":0}}],"format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2","duration":"2.041667","nb_streams":1},"chapters":[]}
        """;
        var baseFacts = FinalVideoQaMediaProbe.Parse(nominal);
        FinalVideoQaMediaProbe.Validate(baseFacts, "video.landscape.v1", false, 49, 2000);
        foreach (var altered in new[] {
            baseFacts with { Video = baseFacts.Video with { CodecName = "hevc" } },
            baseFacts with { Video = baseFacts.Video with { PixelFormat = "yuv444p" } },
        })
            ExpectPolicy("VIDEO_STREAM_INVALID", () => FinalVideoQaMediaProbe.Validate(altered, "video.landscape.v1", false, 49, 2000));
        foreach (var fps in new (long, long)[] {(24000,1001),(25,1),(30,1)})
            ExpectPolicy("OUTPUT_PROFILE_MISMATCH", () => FinalVideoQaMediaProbe.Validate(
                baseFacts with { Video = baseFacts.Video with { FpsNumerator = fps.Item1, FpsDenominator = fps.Item2 } },
                "video.landscape.v1", false, 49, 2000));
        ExpectPolicy("UNEXPECTED_STREAM", () => FinalVideoQaMediaProbe.Parse(
            nominal.Replace("\"chapters\":[]", "\"chapters\":[{\"id\":0}]", StringComparison.Ordinal)));
        ExpectPolicy("UNEXPECTED_STREAM", () => FinalVideoQaMediaProbe.Parse(
            nominal.Replace("\"attached_pic\":0", "\"attached_pic\":1", StringComparison.Ordinal)));
        ExpectPolicy("UNEXPECTED_STREAM", () => FinalVideoQaMediaProbe.Parse(
            nominal.Replace("\"codec_type\":\"video\"", "\"codec_type\":\"data\"", StringComparison.Ordinal)));
        var audio = new FinalQaAudioFacts(1, "aac", "LC", 48000, 1, "mono", 2000000);
        foreach (var bad in new[] { audio with { CodecName = "mp3" }, audio with { Profile = "HE-AAC" },
                    audio with { SampleRate = 44100 }, audio with { Channels = 2 }, audio with { DurationUs = 2_100_001 } })
            ExpectPolicy(bad.DurationUs != 2000000 ? "RUNTIME_MISMATCH" : "AUDIO_STREAM_INVALID",
                () => FinalVideoQaMediaProbe.Validate(baseFacts with { Audio = bad, StreamCount = 2 },
                    "video.landscape.v1", true, 49, 2000));
        ExpectPolicy("RUNTIME_MISMATCH", () => FinalVideoQaMediaProbe.Validate(
            baseFacts with { Video = baseFacts.Video with { DurationUs = 2_083_335 } },
            "video.landscape.v1", false, 49, 2000));
        return Task.CompletedTask;
    }

    private static void ExpectPolicy(string suffix, Action action)
    {
        try { action(); throw new InvalidOperationException("expected FINAL_QA_" + suffix); }
        catch (FinalVideoQaException e) when (e.Code == "FINAL_QA_" + suffix) { }
    }

    private static async Task RealWindowsAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new InvalidOperationException("UNVERIFIED: requires native Windows");
        foreach (var (narr, overlay) in new[] {(false,false), (true,false), (false,true), (true,true)})
        {
            using var f = await Fixture.CreateAsync(narr, overlay, real: true);
            var (_, input) = await ComposeAsync(f);
            var first = await VerifyAsync(f, input, new FixedMasterVideoProcessRunner());
            Check(first.Receipt.Outcome == "PASS" && !first.Reused, "actual Windows ffprobe+decode+receipt");
            var restart = await VerifyAsync(f, input, new NeverRunner());
            Check(restart.Reused && first.Receipt.ReceiptDigest == restart.Receipt.ReceiptDigest,
                  "actual Windows restart receipt reuse no decode");
            Console.WriteLine($"C010B_REAL_WINDOWS_PASS narration={narr} overlay={overlay}");
        }
    }
    private static async Task RealCorruptMediaAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new InvalidOperationException("UNVERIFIED: requires native Windows");
        using var f = await Fixture.CreateAsync(false, false, real: true);
        var bytes = await File.ReadAllBytesAsync(f.Input.C004.FilePath);
        var foundNonKeyframe = false;
        for (var offset = 0; offset + 8 <= bytes.Length;)
        {
            var length = checked((int)System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(offset, 4)));
            if (length < 8 || offset + length > bytes.Length)
                throw new InvalidOperationException("MP4 test fixture box layout changed");
            if (bytes.AsSpan(offset + 4, 4).SequenceEqual("mdat"u8))
            {
                for (var nal = offset + 8; nal + 5 <= offset + length;)
                {
                    var nalLength = checked((int)System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(nal, 4)));
                    if (nalLength <= 0 || nal + 4 + nalLength > offset + length)
                        throw new InvalidOperationException("MP4 synthetic sample NAL layout changed");
                    if ((bytes[nal + 4] & 31) == 1 && nalLength > 2)
                    {
                        bytes.AsSpan(nal + 5, nalLength - 1).Fill(0xff);
                        foundNonKeyframe = true;
                    }
                    nal += 4 + nalLength;
                }
                break;
            }
            offset += length;
        }
        Check(foundNonKeyframe, "must corrupt actual non-keyframe packets while preserving MP4 metadata");
        await File.WriteAllBytesAsync(f.Input.C004.FilePath, bytes);
        var modifiedHash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var manifest = JsonNode.Parse(await File.ReadAllTextAsync(f.Input.C004.ManifestPath))!.AsObject();
        manifest["final_sha256"] = modifiedHash;
        await File.WriteAllTextAsync(f.Input.C004.ManifestPath, manifest.ToJsonString());
        f.Input = f.Input with { C004 = f.Input.C004 with { Sha256 = modifiedHash, Bytes = bytes.LongLength } };
        var input = LifecycleTests.Input(f, null);
        // All C004 manifest/hash/bytes now agree, so failure must be caused by real decoding,
        // not simply rejected at the earlier SHA/lineage gate.
        await LifecycleTests.Throws("DECODE_FAILED",
            () => VerifyAsync(f, input, new FixedMasterVideoProcessRunner()));
        Check(!Directory.Exists(Path.Combine(f.Root, "receipts")),
            "header-valid but corrupted packets must not yield a PASS receipt");
    }

    private static async Task RealProcessBoundariesAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new InvalidOperationException("UNVERIFIED: requires native Windows");
        ProcessStartInfo SlowDecode()
        {
            var start = new ProcessStartInfo("ffmpeg.exe") { UseShellExecute = false, CreateNoWindow = true };
            foreach (var arg in new[] { "-hide_banner", "-loglevel", "error", "-nostdin",
                "-re", "-f", "lavfi", "-i", "color=s=16x16:r=24", "-t", "30", "-f", "null", "-" })
                start.ArgumentList.Add(arg);
            return start;
        }
        var runner = new FixedMasterVideoProcessRunner();
        var timed = await runner.RunAsync(SlowDecode(), TimeSpan.FromMilliseconds(150), CancellationToken.None);
        Check(timed.TimedOut, "real process timeout must report timed out");
        using var cancel = new CancellationTokenSource(TimeSpan.FromMilliseconds(150));
        try
        {
            await runner.RunAsync(SlowDecode(), TimeSpan.FromSeconds(30), cancel.Token);
            throw new InvalidOperationException("process cancellation was swallowed");
        }
        catch (OperationCanceledException) { }
    }

}

internal static class ReceiptAssertions
{
    internal static bool HasValidOutcome(this FinalArtifactReceiptV1 receipt)
        => receipt.SchemaVersion == "1.0" && receipt.QaProfileId == "final-video.qa.windows.v1"
           && receipt.ReceiptDigest.Length == 64 && receipt.QaInputDigest.Length == 64;
}

internal sealed class RejectingRunner(bool narration, bool failDecode, bool failProbe) : IMasterVideoProcessRunner
{
    private readonly QaRunner _delegate = new(narration);
    public int Probes { get; private set; }
    public int Decodes { get; private set; }

    public Task<MasterVideoProcessResult> RunAsync(ProcessStartInfo info, TimeSpan timeout, CancellationToken cancellationToken)
    {
        if (info.FileName == "ffprobe.exe")
        {
            Probes++;
            if (failProbe) return Task.FromResult(new MasterVideoProcessResult(2, false, "private-failure-details"));
        }
        if (info.FileName == "ffmpeg.exe")
        {
            Decodes++;
            if (failDecode) return Task.FromResult(new MasterVideoProcessResult(3, false, "private-decode-details"));
        }
        return _delegate.RunAsync(info, timeout, cancellationToken);
    }
}
