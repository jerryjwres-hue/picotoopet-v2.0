using System.IO;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Services;

namespace PicotooPet.FinalVideoQa.SmokeTests;

/// <summary>
/// G006-owned independent acceptance: the master is genuinely produced by C009A +
/// FixedFfmpegMasterVideoComposer (real C009B), never synthesized from JSON.
/// Each of the 17 mutations is checked against BOTH the exact C009A catalog and
/// C010A VerifyAsync, then restored byte-for-byte and revalidated.
/// </summary>
internal static class C010BRealMasterManifestNegatives
{
    private static readonly string[] HashFields =
    [
        "production_package_digest",
        "production_plan_digest",
        "creative_package_digest",
        "c004_source_sha256",
        "caption_overlay_plan_digest",
        "narration_plan_digest",
        "selected_visual_sha256",
        "master_input_digest",
        "output_sha256",
        "narration_manifest_sha256",
        "c008b_manifest_sha256",
    ];

    internal static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows())
            throw new InvalidOperationException("UNVERIFIED_NATIVE_WINDOWS_REQUIRED");

        // BOTH optional manifests are non-null in this full-real-combination fixture.
        using var fixture = await Fixture.CreateAsync(true, true, real: true);
        var master = (await fixture.Service.ComposeAsync(fixture.Input)).Artifact
            ?? throw new InvalidOperationException("C009B real master missing");
        Check(fixture.Composer.Calls == 1, "C009B real composer must execute");
        var qaInput = LifecycleTests.Input(fixture, master);
        var verifier = new FinalVideoQaLineageValidator(
            Path.Combine(fixture.Root, "finals"),
            Path.Combine(fixture.Root, "narration"),
            Path.Combine(fixture.Root, "overlays"),
            fixture.MasterRoot);
        var verified = await verifier.VerifyAsync(qaInput, CancellationToken.None);
        var identity = IdentityFromVerifiedTemplate(verified.Template);
        var expected = new MasterArtifactExpectation(identity, master.MasterInputDigest);
        Check(MasterInputIdentity.Compute(identity) == master.MasterInputDigest,
            "expectation must be current real C009A identity, never a made-up digest");

        var catalog = new PostProductionMasterArtifactCatalog(fixture.MasterRoot);
        var checkedMaster = await catalog.FindVerifiedExactAsync(expected)
            ?? throw new InvalidOperationException("real C009A catalog must return master");
        Check(checkedMaster.Sha256 == master.Sha256 && checkedMaster.Bytes == master.Bytes,
            "real C009A master hash and bytes must match");

        // Obtain an ACTUAL native QA PASS and immutable receipt first. The
        // tampered master must NOT reuse this receipt, even across restart.
        var result = await LifecycleTests.Service(fixture, new FixedMasterVideoProcessRunner())
            .VerifyAsync(qaInput);
        Check(!result.Reused && result.Receipt.Outcome == "PASS",
            "genuine master must pass real C010A ffprobe/full decode");
        var originalReceipt = await File.ReadAllBytesAsync(result.ReceiptPath);
        var originalManifest = await File.ReadAllBytesAsync(master.ManifestPath);
        var originalVideo = await File.ReadAllBytesAsync(master.FilePath);
        var realNode = JsonNode.Parse(System.Text.Encoding.UTF8.GetString(originalManifest))?.AsObject()
            ?? throw new InvalidOperationException("genuine MasterManifest must parse");
        Check(realNode["narration_manifest_sha256"] is not null &&
              realNode["c008b_manifest_sha256"] is not null, "both actual sources required");

        // Exactly 14 value tamper cases plus 3 structural/content cases.
        var valueCases = new (string Id, string Field, string Mode)[]
        {
            ("production-job-mismatch", "production_job_id", "suffix"),
            ("production-package-mismatch", "production_package_digest", "sha"),
            ("production-plan-mismatch", "production_plan_digest", "sha"),
            ("creative-package-mismatch", "creative_package_digest", "sha"),
            ("source-c004-mismatch", "c004_source_sha256", "sha"),
            ("caption-plan-mismatch", "caption_overlay_plan_digest", "sha"),
            ("narration-plan-mismatch", "narration_plan_digest", "sha"),
            ("selected-visual-mismatch", "selected_visual_sha256", "sha"),
            ("master-input-digest-mismatch", "master_input_digest", "sha"),
            ("master-output-sha-mismatch", "output_sha256", "sha"),
            ("master-output-bytes-mismatch", "output_bytes", "increment"),
            ("master-audio-flag-mismatch", "has_audio", "flip"),
            ("narration-manifest-mismatch", "narration_manifest_sha256", "sha"),
            ("overlay-manifest-mismatch", "c008b_manifest_sha256", "sha"),
        };

        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var (id, field, mode) in valueCases)
        {
            Check(ids.Add(id), "no duplicate negative ids");
            var modified = (JsonObject)realNode.DeepClone();
            if (mode == "suffix")
                modified[field] = modified[field]!.GetValue<string>() + "-wrong";
            else if (mode == "sha")
            {
                Check(HashFields.Contains(field, StringComparer.Ordinal), "only actual digest field mutated");
                var prior = modified[field]!.GetValue<string>();
                Check(prior.Length == 64, "real master digest must be 64 hex");
                modified[field] = (prior[0] == '0' ? "1" : "0") + prior[1..];
            }
            else if (mode == "increment")
                modified[field] = modified[field]!.GetValue<long>() + 1;
            else if (mode == "flip")
                modified[field] = !modified[field]!.GetValue<bool>();
            else throw new InvalidOperationException("unexpected test mutation mode");
            await ExecuteMutationAsync(id, fixture, master, qaInput, catalog, expected,
                result.ReceiptPath, originalReceipt, originalManifest, originalVideo,
                () => File.WriteAllTextAsync(master.ManifestPath, modified.ToJsonString()));
        }

        var extra = Path.Combine(Path.GetDirectoryName(master.FilePath)!, "c010b-unexpected-entry.txt");
        await ExecuteMutationAsync("unexpected-directory-entry", fixture, master, qaInput, catalog, expected,
            result.ReceiptPath, originalReceipt, originalManifest, originalVideo,
            () => File.WriteAllTextAsync(extra, "fixture-only"),
            extra);
        await ExecuteMutationAsync("missing-master-manifest", fixture, master, qaInput, catalog, expected,
            result.ReceiptPath, originalReceipt, originalManifest, originalVideo,
            () =>
            {
                File.Delete(master.ManifestPath);
                return Task.CompletedTask;
            });
        await ExecuteMutationAsync("master-media-byte-tamper", fixture, master, qaInput, catalog, expected,
            result.ReceiptPath, originalReceipt, originalManifest, originalVideo,
            () =>
            {
                var modified = (byte[])originalVideo.Clone();
                modified[^1] ^= 0x5a; // Same-size content change, not a simple length mismatch
                return File.WriteAllBytesAsync(master.FilePath, modified);
            });
        Console.WriteLine("C010B_REAL_MASTER_MANIFEST_SUMMARY=passed=17;failed=0;source=C009B_REAL");
    }

    private static MasterIdentityFacts IdentityFromVerifiedTemplate(FinalArtifactReceiptV1 t) =>
        new(t.ProductionJobId, t.ProductionPackageId, t.ProductionPackageDigest,
            t.ProductionPlanDigest, t.CreativePackageId, t.CreativePackageDigest,
            t.TargetRuntimeMs, t.OutputProfileId, t.NarrationRequired,
            t.NarrationPlanDigest, t.NarrationManifestSha256, t.NarrationSegments,
            t.OverlaysRequired, t.CaptionOverlayPlanDigest,
            t.SelectedVisualKind, t.SelectedVisualSha256, t.SelectedVisualBytes,
            t.C004SourceSha256, t.C004SourceBytes,
            t.C008bArtifactSha256, t.C008bArtifactBytes, t.C008bManifestSha256);

    private static async Task ExecuteMutationAsync(
        string id, Fixture f, MasterVideoArtifact master, FinalVideoQaInputV1 input,
        PostProductionMasterArtifactCatalog catalog, MasterArtifactExpectation expected,
        string receiptPath, byte[] originalReceipt, byte[] manifest, byte[] video,
        Func<Task> mutate, string? extraFile = null)
    {
        try
        {
            await mutate();
            // 1. Actual digest-scoped C009A catalog must reject and emit its own bounded code.
            try
            {
                await catalog.FindVerifiedExactAsync(expected);
                throw new InvalidOperationException(id + ": catalog incorrectly reused corrupted master");
            }
            catch (MasterCompositionException e) when
                (e.Code == MasterCompositionException.ArtifactConflict) { }

            // 2. Actual C010A service must recheck upstream even when a PASS receipt exists.
            await LifecycleTests.Throws("ARTIFACT_INVALID",
                () => LifecycleTests.Service(f, new NeverRunner()).VerifyAsync(input));
            var afterFailureReceipt = await File.ReadAllBytesAsync(receiptPath);
            Check(originalReceipt.SequenceEqual(afterFailureReceipt),
                id + ": existing PASS receipt must stay immutable");
            Check(Directory.EnumerateFiles(Path.Combine(f.Root, "receipts"), "final-artifact-receipt.json",
                    SearchOption.AllDirectories).Count() == 1, id + ": failure must not add PASS receipt");
        }
        finally
        {
            if (extraFile is not null && File.Exists(extraFile)) File.Delete(extraFile);
            await File.WriteAllBytesAsync(master.ManifestPath, manifest);
            await File.WriteAllBytesAsync(master.FilePath, video);
        }

        var recovered = await catalog.FindVerifiedExactAsync(expected);
        Check(recovered is not null && recovered.Sha256 == master.Sha256,
            id + ": catalog must recover exact source after byte-for-byte restoration");
        var reused = await LifecycleTests.Service(f, new NeverRunner()).VerifyAsync(input);
        Check(reused.Reused && reused.ReceiptPath == receiptPath,
            id + ": previous immutable receipt must be reusable after restoration");
        Console.WriteLine("C010B_MASTER_MANIFEST_NEGATIVE_PASS " + id);
    }

    private static void Check(bool condition, string description) =>
        LifecycleTests.Assert(condition, description);
}
