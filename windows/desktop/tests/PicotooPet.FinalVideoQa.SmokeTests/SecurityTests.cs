using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Services;

namespace PicotooPet.FinalVideoQa.SmokeTests;

internal static class SecurityTests
{
    internal static async Task RunAsync()
    {
        using (var coreFixture = await Fixture.CreateAsync(false, false))
        {
            // Python ProductionPlan.model_validate + canonical json.dumps independently produced this vector.
            LifecycleTests.Assert(FinalQaIdentity.Hash(JsonSerializer.SerializeToNode(coreFixture.Plan)!) ==
                "59d3cf9fbebe367039ac2e8b90f33559d6449fdfb4a205e14fa12c0782d1fc11", "Core canonical ProductionPlan digest vector");
            var task = coreFixture.Plan.Tasks[0];
            var multi = coreFixture.Plan with { Tasks = [task with { FrameCount = 25, TargetDurationMs = 900 }, task with { Order = 2, FrameCount = 29, TargetDurationMs = 1100 }] };
            LifecycleTests.Assert(FinalVideoQaLineageValidator.ValidateTiming(multi) == 54, "multi-shot duration uses sum of frames, not target durations");
        }
        foreach (var mutate in new Action<Fixture>[]
        {
            f => File.AppendAllText(f.Input.C004.ManifestPath, "tamper"),
            f => File.AppendAllText(f.Input.NarrationArtifact!.ManifestPath, "tamper"),
            f => File.AppendAllText(f.Input.NarrationArtifact!.Segments[0].WavPath, "tamper"),
            f => File.AppendAllText(f.Input.OverlayArtifact!.ManifestPath!, "tamper"),
            f => File.AppendAllText(f.Input.OverlayArtifact!.FilePath, "tamper"),
        })
        {
            using var f = await Fixture.CreateAsync(true, true);
            var master = (await f.Service.ComposeAsync(f.Input)).Artifact;
            mutate(f);
            await LifecycleTests.Throws(null, () => LifecycleTests.Service(f, new NeverRunner()).VerifyAsync(LifecycleTests.Input(f, master)));
            LifecycleTests.Assert(!Directory.Exists(Path.Combine(f.Root, "receipts")), "upstream tamper creates no receipt");
        }
        foreach (var extra in new[] { true, false })
        {
            using var f = await Fixture.CreateAsync(true, false);
            var master = (await f.Service.ComposeAsync(f.Input)).Artifact!;
            if (extra) await File.WriteAllTextAsync(Path.Combine(Path.GetDirectoryName(master.FilePath)!, "extra"), "bad");
            else File.Delete(master.ManifestPath);
            await LifecycleTests.Throws("ARTIFACT_INVALID", () => LifecycleTests.Service(f, new NeverRunner()).VerifyAsync(LifecycleTests.Input(f, master)));
        }
        using (var f = await Fixture.CreateAsync(false, false))
        {
            var input = LifecycleTests.Input(f, null);
            var service = LifecycleTests.Service(f, new QaRunner(false));
            using var stale = await Fixture.CreateAsync(true, false);
            var staleMaster = (await stale.Service.ComposeAsync(stale.Input)).Artifact;
            await LifecycleTests.Throws("INPUT_INVALID", () => service.VerifyAsync(input with { MasterArtifact = staleMaster }));
            await LifecycleTests.Throws("CAPTION_PROFILE_UNSUPPORTED", () => service.VerifyAsync(input with
            { MasterInput = f.Input with { OverlayPlan = f.Input.OverlayPlan with { Plan = f.Input.OverlayPlan.Plan with { CaptionsRequired = true } } } }));
            await LifecycleTests.Throws("INPUT_INVALID", () => service.VerifyAsync(input with
            { MasterInput = f.Input with { NarrationPlan = f.Input.NarrationPlan with { NarrationPlanDigest = new string('f', 64) } } }));
            await LifecycleTests.Throws("INPUT_INVALID", () => service.VerifyAsync(input with
            { MasterInput = f.Input with { OverlayPlan = f.Input.OverlayPlan with { CaptionOverlayPlanDigest = new string('f', 64) } } }));
            await LifecycleTests.Throws("LINEAGE_MISMATCH", () => service.VerifyAsync(input with { ProductionPackage = input.ProductionPackage with { PlanDigest = new string('f', 64) } }));
            await LifecycleTests.Throws("LINEAGE_MISMATCH", () => service.VerifyAsync(input with { ProductionPlan = input.ProductionPlan with { ProjectKey = "different" } }));
            var first = await service.VerifyAsync(input);
            var saved = await File.ReadAllTextAsync(first.ReceiptPath);
            foreach (var bad in new[] { "{}", saved.Replace("\"outcome\":\"PASS\"", "\"outcome\":\"FAIL\"", StringComparison.Ordinal),
                saved.Replace("\"schema_version\":\"1.0\"", "\"schema_version\":\"1.0\",\"schema_version\":\"1.0\"", StringComparison.Ordinal) })
            {
                await File.WriteAllTextAsync(first.ReceiptPath, bad);
                await LifecycleTests.Throws("RECEIPT_CONFLICT", () => service.VerifyAsync(input));
            }
            await File.WriteAllTextAsync(first.ReceiptPath, saved);
            var directory = Path.GetDirectoryName(first.ReceiptPath)!;
            await File.WriteAllTextAsync(Path.Combine(directory, "extra"), "bad");
            await LifecycleTests.Throws("RECEIPT_CONFLICT", () => service.VerifyAsync(input));
            File.Delete(Path.Combine(directory, "extra")); File.Delete(first.ReceiptPath);
            await LifecycleTests.Throws("RECEIPT_CONFLICT", () => service.VerifyAsync(input));
            LifecycleTests.Assert(Directory.Exists(directory), "partial committed directory not overwritten");
            var outside = Path.Combine(f.Root, "outside.mp4"); File.Copy(f.Input.C004.FilePath, outside);
            await LifecycleTests.Throws("ARTIFACT_INVALID", () => service.VerifyAsync(input with { MasterInput = f.Input with { C004 = f.Input.C004 with { FilePath = outside } } }));
        }
        // Upstream manifest timestamps are outside MasterInputDigest but inside QA provenance identity.
        foreach (var narration in new[] { false, true })
        {
            using var f = await Fixture.CreateAsync(narration, !narration);
            var firstMaster = (await f.Service.ComposeAsync(f.Input)).Artifact!;
            var input = LifecycleTests.Input(f, firstMaster);
            var validator = new FinalVideoQaLineageValidator(Path.Combine(f.Root, "finals"), Path.Combine(f.Root, "narration"), Path.Combine(f.Root, "overlays"), f.MasterRoot);
            var before = await validator.VerifyAsync(input, CancellationToken.None);
            var sourceManifest = narration ? f.Input.NarrationArtifact!.ManifestPath : f.Input.OverlayArtifact!.ManifestPath!;
            var node = JsonNode.Parse(await File.ReadAllTextAsync(sourceManifest))!.AsObject();
            node["created_at"] = "2020-01-01T00:00:00+00:00";
            await File.WriteAllTextAsync(sourceManifest, node.ToJsonString());
            // Test fixture updates the exact C009 manifest's hash binding, never product code.
            var masterManifest = JsonNode.Parse(await File.ReadAllTextAsync(firstMaster.ManifestPath))!.AsObject();
            masterManifest[narration ? "narration_manifest_sha256" : "c008b_manifest_sha256"] = await ProductionLocalEnvironment.Sha256FileAsync(sourceManifest, CancellationToken.None);
            await File.WriteAllTextAsync(firstMaster.ManifestPath, masterManifest.ToJsonString());
            var after = await validator.VerifyAsync(input, CancellationToken.None);
            LifecycleTests.Assert(before.Template.MasterInputDigest == after.Template.MasterInputDigest
                && before.Template.QaInputDigest != after.Template.QaInputDigest, "upstream manifest hashes independently bind QA digest");
        }
        foreach (var error in new[] { "PROBE_FAILED", "TIMEOUT", "PROBE_UNAVAILABLE" })
        {
            using var f = await Fixture.CreateAsync(false, false);
            await LifecycleTests.Throws(error, () => LifecycleTests.Service(f, new FailureRunner(error)).VerifyAsync(LifecycleTests.Input(f, null)));
            LifecycleTests.Assert(!Directory.Exists(Path.Combine(f.Root, "receipts")), "process failure writes no PASS");
        }
        using (var f = await Fixture.CreateAsync(false, false))
            await LifecycleTests.Throws("PROBE_FAILED", () => LifecycleTests.Service(f, new FailureRunner("IO_FAILURE")).VerifyAsync(LifecycleTests.Input(f, null)));
        using (var f = await Fixture.CreateAsync(false, false))
        {
            using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
            try { await LifecycleTests.Service(f, new NeverRunner()).VerifyAsync(LifecycleTests.Input(f, null), cancellation.Token); throw new InvalidOperationException("cancel swallowed"); }
            catch (OperationCanceledException) { }
            // Real directory junction rejection; cleanup removes only the junction, not its target.
            var finals = Path.Combine(f.Root, "finals"); var moved = Path.Combine(f.Root, "real-finals");
            Directory.Move(finals, moved);
            var start = new ProcessStartInfo("cmd.exe") { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
            foreach (var arg in new[] { "/c", "mklink", "/J", finals, moved }) start.ArgumentList.Add(arg);
            using var process = Process.Start(start)!; await process.WaitForExitAsync();
            LifecycleTests.Assert(process.ExitCode == 0, "junction fixture");
            try { await LifecycleTests.Throws("ARTIFACT_INVALID", () => LifecycleTests.Service(f, new NeverRunner()).VerifyAsync(LifecycleTests.Input(f, null))); }
            finally { Directory.Delete(finals); Directory.Move(moved, finals); }
        }
        Console.WriteLine("QA_LINEAGE_SECURITY_RESTART=PASS");
    }
}
internal sealed class FailureRunner(string code) : IMasterVideoProcessRunner
{
    public Task<MasterVideoProcessResult> RunAsync(ProcessStartInfo startInfo, TimeSpan timeout, CancellationToken cancellationToken)
    {
        if (code == "PROBE_UNAVAILABLE") throw new MasterVideoComposerException(MasterVideoComposerException.FfmpegUnavailable);
        if (code == "IO_FAILURE") throw new IOException("private absolute path and process diagnostics");
        return Task.FromResult(new MasterVideoProcessResult(code == "PROBE_FAILED" ? 1 : 0, code == "TIMEOUT", "private stderr/path must not surface"));
    }
}
