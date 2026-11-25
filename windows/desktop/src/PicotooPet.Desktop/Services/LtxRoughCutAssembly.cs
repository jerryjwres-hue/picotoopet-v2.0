using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.Desktop.Services;

/// <summary>Local CPU-only LTX rough cut. No legacy Production Package or visual approval.</summary>
internal static class LtxRoughCutAssembly
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true
    };

    internal static async Task AssembleAsync(ControlCenterSession session,
        IReadOnlyList<ProductionJobRecord> jobs, string batchIdentity, CancellationToken ct)
    {
        if (jobs.Count != 3 || jobs.Any(job => !LtxProductionExecutor.IsCandidateSettled(job))
            || ProductionSubmissionJournal.Hash(string.Join("\n", jobs.Select(job =>
                job.ProductionJobId + ":" + job.PlanDigest))) != batchIdentity)
            throw new InvalidDataException("LTX_ROUGH_CUT_BATCH_INVALID");

        // 01. Only persisted Core receipts may select files. Reuse the paired
        //     client and the existing byte/decode verification for each clip.
        using var core = session.CreateWorkerChallengePreflightClient();
        var outputRoot = ProductionLocalEnvironment.ResolveComfyOutputRoot();
        var runner = new FixedMasterVideoProcessRunner();
        var probe = new FinalVideoQaMediaProbe(runner);
        var pins = new List<FileStream>();
        var paths = new List<string>();
        var receipts = new List<JsonElement>();
        var seenHashes = new HashSet<string>(StringComparer.Ordinal);
        try
        {
            foreach (var job in jobs)
            {
                ct.ThrowIfCancellationRequested();
                var plan = await core.GetLtxPlanAsync(job.ProductionJobId, ct).ConfigureAwait(false);
                var reference = LtxProductionExecutor.ValidatePlan(job, plan, allowSettled: true);
                var receipt = await core.GetLtxCandidateAsync(job.ProductionJobId, ct).ConfigureAwait(false);
                FinalVideoQaMediaProbe.RejectDuplicates(receipt);
                string Text(string key) => receipt.GetProperty(key).GetString() ?? "";
                var generation = Text("generation_id");
                var video = Text("video_asset_id");
                var relative = Text("output_relpath");
                var sha = Text("output_sha256");
                var bytes = receipt.GetProperty("output_bytes").GetInt64();
                if (Text("schema_version") != "production.ltx.candidate.v1"
                    || Text("production_job_id") != job.ProductionJobId || Text("plan_digest") != job.PlanDigest
                    || Text("production_task_id") != reference.ProductionTaskId
                    || Text("job_status") != "NeedsHuman" || Text("lane") != "local"
                    || Text("mime_type") != "video/mp4" || !receipt.GetProperty("decode_verified").GetBoolean()
                    || !receipt.GetProperty("review_required").GetBoolean() || receipt.GetProperty("mac_bytes_verified").GetBoolean()
                    || !CanonicalId(generation) || !CanonicalId(video) || !CanonicalId(Text("production_attempt_id"))
                    || relative != $"PicotooPet/ltx/{job.ProductionJobId}/{reference.ProductionTaskId}/{generation}-video-{video}.mp4"
                    || !seenHashes.Add(sha))
                    throw new InvalidDataException("LTX_ROUGH_CUT_RECEIPT_INVALID");
                var path = ProductionLocalEnvironment.ResolveUnderRoot(outputRoot, relative, true);
                ProductionLocalEnvironment.AssertNoLinkEscape(outputRoot, path);
                if (!ProductionLocalEnvironment.IsOrdinaryFile(path))
                    throw new InvalidDataException("LTX_ROUGH_CUT_SOURCE_INVALID");
                // 02. Keep every source pinned through encode and QA; do not
                //     trust file paths or the Windows-reported digest alone.
                var pin = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read,
                    128 * 1024, FileOptions.Asynchronous);
                pins.Add(pin);
                var measured = await probe.VerifyLtxCandidateAsync(path, sha, bytes, ct).ConfigureAwait(false);
                if (measured != new LtxCandidateMediaFacts(receipt.GetProperty("width").GetInt32(),
                    receipt.GetProperty("height").GetInt32(), receipt.GetProperty("frame_count").GetInt32(),
                    receipt.GetProperty("fps").GetInt32(), receipt.GetProperty("duration_ms").GetInt32()))
                    throw new InvalidDataException("LTX_ROUGH_CUT_MEDIA_MISMATCH");
                paths.Add(path);
                receipts.Add(receipt.Clone());
            }

            // 03. Use the existing managed final root, a separate candidate
            //     namespace, and immutable identity including all three receipts.
            var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "PicotooPet", "FinalVideos", "LtxCandidates");
            if (!MasterVideoPathPolicy.IsSafeLocalFullyQualified(root))
                throw new InvalidDataException("LTX_ROUGH_CUT_ROOT_INVALID");
            ProductionLocalEnvironment.AssertNoLinkEscape(root, root);
            Directory.CreateDirectory(root);
            ProductionLocalEnvironment.AssertNoLinkEscape(root, root);
            var identity = Convert.ToHexStringLower(SHA256.HashData(CanonicalJson.Serialize(
                JsonSerializer.SerializeToNode(receipts)!)));
            var destination = ProductionLocalEnvironment.ResolveUnderRoot(root, identity, false);
            var manifest = new JsonObject
            {
                ["schema_version"] = "picotoo.ltx.rough_cut.v1",
                ["batch_identity"] = batchIdentity,
                ["candidate_identity"] = identity,
                ["creative_package_id"] = jobs[0].CreativePackageId,
                ["creative_package_digest"] = jobs[0].CreativePackageDigest,
                ["sources"] = JsonSerializer.SerializeToNode(receipts),
                ["file_name"] = "rough-cut.mp4",
                ["width"] = 720, ["height"] = 1280, ["fps"] = 24,
                ["frame_count"] = 288, ["duration_ms"] = 12000,
                ["audio_included"] = false, ["visual_review"] = "UNREVIEWED",
                ["formal_delivery"] = false
            };
            if (Directory.Exists(destination))
            {
                await VerifyExistingAsync(root, destination, manifest, probe, ct).ConfigureAwait(false);
                return;
            }
            var staging = Path.Combine(root, "." + identity + "." + Guid.NewGuid().ToString("N") + ".partial");
            Directory.CreateDirectory(staging);
            try
            {
                var output = Path.Combine(staging, "rough-cut.mp4");
                var start = BuildEncode(paths, output);
                var result = await runner.RunAsync(start, TimeSpan.FromMinutes(10), ct).ConfigureAwait(false);
                if (result.ExitCode != 0 || result.TimedOut || result.CleanupIncomplete
                    || !ProductionLocalEnvironment.IsOrdinaryFile(output))
                    throw new InvalidDataException("LTX_ROUGH_CUT_ENCODE_FAILED");
                await probe.VerifyLtxRoughCutAsync(output, ct).ConfigureAwait(false);
                manifest["sha256"] = await ProductionLocalEnvironment.Sha256FileAsync(output, ct).ConfigureAwait(false);
                manifest["bytes"] = new FileInfo(output).Length;
                await File.WriteAllTextAsync(Path.Combine(staging, "manifest.json"), manifest.ToJsonString(JsonOptions), ct)
                    .ConfigureAwait(false);
                ct.ThrowIfCancellationRequested();
                // 04. Publish video and receipt together. Existing output is
                //     never overwritten, and incomplete staging is not deliverable.
                Directory.Move(staging, destination);
            }
            finally { if (Directory.Exists(staging)) Directory.Delete(staging, true); }
        }
        finally
        {
            foreach (var pin in pins) await pin.DisposeAsync().ConfigureAwait(false);
        }
    }

    internal static ProcessStartInfo BuildEncode(IReadOnlyList<string> sources, string output)
    {
        if (sources.Count != 3 || sources.Any(path => !MasterVideoPathPolicy.IsSafeLocalFullyQualified(path))
            || !MasterVideoPathPolicy.IsSafeLocalFullyQualified(output))
            throw new InvalidDataException("LTX_ROUGH_CUT_PATH_INVALID");
        var start = new ProcessStartInfo("ffmpeg.exe") { UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in new[] { "-hide_banner", "-loglevel", "error", "-nostdin", "-xerror", "-n",
            "-filter_complex_threads", "1" }) start.ArgumentList.Add(arg);
        foreach (var path in sources)
            foreach (var arg in new[] { "-protocol_whitelist", "file", "-i", path }) start.ArgumentList.Add(arg);
        // 05. Preserve native aspect ratio via pad, normalize cadence and only
        //     the allowed one-frame rounding discrepancy. No vendor audio yet.
        var filter = string.Concat(Enumerable.Range(0, 3).Select(i =>
            $"[{i}:v:0]scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2," +
            "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,tpad=stop_mode=clone:stop=1," +
            $"trim=end_frame=96,setpts=N/(24*TB)[v{i}];"))
            + "[v0][v1][v2]concat=n=3:v=1:a=0[outv]";
        foreach (var arg in new[] { "-filter_complex", filter, "-map", "[outv]", "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24", "-frames:v", "288",
            "-movflags", "+faststart", "-f", "mp4", output }) start.ArgumentList.Add(arg);
        return start;
    }

    private static async Task VerifyExistingAsync(string root, string directory, JsonObject expected,
        FinalVideoQaMediaProbe probe, CancellationToken ct)
    {
        var output = Path.Combine(directory, "rough-cut.mp4");
        var manifestPath = Path.Combine(directory, "manifest.json");
        ProductionLocalEnvironment.AssertNoLinkEscape(root, output);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, manifestPath);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(output)
            || !ProductionLocalEnvironment.IsOrdinaryFile(manifestPath)
            || new FileInfo(manifestPath).Length is <= 0 or > 64 * 1024)
            throw new InvalidDataException("LTX_ROUGH_CUT_CONFLICT");
        await using var pin = new FileStream(output, FileMode.Open, FileAccess.Read, FileShare.Read,
            128 * 1024, FileOptions.Asynchronous);
        expected["sha256"] = Convert.ToHexStringLower(await SHA256.HashDataAsync(pin, ct).ConfigureAwait(false));
        expected["bytes"] = pin.Length;
        using var parsed = JsonDocument.Parse(await File.ReadAllTextAsync(manifestPath, ct).ConfigureAwait(false));
        FinalVideoQaMediaProbe.RejectDuplicates(parsed.RootElement);
        if (!CanonicalJson.Serialize(expected).AsSpan().SequenceEqual(
            CanonicalJson.Serialize(JsonNode.Parse(parsed.RootElement.GetRawText())!)))
            throw new InvalidDataException("LTX_ROUGH_CUT_CONFLICT");
        await probe.VerifyLtxRoughCutAsync(output, ct).ConfigureAwait(false);
    }

    private static bool CanonicalId(string value) =>
        Guid.TryParseExact(value, "D", out var id) && id != Guid.Empty && id.ToString("D") == value;
}
