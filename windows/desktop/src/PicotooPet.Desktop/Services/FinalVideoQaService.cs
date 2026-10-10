using System.Text.Json;
using System.Security.Cryptography;

namespace PicotooPet.Desktop.Services;

/// <summary>Read-only upstream verification, strict media QA and PASS-only durable receipt.</summary>
public sealed class FinalVideoQaService
{
    private readonly FinalVideoQaLineageValidator _lineage;
    private readonly FinalVideoQaMediaProbe _media;
    private readonly FinalArtifactReceiptStore _receipts;
    private readonly TimeProvider _time;

    public FinalVideoQaService() : this(new FixedMasterVideoProcessRunner(), Root("FinalVideos"),
        Root("Narration", "v1"), Root("PostProduction", "TextOverlay", "v1"), Root("PostProduction", "Master", "v1"),
        Root("PostProduction", "DeliveryReceipts", "v1"), TimeProvider.System) { }
    internal FinalVideoQaService(IMasterVideoProcessRunner runner, string finals, string narration, string overlays,
        string masters, string receipts, TimeProvider time)
    {
        _lineage = new(finals, narration, overlays, masters);
        _media = new(runner);
        _receipts = new(receipts);
        _time = time;
    }
    private static string Root(params string[] suffix) => Path.Combine(
        new[] { Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PicotooPet" }.Concat(suffix).ToArray());

    public async Task<FinalVideoQaResult> VerifyAsync(FinalVideoQaInputV1 input, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // Snapshot caller-owned arrays before awaits. Arbitrary unknown fields/path policies cannot become authority.
        try
        {
            var bytes = JsonSerializer.SerializeToUtf8Bytes(input, FinalQaIdentity.Json);
            if (bytes.Length > 1024 * 1024) throw new FinalVideoQaException("INPUT_INVALID");
            input = JsonSerializer.Deserialize<FinalVideoQaInputV1>(bytes, FinalQaIdentity.Json)
                ?? throw new FinalVideoQaException("INPUT_INVALID");
        }
        catch (Exception e) when (e is JsonException or ArgumentException or InvalidOperationException)
        { throw new FinalVideoQaException("INPUT_INVALID"); }
        var verified = await _lineage.VerifyAsync(input, cancellationToken).ConfigureAwait(false);
        await using var candidateGuard = OpenGuard(verified.CandidatePath);
        try
        {
            var lockedSha = Convert.ToHexString(await SHA256.HashDataAsync(candidateGuard, cancellationToken).ConfigureAwait(false)).ToLowerInvariant();
            if (candidateGuard.Length != verified.Template.ArtifactBytes || lockedSha != verified.Template.ArtifactSha256)
                throw new FinalVideoQaException("HASH_MISMATCH");
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or NotSupportedException)
        { throw new FinalVideoQaException("ARTIFACT_INVALID"); }
        // Hold the Windows read handle (without write/delete sharing) through lookup, decode and publication.
        // Revalidate paths after acquiring it to close the pre-open path/reparse race.
        var locked = await _lineage.VerifyAsync(input, cancellationToken).ConfigureAwait(false);
        if (locked.Template.QaInputDigest != verified.Template.QaInputDigest) throw new FinalVideoQaException("HASH_MISMATCH");
        var existing = await _receipts.FindAsync(verified, cancellationToken).ConfigureAwait(false);
        if (existing is not null) return existing;
        var facts = await _media.VerifyAsync(verified.CandidatePath, verified.Template.OutputProfileId,
            verified.Template.NarrationRequired, verified.Frames, verified.Template.TargetRuntimeMs, cancellationToken).ConfigureAwait(false);
        // The candidate stays locked; revalidate the upstream provenance after expensive decode as well.
        var again = await _lineage.VerifyAsync(input, cancellationToken).ConfigureAwait(false);
        if (again.Template.QaInputDigest != verified.Template.QaInputDigest) throw new FinalVideoQaException("HASH_MISMATCH");
        var receipt = verified.Template with { ObservedMedia = facts, VerifiedAt = _time.GetUtcNow() };
        receipt = receipt with { ReceiptDigest = FinalQaIdentity.ReceiptDigest(receipt) };
        return await _receipts.CommitAsync(verified, receipt, cancellationToken).ConfigureAwait(false);
    }
    private static FileStream OpenGuard(string path)
    {
        try { return new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 64 * 1024, FileOptions.Asynchronous); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException)
        { throw new FinalVideoQaException("ARTIFACT_INVALID"); }
    }
}
