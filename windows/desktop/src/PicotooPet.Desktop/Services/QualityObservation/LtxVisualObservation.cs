using System.Diagnostics;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.QualityObservation;

namespace PicotooPet.Desktop.Services.QualityObservation;

/// <summary>Reuse the existing observer over exact native LTX candidates; advisory only.</summary>
internal static class LtxVisualObservation
{
    internal static async Task<VisualObservationResult> ObserveAsync(
        IReadOnlyList<ProductionJobRecord> jobs, IReadOnlyList<VisualObservationShot> shots,
        bool localVlm, CancellationToken ct)
    {
        using var budget = CancellationTokenSource.CreateLinkedTokenSource(ct);
        budget.CancelAfter(TimeSpan.FromMinutes(8));
        var token = budget.Token;
        var pins = new List<VisualEvidenceFileLease>();
        try
        {
            if (jobs.Count != 3 || shots.Count != 3)
                return VisualReviewObservation.Unverified("需要三个已核验候选镜头。");
            var root = ProductionLocalEnvironment.ResolveComfyOutputRoot();
            var input = new VisualObservationInput("visual_review.ltx.input.v1",
                jobs[0].ProductionJobId, shots);
            // 01. Pin the exact original MP4 bytes during the complete review.
            var probe = new FinalVideoQaMediaProbe(new FixedMasterVideoProcessRunner());
            foreach (var shot in shots)
            {
                var path = ProductionLocalEnvironment.ResolveUnderRoot(root, shot.RelativePath, true);
                ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(root)!, path);
                pins.Add(new VisualEvidenceFileLease(path));
                var facts = await probe.VerifyLtxCandidateAsync(path, shot.Sha256, shot.Bytes, token).ConfigureAwait(false);
                if (facts.FrameCount != shot.ExpectedFrames || facts.DurationMs != shot.ExpectedDurationMs)
                    throw new InvalidDataException("LTX_VISUAL_SOURCE_CHANGED");
            }
            string? endpoint = null, model = null;
            if (localVlm)
            {
                // 02. Deliberate local configuration only; existing observer
                //     checks private literal IPv4, installed model and response.
                var config = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "PicotooPetV2", "MediaWorker", "v1", "ltx-visual-review.json");
                using var pin = new VisualEvidenceFileLease(config);
                if (new FileInfo(config).Length is <= 0 or > 4096)
                    throw new InvalidDataException("LTX_VISUAL_MODEL_NOT_CONFIGURED");
                using var doc = JsonDocument.Parse(await File.ReadAllBytesAsync(config, token).ConfigureAwait(false));
                var value = doc.RootElement;
                FinalVideoQaMediaProbe.RejectDuplicates(value);
                if (value.ValueKind != JsonValueKind.Object || value.EnumerateObject().Count() != 2)
                    throw new InvalidDataException("LTX_VISUAL_MODEL_NOT_CONFIGURED");
                endpoint = value.GetProperty("endpoint").GetString();
                model = value.GetProperty("model").GetString();
                _ = ReviewPolicy.ValidateLocalEndpoint(endpoint, model, true);
                pin.Recheck();
            }
            var run = new DeployedVisualObservationRuntime().CreateEvidenceRun();
            var manifest = Path.Combine(run, "input.json");
            await File.WriteAllBytesAsync(manifest, JsonSerializer.SerializeToUtf8Bytes(input, VisualReviewObservation.Json), token)
                .ConfigureAwait(false);
            await File.WriteAllBytesAsync(Path.Combine(run, "source-provenance.json"),
                JsonSerializer.SerializeToUtf8Bytes(new
                {
                    schema_version = "visual_observation.ltx.provenance.v1",
                    authority = "NONE", human_accept = "NOT_GRANTED",
                    creative_package_digest = jobs[0].CreativePackageDigest,
                    candidates = jobs.Select(job => new { job_id = job.ProductionJobId, plan_digest = job.PlanDigest }),
                    frame_transfer_consented = localVlm
                }), token).ConfigureAwait(false);
            var output = Path.Combine(run, "evidence");
            var runner = new FixedMasterVideoProcessRunner();
            async Task<string> Media(string executable, IEnumerable<string> args, TimeSpan timeout)
            {
                var start = new ProcessStartInfo(executable) { UseShellExecute = false };
                foreach (var arg in args) start.ArgumentList.Add(arg);
                var result = await runner.RunAsync(start, timeout, token).ConfigureAwait(false);
                if (result.ExitCode != 0 || result.TimedOut || result.CleanupIncomplete)
                    throw new InvalidOperationException("LTX_VISUAL_MEDIA_FAILED");
                return result.Stdout;
            }
            // 03. Exact existing observer and report verifier, no duplicate
            //     visual classifier, automatic ACCEPT or production mutation.
            var report = await ReviewRunner.ExecuteAsync(new ReviewOptions(manifest, root, output,
                FixedMasterVideoProcessRunner.Ffprobe, FixedMasterVideoProcessRunner.Ffmpeg,
                endpoint, model, localVlm), Media).ConfigureAwait(false);
            token.ThrowIfCancellationRequested();
            foreach (var pin in pins) pin.Recheck();
            if (report.Status == "UNVERIFIED")
                return VisualReviewObservation.Unverified("辅助审片未完成；没有视觉通过结论。");
            return await VisualReviewObservation.ReadReportAsync(input, output, localVlm, token).ConfigureAwait(false);
        }
        catch (Exception) when (!ct.IsCancellationRequested)
        {
            return VisualReviewObservation.Unverified("视觉观察未完成：检查本地媒体、FFmpeg 或已配置的 Ollama；未改变生产状态。");
        }
        finally { foreach (var pin in pins) pin.Dispose(); }
    }
}
