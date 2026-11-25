using System.Diagnostics;
using System.IO;
using PicotooPet.Desktop.Services;

namespace PicotooPet.FinalVideoQa.SmokeTests;

internal static class LtxRoughCutRealTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "picotoo-ltx-rough-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            // 01. Three short synthetic clips, including actual observed native
            //     704x1280 geometry and all allowed frame rounding boundaries.
            var runner = new FixedMasterVideoProcessRunner();
            var probe = new FinalVideoQaMediaProbe(runner);
            var paths = new List<string>();
            foreach (var (width, height, count, color) in new[]
                { (704, 1280, 95, "red"), (720, 1280, 96, "green"), (576, 1024, 97, "blue") })
            {
                var path = Path.Combine(root, $"source-{count}.mp4");
                var start = new ProcessStartInfo("ffmpeg.exe") { UseShellExecute = false };
                foreach (var arg in new[] { "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                    "-f", "lavfi", "-i", $"color=c={color}:s={width}x{height}:r=24",
                    "-frames:v", count.ToString(System.Globalization.CultureInfo.InvariantCulture),
                    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "2", path })
                    start.ArgumentList.Add(arg);
                var made = await runner.RunAsync(start, TimeSpan.FromMinutes(2), CancellationToken.None);
                if (made.ExitCode != 0 || made.TimedOut || made.CleanupIncomplete)
                    throw new InvalidOperationException("LTX_REAL_FIXTURE_FAILED");
                var hash = await ProductionLocalEnvironment.Sha256FileAsync(path, CancellationToken.None);
                var measured = await probe.VerifyLtxCandidateAsync(path, hash, new FileInfo(path).Length, CancellationToken.None);
                if (measured.Width != width || measured.Height != height || measured.FrameCount != count)
                    throw new InvalidOperationException("LTX_REAL_FIXTURE_MEDIA_MISMATCH");
                paths.Add(path);
            }
            // 02. Real encode and full decode of exactly the production command.
            var output = Path.Combine(root, "rough-cut.mp4");
            var result = await runner.RunAsync(LtxRoughCutAssembly.BuildEncode(paths, output),
                TimeSpan.FromMinutes(5), CancellationToken.None);
            if (result.ExitCode != 0 || result.TimedOut || result.CleanupIncomplete)
                throw new InvalidOperationException("LTX_REAL_ROUGH_CUT_ENCODE_FAILED");
            await probe.VerifyLtxRoughCutAsync(output, CancellationToken.None);
            Console.WriteLine("LTX_REAL_ROUGH_CUT_95_96_97_720P_288_FRAMES=PASS; GPU_POST=0");
            // 03. Run the same observer on actual native portrait MP4 clips.
            //     Synthetic media cannot establish identity/visual quality.
            var shots = new List<PicotooPet.QualityObservation.InputShot>();
            for (var index = 0; index < paths.Count; index++)
            {
                var path = paths[index];
                var sha = await ProductionLocalEnvironment.Sha256FileAsync(path, CancellationToken.None);
                var facts = await probe.VerifyLtxCandidateAsync(path, sha, new FileInfo(path).Length, CancellationToken.None);
                shots.Add(new(index + 1, "shot-" + index, "task-" + index, Path.GetFileName(path),
                    sha, new FileInfo(path).Length, facts.FrameCount, facts.DurationMs, "synthetic test"));
            }
            var input = Path.Combine(root, "input.json");
            var manifest = new PicotooPet.QualityObservation.InputManifest(
                "visual_review.ltx.input.v1", Guid.NewGuid().ToString("D"), shots);
            await File.WriteAllTextAsync(input, System.Text.Json.JsonSerializer.Serialize(
                manifest, PicotooPet.QualityObservation.ReviewPolicy.Json));
            var evidence = root + "-evidence";
            try
            {
                var report = await PicotooPet.QualityObservation.ReviewRunner.ExecuteAsync(
                    new(input, root, evidence, "ffprobe.exe", "ffmpeg.exe", null, null, false));
                if (report.Status != "ADVISORY_REVIEW" || report.ModelState != "NOT_REQUESTED"
                    || report.Shots.Count != 3 || report.Shots.Any(shot => shot.Samples.Count != 3))
                    throw new InvalidOperationException("LTX_REAL_OBSERVATION_FAILED");
                var visual = await PicotooPet.Desktop.Services.QualityObservation.VisualReviewObservation.ReadReportAsync(
                    new("visual_review.ltx.input.v1", manifest.JobId, shots.Select(shot =>
                        new PicotooPet.Desktop.Services.QualityObservation.VisualObservationShot(
                            shot.Order, shot.ShotId, shot.TaskId, shot.RelativePath, shot.Sha256, shot.Bytes,
                            shot.ExpectedFrames, shot.ExpectedDurationMs, shot.Action)).ToArray()),
                    evidence, false, CancellationToken.None);
                if (visual.Verdict != PicotooPet.Desktop.Services.QualityObservation.VisualObservationVerdict.Review)
                    throw new InvalidOperationException("LTX_REAL_OBSERVATION_REPORT_FAILED");
                Console.WriteLine("LTX_REAL_VISUAL_OBSERVATION_9_FRAMES=PASS; MODEL=NOT_REQUESTED; VISUAL_ACCEPT=UNVERIFIED");
            }
            finally { if (Directory.Exists(evidence)) Directory.Delete(evidence, true); }
        }
        finally { Directory.Delete(root, true); }
    }
}
