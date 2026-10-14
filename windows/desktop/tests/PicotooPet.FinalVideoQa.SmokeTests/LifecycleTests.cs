using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.FinalVideoQa.SmokeTests;

internal static class LifecycleTests
{
    internal static FinalVideoQaInputV1 Input(Fixture f, MasterVideoArtifact? master)
    {
        var p = f.Plan;
        var digest = FinalQaIdentity.Hash(JsonSerializer.SerializeToNode(p)!);
        var goal = new GoalVideoContinuationRecord("goal", Fixture.ShaValue("handoff"), Fixture.ShaValue("return"),
            "creative-job", p.CreativePackageId, p.CreativePackageDigest, "creative_ready", p.ProductionJobId, "production_ready");
        var job = new ProductionJobRecord(p.ProductionJobId, p.CreativePackageId, p.CreativePackageDigest,
            p.ProjectKey, p.ProductionProfile, digest, "production_ready", null, null, null, null, "idem",
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
        var package = new ProductionPackageRecord(f.Input.C004.ProductionPackageId, p.ProductionJobId,
            p.CreativePackageId, digest, f.Input.C004.ProductionPackageDigest, "unused",
            JsonSerializer.SerializeToElement(new { }), "PASS", DateTimeOffset.UtcNow);
        return new(goal, job, p, package, f.Input, master);
    }
    internal static FinalVideoQaService Service(Fixture f, IMasterVideoProcessRunner runner) =>
        new(runner, Path.Combine(f.Root, "finals"), Path.Combine(f.Root, "narration"), Path.Combine(f.Root, "overlays"),
            f.MasterRoot, Path.Combine(f.Root, "receipts"), TimeProvider.System);

    internal static async Task RunAsync(bool real)
    {
        foreach (var profile in real ? new[] { "video.landscape.v1", "video.vertical.v1", "video.square.v1" } : new[] { "video.landscape.v1" })
        foreach (var narration in new[] { false, true })
        foreach (var overlay in new[] { false, true })
        {
            using var f = await Fixture.CreateAsync(narration, overlay, profile: profile, real: real);
            var master = (await f.Service.ComposeAsync(f.Input)).Artifact;
            var input = Input(f, master);
            var runner = new QaRunner(narration);
            var service = Service(f, real ? new FixedMasterVideoProcessRunner() : runner);
            var first = await service.VerifyAsync(input);
            Assert(!first.Reused && first.Receipt.Outcome == "PASS", "fresh PASS");
            if (first.Receipt.PassedCheckIds is string[] exposed) exposed[0] = "caller-injected";
            Assert(FinalQaIdentity.Checks[0] == "lineage.v1", "returned receipt must not mutate global closed QA authority");
            Assert(first.Receipt.CandidateKind == (narration || overlay ? "c009_master_v1" : "c004_fallback_v1"), "strict candidate");
            var restart = await Service(f, new NeverRunner()).VerifyAsync(input);
            Assert(restart.Reused && restart.Receipt.ReceiptDigest == first.Receipt.ReceiptDigest, "restart skip process");
            var json = await File.ReadAllTextAsync(first.ReceiptPath);
            Assert(!json.Contains(f.Root, StringComparison.OrdinalIgnoreCase) && !json.Contains(Fixture.NarrationText, StringComparison.Ordinal)
                && !json.Contains(Fixture.OverlayText, StringComparison.Ordinal), "receipt privacy");
            Assert(FinalQaIdentity.ReceiptDigest(first.Receipt with { VerifiedAt = DateTimeOffset.MinValue }) == first.Receipt.ReceiptDigest, "timestamp excluded");
            Assert(FinalQaIdentity.ReceiptDigest(first.Receipt with { ObservedMedia = first.Receipt.ObservedMedia with { FormatDurationUs = 1 } }) != first.Receipt.ReceiptDigest, "media bound");
            if (master is not null)
            {
                var cased = await service.VerifyAsync(input with { MasterArtifact = master with { FilePath = master.FilePath.ToUpperInvariant(), ManifestPath = master.ManifestPath.ToUpperInvariant(), Reused = !master.Reused } });
                Assert(cased.Reused, "Windows equivalent paths and operational reused flag do not change identity");
                await Throws("MASTER_REQUIRED", () => service.VerifyAsync(input with { MasterArtifact = null }));
                await Throws("LINEAGE_MISMATCH", () => service.VerifyAsync(input with { MasterArtifact = master with { MasterInputDigest = new string('f', 64) } }));
            }
            await Throws("LINEAGE_MISMATCH", () => service.VerifyAsync(input with { ProductionJob = input.ProductionJob with { PlanDigest = new string('f', 64) } }));
            var changed = await service.VerifyAsync(input with { GoalContinuation = input.GoalContinuation with { ReturnSha256 = Fixture.ShaValue("return2") } });
            Assert(changed.ReceiptPath != first.ReceiptPath && File.Exists(first.ReceiptPath), "changed identity immutable");
            var node = JsonNode.Parse(json)!.AsObject(); node["unexpected"] = true;
            await File.WriteAllTextAsync(first.ReceiptPath, node.ToJsonString());
            await Throws("RECEIPT_CONFLICT", () => service.VerifyAsync(input));
            await File.WriteAllTextAsync(first.ReceiptPath, json);
            await File.AppendAllTextAsync(master?.FilePath ?? f.Input.C004.FilePath, "tamper");
            await Throws(null, () => service.VerifyAsync(input));
            Console.WriteLine($"PASS {(real ? "REAL_WINDOWS" : "CONTRACT")} {profile} narration={narration} overlay={overlay}");
        }
        using var failure = await Fixture.CreateAsync(false, false);
        await Throws("DECODE_FAILED", () => Service(failure, new QaRunner(false) { DecodeFailure = true }).VerifyAsync(Input(failure, null)));
        Assert(!Directory.Exists(Path.Combine(failure.Root, "receipts")), "no FAIL receipt");
        using var aba = await Fixture.CreateAsync(false, false);
        var attack = new ReplacementRunner(aba.Input.C004.FilePath);
        await Service(aba, attack).VerifyAsync(Input(aba, null));
        Assert(attack.Blocked, "candidate must stay read-locked during probe/decode, not merely be hashed before/after");
        if (real) await RealMedia.CorruptionAndProcessLimitsAsync();
    }
    internal static void Assert(bool ok, string message) { if (!ok) throw new InvalidOperationException(message); }
    internal static async Task Throws(string? suffix, Func<Task> action)
    {
        try { await action(); throw new InvalidOperationException("Expected QA rejection " + suffix); }
        catch (FinalVideoQaException e) when (suffix is null || e.Code == "FINAL_QA_" + suffix) { }
    }
}

internal sealed class NeverRunner : IMasterVideoProcessRunner
{
    public Task<MasterVideoProcessResult> RunAsync(ProcessStartInfo startInfo, TimeSpan timeout, CancellationToken cancellationToken)
        => throw new InvalidOperationException("Exact restart must not execute probe/decode.");
}
internal sealed class ReplacementRunner(string path) : IMasterVideoProcessRunner
{
    public bool Blocked { get; private set; }
    public async Task<MasterVideoProcessResult> RunAsync(ProcessStartInfo startInfo, TimeSpan timeout, CancellationToken cancellationToken)
    {
        var original = await File.ReadAllBytesAsync(path, cancellationToken);
        try
        {
            await File.WriteAllTextAsync(path, "replacement", cancellationToken);
            await File.WriteAllBytesAsync(path, original, cancellationToken);
        }
        catch (IOException) { Blocked = true; }
        return await new QaRunner(false).RunAsync(startInfo, timeout, cancellationToken);
    }
}
internal sealed class QaRunner(bool narration) : IMasterVideoProcessRunner
{
    public bool DecodeFailure { get; init; }
    public Task<MasterVideoProcessResult> RunAsync(ProcessStartInfo startInfo, TimeSpan timeout, CancellationToken cancellationToken)
    {
        LifecycleTests.Assert(!startInfo.UseShellExecute && startInfo.CreateNoWindow && startInfo.Arguments.Length == 0, "fixed process boundary");
        if (startInfo.FileName == "ffmpeg.exe")
        {
            LifecycleTests.Assert(startInfo.ArgumentList.Contains("-xerror") && startInfo.ArgumentList[^1] == "-"
                && !startInfo.ArgumentList.Contains("-vf"), "full decode only");
            return Task.FromResult(new MasterVideoProcessResult(DecodeFailure ? 1 : 0, false, ""));
        }
        LifecycleTests.Assert(startInfo.FileName == "ffprobe.exe" && startInfo.ArgumentList.Contains("-count_packets"), "fixed probe");
        var streams = new JsonArray(JsonNode.Parse("""
        {"index":0,"codec_type":"video","codec_name":"h264","pix_fmt":"yuv420p","width":832,"height":480,"r_frame_rate":"24/1","avg_frame_rate":"24/1","duration":"2.041667","nb_read_packets":"49","disposition":{"attached_pic":0}}
        """)!);
        if (narration) streams.Add(JsonNode.Parse("""
        {"index":1,"codec_type":"audio","codec_name":"aac","profile":"LC","sample_rate":"48000","channels":1,"channel_layout":"mono","duration":"2.000000","disposition":{"attached_pic":0}}
        """));
        var root = new JsonObject { ["streams"] = streams, ["chapters"] = new JsonArray(),
            ["format"] = new JsonObject { ["format_name"] = "mov,mp4,m4a,3gp,3g2,mj2", ["duration"] = "2.041667", ["nb_streams"] = streams.Count } };
        return Task.FromResult(new MasterVideoProcessResult(0, false, root.ToJsonString()));
    }
}
internal static class RealMedia
{
    internal static async Task GenerateAsync(string path, int width, int height)
    {
        var start = new ProcessStartInfo("ffmpeg.exe") { UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in new[] { "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi", "-i",
            $"color=c=blue:s={width}x{height}:r=24", "-frames:v", "49", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path }) start.ArgumentList.Add(arg);
        var result = await new FixedMasterVideoProcessRunner().RunAsync(start, TimeSpan.FromSeconds(30), CancellationToken.None);
        LifecycleTests.Assert(result.ExitCode == 0 && !result.TimedOut, "real fixture creation");
    }
    internal static async Task CorruptionAndProcessLimitsAsync()
    {
        using var f = await Fixture.CreateAsync(false, false, real: true);
        var corrupt = Path.Combine(f.Root, "corrupt.mp4");
        var bytes = await File.ReadAllBytesAsync(f.Input.C004.FilePath);
        var found = false;
        for (var offset = 0; offset + 8 <= bytes.Length;)
        {
            var length = checked((int)System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(offset, 4)));
            if (length < 8 || offset + length > bytes.Length) throw new InvalidOperationException("fixture MP4 box");
            if (bytes.AsSpan(offset + 4, 4).SequenceEqual("mdat"u8))
            {
                // Retain length prefixes and the first keyframe so ffprobe can still read structural facts.
                for (var nal = offset + 8; nal + 5 <= offset + length;)
                {
                    var size = checked((int)System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(nal, 4)));
                    if (size <= 0 || nal + 4 + size > offset + length) throw new InvalidOperationException("fixture NAL");
                    if ((bytes[nal + 4] & 31) == 1 && size > 2)
                    { bytes.AsSpan(nal + 5, size - 1).Fill(0xff); found = true; }
                    nal += 4 + size;
                }
                break;
            }
            offset += length;
        }
        LifecycleTests.Assert(found, "mdat corrupted while retaining valid header/moov");
        await File.WriteAllBytesAsync(corrupt, bytes);
        await LifecycleTests.Throws("DECODE_FAILED", () => new FinalVideoQaMediaProbe(new FixedMasterVideoProcessRunner()).VerifyAsync(corrupt,
            "video.landscape.v1", false, 49, 2000, CancellationToken.None));
        ProcessStartInfo SlowDecode()
        {
            var start = new ProcessStartInfo("ffmpeg.exe") { UseShellExecute = false, CreateNoWindow = true };
            foreach (var arg in new[] { "-hide_banner", "-loglevel", "error", "-nostdin", "-re", "-f", "lavfi", "-i", "color=s=16x16:r=24", "-t", "30", "-f", "null", "-" }) start.ArgumentList.Add(arg);
            return start;
        }
        var runner = new FixedMasterVideoProcessRunner();
        var timed = await runner.RunAsync(SlowDecode(), TimeSpan.FromMilliseconds(150), CancellationToken.None);
        LifecycleTests.Assert(timed.TimedOut, "real timeout terminates process tree");
        using var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(150));
        try { await runner.RunAsync(SlowDecode(), TimeSpan.FromSeconds(30), cancellation.Token); throw new InvalidOperationException("real cancellation ignored"); }
        catch (OperationCanceledException) { }
        Console.WriteLine("QA_REAL_CORRUPT_PACKET_DECODE_TIMEOUT_CANCEL=PASS");
    }
}
