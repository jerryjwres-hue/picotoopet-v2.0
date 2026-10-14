using System.Text.Json;
using System.Text.Json.Nodes;

namespace PicotooPet.Desktop.Services;

/// <summary>Exact immutable PASS directory; no latest lookup, overwrite, or upstream mutation.</summary>
public sealed class FinalArtifactReceiptStore
{
    internal const string FileName = "final-artifact-receipt.json";
    private readonly string _root;
    internal FinalArtifactReceiptStore(string root)
    {
        if (!Path.IsPathFullyQualified(root)) throw new FinalVideoQaException("INPUT_INVALID");
        _root = Path.GetFullPath(root);
    }
    internal static JsonObject InputFields(FinalArtifactReceiptV1 receipt)
    {
        // The observation is intentionally absent before probing; nullable serialization is not an input boundary here.
        var node = JsonSerializer.SerializeToNode(receipt, FinalQaIdentity.Json)!.AsObject();
        foreach (var field in new[] { "qa_input_digest", "receipt_digest", "observed_media", "passed_check_ids", "verified_at" }) node.Remove(field);
        return node;
    }
    private string DirectoryFor(FinalArtifactReceiptV1 expected) => MasterPathPolicy.ArtifactDirectory(
        MasterPathPolicy.JobDirectory(_root, expected.ProductionJobId), expected.QaInputDigest);

    internal async Task<FinalVideoQaResult?> FindAsync(FinalQaVerifiedInput expected, CancellationToken ct)
    {
        try
        {
            var directory = DirectoryFor(expected.Template);
            ProductionLocalEnvironment.AssertNoLinkEscape(_root, directory);
            if (File.Exists(directory)) throw new FinalVideoQaException("RECEIPT_CONFLICT");
            if (!Directory.Exists(directory)) return null;
            var receipt = await ReadAsync(directory, expected, ct).ConfigureAwait(false);
            return new(receipt, Path.Combine(directory, FileName), true);
        }
        catch (OperationCanceledException) { throw; }
        catch (FinalVideoQaException) { throw; }
        catch (Exception e) when (e is IOException or InvalidDataException or UnauthorizedAccessException or JsonException or ArgumentException
            or InvalidOperationException or NullReferenceException or NotSupportedException)
        { throw new FinalVideoQaException("RECEIPT_CONFLICT"); }
    }
    private async Task<FinalArtifactReceiptV1> ReadAsync(string directory, FinalQaVerifiedInput expected, CancellationToken ct)
    {
        var path = Path.Combine(directory, FileName);
        ProductionLocalEnvironment.AssertNoLinkEscape(_root, path);
        if (Directory.EnumerateFileSystemEntries(directory).Count() != 1 || !ProductionLocalEnvironment.IsOrdinaryFile(path)
            || new FileInfo(path).Length is <= 0 or > 512 * 1024) throw new FinalVideoQaException("RECEIPT_CONFLICT");
        var bytes = await File.ReadAllBytesAsync(path, ct).ConfigureAwait(false);
        if (bytes.Length > 512 * 1024) throw new FinalVideoQaException("RECEIPT_CONFLICT");
        using var doc = JsonDocument.Parse(bytes);
        FinalVideoQaMediaProbe.RejectDuplicates(doc.RootElement);
        var receipt = JsonSerializer.Deserialize<FinalArtifactReceiptV1>(bytes, FinalQaIdentity.Json)
            ?? throw new FinalVideoQaException("RECEIPT_CONFLICT");
        if (receipt.QaInputDigest != expected.Template.QaInputDigest || !FinalQaIdentity.Sha(receipt.ReceiptDigest)
            || receipt.ReceiptDigest != FinalQaIdentity.ReceiptDigest(receipt) || receipt.VerifiedAt == default
            || !receipt.PassedCheckIds.SequenceEqual(FinalQaIdentity.Checks, StringComparer.Ordinal)
            || !JsonNode.DeepEquals(InputFields(receipt), InputFields(expected.Template)))
            throw new FinalVideoQaException("RECEIPT_CONFLICT");
        try { FinalVideoQaMediaProbe.Validate(receipt.ObservedMedia, receipt.OutputProfileId, receipt.NarrationRequired, expected.Frames, receipt.TargetRuntimeMs); }
        catch (FinalVideoQaException) { throw new FinalVideoQaException("RECEIPT_CONFLICT"); }
        return receipt;
    }
    internal async Task<FinalVideoQaResult> CommitAsync(FinalQaVerifiedInput expected, FinalArtifactReceiptV1 receipt, CancellationToken ct)
    {
        string? temporary = null;
        try
        {
            ct.ThrowIfCancellationRequested();
            ProductionLocalEnvironment.AssertNoLinkEscape(_root, _root);
            Directory.CreateDirectory(_root);
            var job = MasterPathPolicy.JobDirectory(_root, receipt.ProductionJobId);
            ProductionLocalEnvironment.AssertNoLinkEscape(_root, job);
            Directory.CreateDirectory(job);
            temporary = Path.Combine(job, $".{receipt.QaInputDigest}.{Guid.NewGuid():N}.tmp");
            Directory.CreateDirectory(temporary);
            ProductionLocalEnvironment.AssertNoLinkEscape(_root, temporary);
            await using (var output = new FileStream(Path.Combine(temporary, FileName), FileMode.CreateNew,
                FileAccess.Write, FileShare.None, 16 * 1024, FileOptions.Asynchronous))
            {
                await output.WriteAsync(JsonSerializer.SerializeToUtf8Bytes(receipt, FinalQaIdentity.Json), ct).ConfigureAwait(false);
                await output.FlushAsync(ct).ConfigureAwait(false);
            }
            await ReadAsync(temporary, expected, ct).ConfigureAwait(false);
            ct.ThrowIfCancellationRequested();
            var final = DirectoryFor(receipt);
            try { Directory.Move(temporary, final); temporary = null; }
            catch (IOException)
            {
                var winner = await FindAsync(expected, ct).ConfigureAwait(false);
                return winner ?? throw new FinalVideoQaException("RECEIPT_CONFLICT");
            }
            return new(receipt, Path.Combine(final, FileName), false);
        }
        catch (OperationCanceledException) { throw; }
        catch (FinalVideoQaException) { throw; }
        catch (Exception e) when (e is IOException or InvalidDataException or UnauthorizedAccessException or JsonException or ArgumentException or InvalidOperationException)
        { throw new FinalVideoQaException("RECEIPT_CONFLICT"); }
        finally
        {
            if (temporary is not null)
            {
                try
                {
                    ProductionLocalEnvironment.AssertNoLinkEscape(_root, temporary);
                    // Delete only our generated ordinary file, never recurse into untrusted entries.
                    var file = Path.Combine(temporary, FileName);
                    if (ProductionLocalEnvironment.IsOrdinaryFile(file)) File.Delete(file);
                    Directory.Delete(temporary, recursive: false);
                }
                catch (IOException) { }
                catch (InvalidDataException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
    }
}
