using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>验证完整 lineage 后，以不可变 digest 目录提交 C009 主片产物。</summary>
public sealed class PostProductionMasterCompositorService
{
    private static readonly JsonSerializerOptions ManifestJson = new()
    {
        WriteIndented = true,
    };
    private readonly IMasterVideoComposer _composer;
    private readonly PostProductionMasterSourceVerifier _verifier;
    private readonly PostProductionMasterArtifactCatalog _catalog;
    private readonly TimeProvider _timeProvider;

    public PostProductionMasterCompositorService(
        IMasterVideoComposer composer,
        string finalVideoRoot,
        string narrationRoot,
        string overlayRoot,
        string masterRoot,
        TimeProvider timeProvider)
    {
        _composer = composer ?? throw new ArgumentNullException(nameof(composer));
        _verifier = new PostProductionMasterSourceVerifier(finalVideoRoot, narrationRoot, overlayRoot);
        _catalog = new PostProductionMasterArtifactCatalog(masterRoot);
        _timeProvider = timeProvider ?? throw new ArgumentNullException(nameof(timeProvider));
    }

    public static PostProductionMasterCompositorService Create(IMasterVideoComposer composer)
    {
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(localAppData))
        {
            throw new DirectoryNotFoundException("LOCAL_APP_DATA_NOT_FOUND");
        }
        return new PostProductionMasterCompositorService(
            composer,
            Path.Combine(localAppData, "PicotooPet", "FinalVideos"),
            Path.Combine(localAppData, "PicotooPet", "Narration", "v1"),
            Path.Combine(localAppData, "PicotooPet", "PostProduction", "TextOverlay", "v1"),
            Path.Combine(localAppData, "PicotooPet", "PostProduction", "Master", "v1"),
            TimeProvider.System);
    }

    public async Task<MasterCompositionResult> ComposeAsync(
        MasterCompositionInputV1 input,
        CancellationToken cancellationToken = default)
    {
        if (input is null)
        {
            throw new MasterCompositionException(MasterCompositionException.InputInvalid);
        }
        ValidatePlans(input);
        ValidateLineage(input);

        // All upstream identity/path/bytes checks happen before any C009 directory is created.
        var c004 = await _verifier.VerifyFinalVideoAsync(input.C004, cancellationToken).ConfigureAwait(false);
        var narrationPlan = input.NarrationPlan.Plan;
        var overlayPlan = input.OverlayPlan.Plan;
        if (!narrationPlan.NarrationRequired && !overlayPlan.OverlaysRequired)
        {
            return new MasterCompositionResult(Required: false, C004Fallback: input.C004, Artifact: null);
        }

        VerifiedMasterVisual selectedVisual = c004.Visual;
        VerifiedOverlaySource? overlay = null;
        if (overlayPlan.OverlaysRequired)
        {
            if (input.OverlayArtifact is null || input.OverlayArtifact.Passthrough)
            {
                throw new MasterCompositionException(MasterCompositionException.VisualInvalid);
            }
            overlay = await _verifier.VerifyOverlayAsync(
                input.OverlayArtifact, input.C004, input.OverlayPlan, cancellationToken).ConfigureAwait(false);
            selectedVisual = overlay.Visual;
        }

        VerifiedNarrationSource? narration = null;
        if (narrationPlan.NarrationRequired)
        {
            if (input.NarrationArtifact is null)
            {
                throw new MasterCompositionException(MasterCompositionException.NarrationInvalid);
            }
            narration = await _verifier.VerifyNarrationAsync(
                input.NarrationArtifact, input.NarrationPlan, cancellationToken).ConfigureAwait(false);
        }

        var identity = new MasterIdentityFacts(
            input.C004.ProductionJobId,
            input.C004.ProductionPackageId,
            input.C004.ProductionPackageDigest,
            narrationPlan.ProductionPlanDigest,
            narrationPlan.CreativePackageId,
            narrationPlan.CreativePackageDigest,
            narrationPlan.TargetRuntimeMs,
            overlayPlan.OutputProfileId,
            narrationPlan.NarrationRequired,
            input.NarrationPlan.NarrationPlanDigest,
            narration?.ManifestSha256,
            narration?.IdentitySegments ?? [],
            overlayPlan.OverlaysRequired,
            input.OverlayPlan.CaptionOverlayPlanDigest,
            selectedVisual.SourceKind,
            selectedVisual.Sha256,
            selectedVisual.Bytes,
            c004.Visual.Sha256,
            c004.Visual.Bytes,
            overlay?.Visual.Sha256,
            overlay?.Visual.Bytes,
            overlay?.ManifestSha256);
        var digest = MasterInputIdentity.Compute(identity);
        var expectation = new MasterArtifactExpectation(identity, digest);
        var existing = await _catalog.FindVerifiedExactAsync(expectation, cancellationToken).ConfigureAwait(false);
        if (existing is not null)
        {
            return new MasterCompositionResult(Required: true, C004Fallback: null, Artifact: existing);
        }

        var root = _catalog.Root;
        var temporaryDirectory = string.Empty;
        try
        {
            Directory.CreateDirectory(root);
            ProductionLocalEnvironment.AssertNoLinkEscape(root, root);
            var jobDirectory = MasterPathPolicy.JobDirectory(root, identity.ProductionJobId);
            Directory.CreateDirectory(jobDirectory);
            ProductionLocalEnvironment.AssertNoLinkEscape(root, jobDirectory);
            var finalDirectory = MasterPathPolicy.ArtifactDirectory(jobDirectory, digest);
            if (Directory.Exists(finalDirectory) || File.Exists(finalDirectory))
            {
                throw new MasterCompositionException(MasterCompositionException.ArtifactConflict);
            }
            temporaryDirectory = ProductionLocalEnvironment.ResolveUnderRoot(
                jobDirectory, $".{digest}.{Guid.NewGuid():N}.tmp", requireExistingFile: false);
            Directory.CreateDirectory(temporaryDirectory);
            ProductionLocalEnvironment.AssertNoLinkEscape(root, temporaryDirectory);
            var temporaryOutput = Path.Combine(temporaryDirectory, PostProductionMasterArtifactCatalog.OutputFileName);

            try
            {
                await _composer.ComposeAsync(
                    new MasterVideoCompositionRequest(
                        selectedVisual,
                        narration?.Segments ?? [],
                        narrationPlan.TargetRuntimeMs,
                        temporaryOutput),
                    cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw new MasterCompositionException(MasterCompositionException.ComposerFailed, exception);
            }

            VerifyTemporaryOutput(root, temporaryOutput);
            var outputBytes = new FileInfo(temporaryOutput).Length;
            var outputSha = await ProductionLocalEnvironment.Sha256FileAsync(temporaryOutput, cancellationToken)
                .ConfigureAwait(false);
            var manifest = BuildManifest(identity, digest, outputSha, outputBytes);
            var manifestPath = Path.Combine(
                temporaryDirectory, PostProductionMasterArtifactCatalog.ManifestFileName);
            await File.WriteAllTextAsync(
                manifestPath,
                JsonSerializer.Serialize(manifest, ManifestJson),
                new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                cancellationToken).ConfigureAwait(false);
            VerifyTemporaryManifest(root, manifestPath);
            if (Directory.EnumerateFileSystemEntries(temporaryDirectory).Count() != 2)
            {
                throw new MasterCompositionException(MasterCompositionException.OutputInvalid);
            }

            try
            {
                Directory.Move(temporaryDirectory, finalDirectory);
                temporaryDirectory = string.Empty;
            }
            catch (IOException exception)
            {
                throw new MasterCompositionException(MasterCompositionException.ArtifactConflict, exception);
            }

            var committed = await _catalog.FindVerifiedExactAsync(expectation, cancellationToken).ConfigureAwait(false)
                ?? throw new MasterCompositionException(MasterCompositionException.ArtifactConflict);
            return new MasterCompositionResult(
                Required: true,
                C004Fallback: null,
                committed with { Reused = false });
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (MasterCompositionException)
        {
            throw;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException
            or ArgumentException or NotSupportedException or JsonException or InvalidOperationException)
        {
            throw new MasterCompositionException(MasterCompositionException.ArtifactConflict, exception);
        }
        finally
        {
            TryDeleteTemporaryDirectory(temporaryDirectory);
        }
    }

    private static void ValidatePlans(MasterCompositionInputV1 input)
    {
        try
        {
            NarrationPlanContract.Validate(input.NarrationPlan);
            CaptionOverlayPlanParser.Validate(input.OverlayPlan);
            if (PostProductionMasterSourceVerifier.ComputeOverlayPlanDigest(input.OverlayPlan.Plan)
                != input.OverlayPlan.CaptionOverlayPlanDigest)
            {
                throw new MasterCompositionException(MasterCompositionException.InputInvalid);
            }
        }
        catch (MasterCompositionException)
        {
            throw;
        }
        catch (Exception exception) when (exception is NarrationPlanContractException or TextOverlayException
            or ArgumentException or InvalidOperationException or JsonException or NullReferenceException)
        {
            throw new MasterCompositionException(MasterCompositionException.InputInvalid, exception);
        }
    }

    private static void ValidateLineage(MasterCompositionInputV1 input)
    {
        var narration = input.NarrationPlan.Plan;
        var overlay = input.OverlayPlan.Plan;
        if (input.C004.ProductionJobId != narration.ProductionJobId
            || input.C004.ProductionJobId != overlay.ProductionJobId
            || narration.CreativePackageId != overlay.CreativePackageId
            || narration.CreativePackageDigest != overlay.CreativePackageDigest
            || narration.ProductionPlanDigest != overlay.ProductionPlanDigest
            || narration.TargetRuntimeMs != overlay.TargetRuntimeMs)
        {
            throw new MasterCompositionException(MasterCompositionException.LineageMismatch);
        }
        if (overlay.CaptionsRequired || overlay.Captions.Count != 0
            || !CaptionOverlayConstants.OutputProfileIds.Contains(overlay.OutputProfileId))
        {
            throw new MasterCompositionException(MasterCompositionException.InputInvalid);
        }
        if (overlay.OverlaysRequired
            && (input.OverlayArtifact is null
                || input.OverlayArtifact.ProductionJobId != input.C004.ProductionJobId
                || input.OverlayArtifact.SourceFinalSha256 != input.C004.Sha256
                || input.OverlayArtifact.CaptionOverlayPlanDigest != input.OverlayPlan.CaptionOverlayPlanDigest
                || input.OverlayArtifact.OutputProfileId != overlay.OutputProfileId
                || input.OverlayArtifact.Passthrough))
        {
            throw new MasterCompositionException(MasterCompositionException.LineageMismatch);
        }
        if (narration.NarrationRequired && input.NarrationArtifact is null)
        {
            throw new MasterCompositionException(MasterCompositionException.NarrationInvalid);
        }
    }

    private MasterManifest BuildManifest(
        MasterIdentityFacts identity,
        string digest,
        string outputSha,
        long outputBytes) =>
        new(
            PostProductionMasterProfiles.SchemaVersion,
            PostProductionMasterProfiles.MasterProfileId,
            PostProductionMasterProfiles.VideoProfileId,
            PostProductionMasterProfiles.AudioProfileId,
            identity.ProductionJobId,
            identity.ProductionPackageId,
            identity.ProductionPackageDigest,
            identity.CreativePackageId,
            identity.CreativePackageDigest,
            identity.ProductionPlanDigest,
            identity.TargetRuntimeMs,
            identity.OutputProfileId,
            identity.NarrationRequired,
            identity.NarrationPlanDigest,
            identity.NarrationManifestSha256,
            identity.NarrationSegments.Select(static segment => new MasterManifestNarrationSegment(
                segment.SegmentId,
                segment.BeatId,
                segment.Order,
                segment.TextSha256,
                segment.StartMs,
                segment.EndMs,
                segment.WavSha256,
                segment.WavBytes,
                segment.ActualDurationMs,
                segment.SampleFrames,
                segment.SampleRate,
                segment.Channels,
                segment.BitsPerSample)).ToArray(),
            identity.OverlaysRequired,
            identity.CaptionOverlayPlanDigest,
            identity.C004SourceSha256,
            identity.C004SourceBytes,
            identity.SelectedVisualKind,
            identity.SelectedVisualSha256,
            identity.SelectedVisualBytes,
            identity.C008BArtifactSha256,
            identity.C008BArtifactBytes,
            identity.C008BManifestSha256,
            PostProductionMasterArtifactCatalog.OutputFileName,
            outputSha,
            outputBytes,
            identity.NarrationRequired,
            digest,
            _timeProvider.GetUtcNow());

    private static void VerifyTemporaryOutput(string root, string outputPath)
    {
        ProductionLocalEnvironment.AssertNoLinkEscape(root, outputPath);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(outputPath)
            || new FileInfo(outputPath).Length <= 0)
        {
            throw new MasterCompositionException(MasterCompositionException.OutputInvalid);
        }
    }

    private static void VerifyTemporaryManifest(string root, string manifestPath)
    {
        ProductionLocalEnvironment.AssertNoLinkEscape(root, manifestPath);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(manifestPath)
            || new FileInfo(manifestPath).Length <= 0)
        {
            throw new MasterCompositionException(MasterCompositionException.ArtifactConflict);
        }
    }

    private static void TryDeleteTemporaryDirectory(string path)
    {
        if (string.IsNullOrEmpty(path))
        {
            return;
        }
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch (IOException)
        {
            // Generated C009 work directories are uncommitted and may be ignored on restart.
        }
        catch (UnauthorizedAccessException)
        {
            // Same policy: never mutate upstream or a committed digest directory during cleanup.
        }
    }
}
