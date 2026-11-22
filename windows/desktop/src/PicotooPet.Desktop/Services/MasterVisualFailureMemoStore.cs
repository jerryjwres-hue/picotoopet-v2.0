using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// A negative C009 visual-input observation, never an approval or task ledger.
/// Suppresses an unchanged deterministic visual failure across process restarts,
/// but never suppresses a newly verified source-byte state.
/// </summary>
public sealed class MasterVisualFailureMemoStore
{
    private const string MemoSchema = "picotoo.c009.master-visual-failure.v1";
    private const int MaximumMemoBytes = 512;
    private readonly string _root;
    private readonly string _finalRoot;
    private readonly string _overlayRoot;

    public MasterVisualFailureMemoStore(string root, string finalRoot, string overlayRoot)
    {
        if (!Path.IsPathFullyQualified(root) || !Path.IsPathFullyQualified(finalRoot)
            || !Path.IsPathFullyQualified(overlayRoot))
            throw new ArgumentException("C009_FAILURE_MEMO_ROOT_INVALID");

        _root = Path.GetFullPath(root);
        _finalRoot = Path.GetFullPath(finalRoot);
        _overlayRoot = Path.GetFullPath(overlayRoot);
    }

    public static MasterVisualFailureMemoStore CreateDefault()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(local))
            throw new DirectoryNotFoundException("LOCAL_APP_DATA_NOT_FOUND");
        return new MasterVisualFailureMemoStore(
            Path.Combine(local, "PicotooPet", "PostProduction", "VisualFailureMemo", "v1"),
            Path.Combine(local, "PicotooPet", "FinalVideos"),
            Path.Combine(local, "PicotooPet", "PostProduction", "TextOverlay", "v1"));
    }

    public async Task<string?> CaptureFingerprintAsync(
        MasterCompositionInputV1 input, CancellationToken cancellationToken)
    {
        // 01. Fingerprint *actual local bytes*, not just an old receipt's
        //     claimed SHA. A corrected file changes the fingerprint and
        //     permits one new C009 validation attempt after a restart.
        var c004Video = await CaptureFileAsync(
            _finalRoot, input.C004.FilePath, cancellationToken).ConfigureAwait(false);
        var c004Manifest = await CaptureFileAsync(
            _finalRoot, input.C004.ManifestPath, cancellationToken).ConfigureAwait(false);
        if (c004Video is null || c004Manifest is null)
            return null;

        var parts = new List<string>
        {
            "visual-failure-state-v1",
            input.C004.ProductionJobId,
            input.C004.ProductionPackageDigest,
            input.C004.Sha256,
            input.C004.Bytes.ToString(System.Globalization.CultureInfo.InvariantCulture),
            input.NarrationPlan.NarrationPlanDigest,
            input.OverlayPlan.CaptionOverlayPlanDigest,
            c004Video,
            c004Manifest,
        };
        if (input.OverlayPlan.Plan.OverlaysRequired)
        {
            if (input.OverlayArtifact is null)
                return null;
            var overlayVideo = await CaptureFileAsync(
                _overlayRoot, input.OverlayArtifact.FilePath, cancellationToken).ConfigureAwait(false);
            var overlayManifest = await CaptureFileAsync(
                _overlayRoot, input.OverlayArtifact.ManifestPath, cancellationToken).ConfigureAwait(false);
            if (overlayVideo is null || overlayManifest is null)
                return null;
            parts.Add(overlayVideo);
            parts.Add(overlayManifest);
        }
        else
        {
            parts.Add("NO_OVERLAY");
        }
        return Hex(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join("\u001f", parts))));
    }

    public async Task<bool> WasAlreadyFailedAsync(
        string goalId, string jobId, string fingerprint, CancellationToken cancellationToken)
    {
        // 02. A missing memo permits ordinary C009 validation. A malformed or
        //     symlinked memo fails closed; no assumption of prior success.
        var path = PathFor(goalId, jobId);
        if (!File.Exists(path))
            return false;
        ProductionLocalEnvironment.AssertNoLinkEscape(_root, path);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(path)
            || new FileInfo(path).Length is <= 0 or > MaximumMemoBytes)
            throw new InvalidDataException("C009_FAILURE_MEMO_TAMPERED");
        var bytes = await File.ReadAllBytesAsync(path, cancellationToken).ConfigureAwait(false);
        if (bytes.Length is <= 0 or > MaximumMemoBytes)
            throw new InvalidDataException("C009_FAILURE_MEMO_TAMPERED");
        try
        {
            using var document = JsonDocument.Parse(bytes);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object
                || root.EnumerateObject().Count() != 3
                || root.GetProperty("schema").GetString() != MemoSchema
                || root.GetProperty("code").GetString() != MasterCompositionException.VisualInvalid)
                throw new InvalidDataException("C009_FAILURE_MEMO_TAMPERED");
            var recorded = root.GetProperty("fingerprint").GetString();
            if (!ValidDigest(recorded))
                throw new InvalidDataException("C009_FAILURE_MEMO_TAMPERED");
            return recorded == fingerprint;
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("C009_FAILURE_MEMO_TAMPERED", exception);
        }
    }

    public async Task RememberAsync(
        string goalId, string jobId, string fingerprint, CancellationToken cancellationToken)
    {
        // 03. Write only a negative error code and SHA, never private paths,
        //     prompt strings, Core credentials, a receipt PASS or a retry grant.
        if (!ValidDigest(fingerprint))
            throw new InvalidDataException("C009_FAILURE_FINGERPRINT_INVALID");
        var path = PathFor(goalId, jobId);
        Directory.CreateDirectory(_root);
        ProductionLocalEnvironment.AssertNoLinkEscape(_root, _root);
        ProductionLocalEnvironment.AssertNoLinkEscape(_root, path);

        var payload = JsonSerializer.SerializeToUtf8Bytes(new
        {
            schema = MemoSchema,
            code = MasterCompositionException.VisualInvalid,
            fingerprint,
        });
        var temp = Path.Combine(_root, "." + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            await using (var stream = new FileStream(
                temp, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                4096, FileOptions.Asynchronous))
            {
                await stream.WriteAsync(payload, cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
            }
            if (File.Exists(path) && !ProductionLocalEnvironment.IsOrdinaryFile(path))
                throw new InvalidDataException("C009_FAILURE_MEMO_TAMPERED");
            File.Move(temp, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temp))
                File.Delete(temp);
        }
    }

    private static async Task<string?> CaptureFileAsync(
        string allowedRoot, string? path, CancellationToken cancellationToken)
    {
        // 04. Never hash arbitrary Core/user paths or follow symlinks.
        //     An absent source has a stable marker so creating the file later
        //     changes the fingerprint and allows a fresh validation attempt.
        try
        {
            if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path))
                return null;
            var full = Path.GetFullPath(path);
            if (!full.StartsWith(
                    Path.TrimEndingDirectorySeparator(allowedRoot)
                        + Path.DirectorySeparatorChar,
                    StringComparison.OrdinalIgnoreCase))
                return null;
            // 05. A corrected managed *path* must also change the memo,
            //     even if the file at the new path has identical bytes.
            //     This relative path is hashed only; never stored in plaintext.
            var relative = Path.GetRelativePath(allowedRoot, full)
                .Replace('\\', '/');
            if (File.Exists(full))
            {
                ProductionLocalEnvironment.AssertNoLinkEscape(allowedRoot, full);
                if (!ProductionLocalEnvironment.IsOrdinaryFile(full))
                    return null;
                await using var stream = new FileStream(
                    full, FileMode.Open, FileAccess.Read, FileShare.Read,
                    64 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan);
                var hash = await SHA256.HashDataAsync(stream, cancellationToken).ConfigureAwait(false);
                return "FILE:" + relative + ":" + Hex(hash) + ":" +
                    stream.Length.ToString(System.Globalization.CultureInfo.InvariantCulture);
            }
            ProductionLocalEnvironment.AssertNoLinkEscape(allowedRoot, full);
            return "MISSING:" + relative;
        }
        catch (Exception exception) when (exception is IOException
            or UnauthorizedAccessException or ArgumentException or NotSupportedException)
        {
            return null;
        }
    }

    private string PathFor(string goalId, string jobId)
    {
        if (string.IsNullOrWhiteSpace(goalId) || goalId.Length > 160
            || string.IsNullOrWhiteSpace(jobId) || jobId.Length > 160)
            throw new InvalidDataException("C009_FAILURE_MEMO_ID_INVALID");
        var digest = Hex(SHA256.HashData(
            Encoding.UTF8.GetBytes(goalId + "\u001f" + jobId)));
        return Path.Combine(_root, digest + ".json");
    }

    private static bool ValidDigest(string? value) =>
        value is { Length: 64 } && value.All(static c => c is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static string Hex(byte[] bytes) => Convert.ToHexStringLower(bytes);
}
