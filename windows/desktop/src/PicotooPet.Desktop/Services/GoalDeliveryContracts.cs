using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Security.Cryptography;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>C009C 交付投影仅存在于 Windows 内存，绝不替代 Core 或 C009A manifest。</summary>
public enum GoalDeliveryPhase
{
    Idle,
    VisualPreparing,
    VisualReadyPostProcessing,
    PostProcessing,
    MasteredReady,
    FallbackReady,
    QualityChecking, // C010 reserved; C009C never emits.
    DeliveryReady,   // C010 reserved; C009C never emits.
    QaFailed,        // C010 reserved; C009C never emits.
    Failed,
}

public enum GoalDeliveryKind
{
    C004Fallback,
    C009Master,
}

public sealed record GoalDeliverySnapshot(
    string? GoalId,
    string? ProductionJobId,
    GoalDeliveryPhase Phase,
    string? StatusText,
    bool CanOpen)
{
    public static GoalDeliverySnapshot Idle(string? goalId, string? jobId) =>
        new(goalId, jobId, GoalDeliveryPhase.Idle, null, false);
}

/// <summary>单一已验证候选。所有绝对路径都只能来自 C004/C009A 受控本地产物。</summary>
public sealed record GoalDeliveryCandidateV1(
    GoalDeliveryKind Kind,
    string ProductionJobId,
    string ProductionPackageId,
    string ProductionPackageDigest,
    string ProductionPlanDigest,
    long TargetRuntimeMs,
    string OutputProfileId,
    bool NarrationRequired,
    string NarrationPlanDigest,
    bool OverlaysRequired,
    string CaptionOverlayPlanDigest,
    string FilePath,
    string ManifestPath,
    string FileSha256,
    long FileBytes,
    string ManifestSha256,
    long ManifestBytes,
    string? MasterInputDigest,
    string? ApprovalReceiptDigest = null);

public interface IPostProductionDeliveryObserver
{
    GoalDeliverySnapshot Observe(string? goalId, GoalVideoContinuationRecord? continuation);
    Task<bool> OpenCurrentAsync(CancellationToken cancellationToken = default);
}

/// <summary>最终候选只能由 Core 冻结的两个 requirement bit 决定，不依赖文件是否存在。</summary>
public static class GoalDeliveryPolicy
{
    public static bool IsPostProductionRequired(bool narrationRequired, bool overlaysRequired) =>
        narrationRequired || overlaysRequired;

    public static bool IsAllowed(GoalDeliveryKind kind, bool narrationRequired, bool overlaysRequired) =>
        IsPostProductionRequired(narrationRequired, overlaysRequired)
            ? kind == GoalDeliveryKind.C009Master
            : kind == GoalDeliveryKind.C004Fallback;

    public static bool IsPreQaOpenable(GoalDeliveryPhase phase, GoalDeliveryKind kind) =>
        phase switch
        {
            GoalDeliveryPhase.MasteredReady => kind == GoalDeliveryKind.C009Master,
            GoalDeliveryPhase.FallbackReady => kind == GoalDeliveryKind.C004Fallback,
            _ => false,
        };
}

/// <summary>
/// 读取已有的 C004/C009A 产物进行 read-only 身份校验；不读取任意用户路径、不启动 FFmpeg。
/// </summary>
public sealed class GoalDeliveryCandidateVerifier
{
    private const int MaximumManifestBytes = 512 * 1024;
    private readonly string _finalVideoRoot;
    private readonly string _masterRoot;

    public GoalDeliveryCandidateVerifier(string finalVideoRoot, string masterRoot)
    {
        _finalVideoRoot = RequireFullRoot(finalVideoRoot);
        _masterRoot = RequireFullRoot(masterRoot);
    }

    public static GoalDeliveryCandidateVerifier CreateDefault()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(local))
        {
            throw new DirectoryNotFoundException("LOCAL_APP_DATA_NOT_FOUND");
        }
        return new GoalDeliveryCandidateVerifier(
            Path.Combine(local, "PicotooPet", "FinalVideos"),
            Path.Combine(local, "PicotooPet", "PostProduction", "Master", "v1"));
    }

    public async Task<GoalDeliveryCandidateV1> FromFallbackAsync(
        FinalVideoArtifact artifact,
        NarrationPlanResponseRecord narration,
        CaptionOverlayPlanResponseRecord overlay,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(artifact);
        ArgumentNullException.ThrowIfNull(narration);
        ArgumentNullException.ThrowIfNull(overlay);
        if (GoalDeliveryPolicy.IsPostProductionRequired(
            narration.Plan.NarrationRequired, overlay.Plan.OverlaysRequired))
        {
            throw Invalid();
        }
        var candidate = new GoalDeliveryCandidateV1(
            GoalDeliveryKind.C004Fallback,
            artifact.ProductionJobId, artifact.ProductionPackageId, artifact.ProductionPackageDigest,
            narration.Plan.ProductionPlanDigest, narration.Plan.TargetRuntimeMs,
            overlay.Plan.OutputProfileId, false, narration.NarrationPlanDigest,
            false, overlay.CaptionOverlayPlanDigest,
            artifact.FilePath, artifact.ManifestPath, artifact.Sha256, artifact.Bytes,
            string.Empty, 0, null);
        return await CaptureManifestAsync(candidate, cancellationToken).ConfigureAwait(false);
    }

    public async Task<GoalDeliveryCandidateV1> FromMasterAsync(
        MasterVideoArtifact artifact,
        NarrationPlanResponseRecord narration,
        CaptionOverlayPlanResponseRecord overlay,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(artifact);
        ArgumentNullException.ThrowIfNull(narration);
        ArgumentNullException.ThrowIfNull(overlay);
        if (!GoalDeliveryPolicy.IsPostProductionRequired(
            narration.Plan.NarrationRequired, overlay.Plan.OverlaysRequired)
            || artifact.ProductionJobId != narration.Plan.ProductionJobId
            || artifact.ProductionPlanDigest != narration.Plan.ProductionPlanDigest
            || artifact.OutputProfileId != overlay.Plan.OutputProfileId
            || artifact.TargetRuntimeMs != narration.Plan.TargetRuntimeMs
            || artifact.HasAudio != narration.Plan.NarrationRequired)
        {
            throw Invalid();
        }
        var candidate = new GoalDeliveryCandidateV1(
            GoalDeliveryKind.C009Master,
            artifact.ProductionJobId, artifact.ProductionPackageId, artifact.ProductionPackageDigest,
            artifact.ProductionPlanDigest, artifact.TargetRuntimeMs, artifact.OutputProfileId,
            narration.Plan.NarrationRequired, narration.NarrationPlanDigest,
            overlay.Plan.OverlaysRequired, overlay.CaptionOverlayPlanDigest,
            artifact.FilePath, artifact.ManifestPath, artifact.Sha256, artifact.Bytes,
            string.Empty, 0, artifact.MasterInputDigest);
        return await CaptureManifestAsync(candidate, cancellationToken).ConfigureAwait(false);
    }

    public async Task<bool> VerifyAtOpenAsync(
        GoalDeliveryCandidateV1 candidate,
        CancellationToken cancellationToken)
    {
        try
        {
            if (!GoalDeliveryPolicy.IsAllowed(
                candidate.Kind, candidate.NarrationRequired, candidate.OverlaysRequired)
                || !HasSha(candidate.FileSha256) || !HasSha(candidate.ManifestSha256)
                || candidate.FileBytes <= 0 || candidate.ManifestBytes is <= 0 or > MaximumManifestBytes
                || candidate.ApprovalReceiptDigest is not null)
            {
                return false;
            }
            return await VerifyFilesAsync(candidate, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception) when (IsRejectedFileError(exception))
        {
            return false;
        }
    }

    private async Task<GoalDeliveryCandidateV1> CaptureManifestAsync(
        GoalDeliveryCandidateV1 candidate,
        CancellationToken cancellationToken)
    {
        if (!GoalDeliveryPolicy.IsAllowed(
            candidate.Kind, candidate.NarrationRequired, candidate.OverlaysRequired))
        {
            throw Invalid();
        }
        ValidatePath(candidate);
        var info = new FileInfo(candidate.ManifestPath);
        if (info.Length is <= 0 or > MaximumManifestBytes
            || !ProductionLocalEnvironment.IsOrdinaryFile(candidate.ManifestPath))
        {
            throw Invalid();
        }
        var sha = await ProductionLocalEnvironment.Sha256FileAsync(candidate.ManifestPath, cancellationToken)
            .ConfigureAwait(false);
        var captured = candidate with { ManifestBytes = info.Length, ManifestSha256 = sha };
        if (!await VerifyFilesAsync(captured, cancellationToken).ConfigureAwait(false))
        {
            throw Invalid();
        }
        return captured;
    }

    private async Task<bool> VerifyFilesAsync(
        GoalDeliveryCandidateV1 candidate,
        CancellationToken cancellationToken)
    {
        ValidatePath(candidate);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(candidate.FilePath)
            || !ProductionLocalEnvironment.IsOrdinaryFile(candidate.ManifestPath)
            || new FileInfo(candidate.FilePath).Length != candidate.FileBytes
            || new FileInfo(candidate.ManifestPath).Length != candidate.ManifestBytes)
        {
            return false;
        }
        var videoSha = await ProductionLocalEnvironment.Sha256FileAsync(
            candidate.FilePath, cancellationToken).ConfigureAwait(false);
        if (videoSha != candidate.FileSha256)
        {
            return false;
        }
        var manifestSha = await ProductionLocalEnvironment.Sha256FileAsync(
            candidate.ManifestPath, cancellationToken).ConfigureAwait(false);
        return manifestSha == candidate.ManifestSha256;
    }

    private void ValidatePath(GoalDeliveryCandidateV1 candidate)
    {
        if (string.IsNullOrWhiteSpace(candidate.ProductionJobId)
            || !HasSha(candidate.FileSha256) || candidate.FileBytes <= 0
            || !Path.IsPathFullyQualified(candidate.FilePath)
            || !Path.IsPathFullyQualified(candidate.ManifestPath))
        {
            throw Invalid();
        }

        string root;
        string expectedFile;
        string expectedManifest;
        if (candidate.Kind == GoalDeliveryKind.C004Fallback && candidate.MasterInputDigest is null)
        {
            root = _finalVideoRoot;
            var jobHash = Convert.ToHexString(
                SHA256.HashData(Encoding.UTF8.GetBytes(candidate.ProductionJobId)))
                .ToLowerInvariant()[..32];
            expectedFile = Path.Combine(root, "final-" + jobHash + ".mp4");
            expectedManifest = Path.Combine(root, "final-" + jobHash + ".final-video.json");
        }
        else if (candidate.Kind == GoalDeliveryKind.C009Master
            && HasSha(candidate.MasterInputDigest))
        {
            root = _masterRoot;
            var jobDir = MasterPathPolicy.JobDirectory(root, candidate.ProductionJobId);
            var artifactDir = MasterPathPolicy.ArtifactDirectory(jobDir, candidate.MasterInputDigest!);
            expectedFile = Path.Combine(artifactDir, PostProductionMasterArtifactCatalog.OutputFileName);
            expectedManifest = Path.Combine(artifactDir, PostProductionMasterArtifactCatalog.ManifestFileName);
        }
        else
        {
            throw Invalid();
        }
        if (!SamePath(expectedFile, candidate.FilePath)
            || !SamePath(expectedManifest, candidate.ManifestPath)
            || !Directory.Exists(root))
        {
            throw Invalid();
        }
        ProductionLocalEnvironment.AssertNoLinkEscape(root, root);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, expectedFile);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, expectedManifest);
    }

    private static bool SamePath(string a, string b) =>
        string.Equals(Path.GetFullPath(a), Path.GetFullPath(b), StringComparison.OrdinalIgnoreCase);

    private static string RequireFullRoot(string root) =>
        string.IsNullOrWhiteSpace(root) || !Path.IsPathFullyQualified(root)
            ? throw new ArgumentException("DELIVERY_ROOT_INVALID", nameof(root))
            : Path.GetFullPath(root);

    private static bool HasSha(string? sha) => sha is { Length: 64 }
        && sha.All(static c => c is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static InvalidDataException Invalid() => new("GOAL_DELIVERY_CANDIDATE_INVALID");

    private static bool IsRejectedFileError(Exception e) => e is IOException
        or UnauthorizedAccessException or ArgumentException or NotSupportedException
        or InvalidOperationException or System.Security.Cryptography.CryptographicException;
}
