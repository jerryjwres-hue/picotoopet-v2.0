using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// Read-only GUI index for the existing C010A immutable QA receipt.
/// This file grants NO independent approval: C011, C010A and managed media are rechecked
/// against live Core authority on every restore and every Open.
/// </summary>
public sealed record VerifiedGoalDeliveryProjection(
    string GoalId,
    string ProductionJobId,
    GoalDeliveryCandidateV1 Candidate,
    FinalVideoQaInputV1 Input,
    FinalVideoQaResult Receipt,
    string AuthorityFingerprint);

public sealed class VerifiedGoalDeliveryProjectionStore
{
    private const int MaximumBytes = 2 * 1024 * 1024;
    private readonly string _root;

    public VerifiedGoalDeliveryProjectionStore(string root)
    {
        if (!Path.IsPathFullyQualified(root))
        {
            throw new InvalidDataException("GOAL_DELIVERY_STORE_ROOT_INVALID");
        }
        _root = Path.GetFullPath(root);
    }

    public static VerifiedGoalDeliveryProjectionStore CreateDefault() =>
        new(Path.Combine(Environment.GetFolderPath(
            Environment.SpecialFolder.LocalApplicationData), "PicotooPet",
            "PostProduction", "VerifiedGoals", "v1"));

    private string PathFor(string goalId, string jobId)
    {
        // ── Goal/Job identity controls the filename; no caller-selected paths. ──
        if (string.IsNullOrWhiteSpace(goalId) || string.IsNullOrWhiteSpace(jobId))
        {
            throw new InvalidDataException("GOAL_DELIVERY_STORE_ID_INVALID");
        }
        var digest = Convert.ToHexString(SHA256.HashData(
            Encoding.UTF8.GetBytes(goalId + "\u001f" + jobId))).ToLowerInvariant();
        return Path.Combine(_root, digest + ".json");
    }

    public async Task WriteAsync(VerifiedGoalDeliveryProjection projection, CancellationToken ct)
    {
        // ── The producer passes its actual C010A receipt; this store cannot mint one. ──
        if (projection.Candidate.ProductionJobId != projection.ProductionJobId
            || projection.Input.GoalContinuation.GoalId != projection.GoalId
            || projection.Input.ProductionJob.ProductionJobId != projection.ProductionJobId
            || projection.Receipt.Receipt.Outcome != "PASS"
            || !FinalQaIdentity.Sha(projection.AuthorityFingerprint)
            || projection.Candidate.ApprovalReceiptDigest != projection.Receipt.Receipt.ReceiptDigest)
        {
            throw new InvalidDataException("GOAL_DELIVERY_STORE_PROVENANCE_INVALID");
        }
        var payload = JsonSerializer.SerializeToUtf8Bytes(projection, FinalQaIdentity.Json);
        if (payload.Length is <= 0 or > MaximumBytes)
        {
            throw new InvalidDataException("GOAL_DELIVERY_STORE_SIZE_INVALID");
        }
        var path = PathFor(projection.GoalId, projection.ProductionJobId);
        ProductionLocalEnvironment.AssertNoLinkEscape(_root, _root);
        Directory.CreateDirectory(_root);
        ProductionLocalEnvironment.AssertNoLinkEscape(_root, path);
        if (File.Exists(path))
        {
            await AssertIdenticalAsync(path, payload, ct).ConfigureAwait(false);
            return;
        }
        var temp = Path.Combine(_root, "." + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            await using (var output = new FileStream(
                temp, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                16 * 1024, FileOptions.Asynchronous))
            {
                await output.WriteAsync(payload, ct).ConfigureAwait(false);
                await output.FlushAsync(ct).ConfigureAwait(false);
            }
            try
            {
                File.Move(temp, path);
            }
            catch (IOException) when (File.Exists(path))
            {
                await AssertIdenticalAsync(path, payload, ct).ConfigureAwait(false);
            }
        }
        finally
        {
            if (File.Exists(temp)) File.Delete(temp);
        }
    }

    public async Task<VerifiedGoalDeliveryProjection?> ReadAsync(
        string goalId, string jobId, CancellationToken ct)
    {
        if (!Directory.Exists(_root))
        {
            return null;
        }
        var path = PathFor(goalId, jobId);
        ProductionLocalEnvironment.AssertNoLinkEscape(_root, _root);
        ProductionLocalEnvironment.AssertNoLinkEscape(_root, path);
        if (!File.Exists(path))
        {
            return null;
        }
        if (!ProductionLocalEnvironment.IsOrdinaryFile(path)
            || new FileInfo(path).Length is <= 0 or > MaximumBytes)
        {
            throw new InvalidDataException("GOAL_DELIVERY_STORE_TAMPERED");
        }
        var bytes = await File.ReadAllBytesAsync(path, ct).ConfigureAwait(false);
        if (bytes.Length is <= 0 or > MaximumBytes)
        {
            throw new InvalidDataException("GOAL_DELIVERY_STORE_TAMPERED");
        }
        var record = JsonSerializer.Deserialize<VerifiedGoalDeliveryProjection>(bytes, FinalQaIdentity.Json)
            ?? throw new InvalidDataException("GOAL_DELIVERY_STORE_TAMPERED");
        if (record.GoalId != goalId || record.ProductionJobId != jobId
            || record.Candidate.ProductionJobId != jobId
            || record.Input.GoalContinuation.GoalId != goalId
            || record.Input.ProductionJob.ProductionJobId != jobId
            || record.Receipt.Receipt.Outcome != "PASS"
            || !FinalQaIdentity.Sha(record.AuthorityFingerprint)
            || record.Candidate.ApprovalReceiptDigest != record.Receipt.Receipt.ReceiptDigest)
        {
            throw new InvalidDataException("GOAL_DELIVERY_STORE_TAMPERED");
        }
        return record;
    }

    private static async Task AssertIdenticalAsync(string path, byte[] expected, CancellationToken ct)
    {
        if (!ProductionLocalEnvironment.IsOrdinaryFile(path)
            || new FileInfo(path).Length != expected.Length)
        {
            throw new InvalidDataException("GOAL_DELIVERY_STORE_IMMUTABLE_CONFLICT");
        }
        var current = await File.ReadAllBytesAsync(path, ct).ConfigureAwait(false);
        if (!current.AsSpan().SequenceEqual(expected))
        {
            throw new InvalidDataException("GOAL_DELIVERY_STORE_IMMUTABLE_CONFLICT");
        }
    }
}
