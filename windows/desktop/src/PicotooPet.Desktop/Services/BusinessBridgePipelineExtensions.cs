using System.Security.Cryptography;
using System.Text.Json;
using PicotooPet.Desktop.Core.BusinessPipeline;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>扩展既有 BusinessBridge：first-party Adapter → 固定 Inbox，Core Pipeline → 固定 Outbox。</summary>
public static class BusinessBridgePipelineExtensions
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    public static async Task<BusinessAdapterBuildResult> SubmitAdapterSourceAsync(
        this BusinessBridgeService bridge,
        ControlCenterSession session,
        string adapterProfile,
        string sourcePath,
        string projectKey,
        string objective,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(bridge);
        ArgumentNullException.ThrowIfNull(session);
        var adapter = CreateAdapter(adapterProfile);
        var built = adapter.BuildPackage(
            new BusinessAdapterBuildRequest(
                sourcePath,
                bridge.Inbox,
                projectKey,
                objective));
        var processed = await bridge.ProcessInboxAsync(cancellationToken).ConfigureAwait(false);
        if (processed.Quarantined > 0)
        {
            throw new InvalidOperationException("Adapter Work Package 被 BusinessBridge 安全隔离。");
        }
        if (processed.Deferred > 0)
        {
            throw new IOException("Adapter Work Package 已保留在 Inbox，等待 Mac Core 恢复后重试。");
        }
        var packages = await session.GetBusinessWorkPackagesAsync(cancellationToken).ConfigureAwait(false);
        if (!packages.Any(item => item.WorkPackageId == built.Manifest.PackageId))
        {
            throw new InvalidOperationException("Adapter Work Package 未出现在 Mac Core durable facts 中。");
        }
        return built;
    }

    public static async Task<IReadOnlyList<BusinessPipelineRunRecord>> SynchronizeBusinessPipelineRunsAsync(
        this BusinessBridgeService bridge,
        ControlCenterSession session,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(bridge);
        ArgumentNullException.ThrowIfNull(session);
        var runs = await session.GetBusinessPipelineRunsAsync(cancellationToken).ConfigureAwait(false);
        var directory = Path.Combine(bridge.Root, "Runs");
        Directory.CreateDirectory(directory);
        foreach (var run in runs)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var safeId = Guid.Parse(run.PipelineRunId).ToString();
            var destination = Path.Combine(directory, safeId + ".json");
            WriteAtomicJson(destination, run);
        }
        return runs;
    }

    public static async Task<string> DeliverBusinessReturnPackageAsync(
        this BusinessBridgeService bridge,
        ControlCenterSession session,
        BusinessPipelineRunRecord run,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(bridge);
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(run);
        if (run.Status != "Completed" || run.ReturnPackageId is null)
        {
            throw new InvalidOperationException("Pipeline 尚未完成 Return Package。");
        }

        var payload = await session.DownloadBusinessReturnPackageAsync(run.PipelineRunId, cancellationToken)
            .ConfigureAwait(false);
        var directory = Path.Combine(bridge.Outbox, run.WorkPackageId);
        Directory.CreateDirectory(directory);
        var destination = Path.Combine(directory, "business-return-package.zip");
        WriteImmutable(destination, payload);
        return destination;
    }

    private static BusinessWorkPackageAdapter CreateAdapter(string adapterProfile) => adapterProfile switch
    {
        "amazon.reviews_export.v1" => new AmazonReviewsAdapter(),
        "inspiration.ideas_export.v1" => new InspirationIdeasAdapter(),
        _ => throw new InvalidOperationException("只允许 2.3.21.1 first-party Business Adapter profile。"),
    };

    private static void WriteAtomicJson(string destination, BusinessPipelineRunRecord run)
    {
        var temporary = destination + ".partial-" + Guid.NewGuid().ToString("N");
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(run, JsonOptions));
            File.Move(temporary, destination, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }
    }

    private static void WriteImmutable(string destination, ReadOnlySpan<byte> payload)
    {
        var temporary = destination + ".partial-" + Guid.NewGuid().ToString("N");
        try
        {
            File.WriteAllBytes(temporary, payload.ToArray());
            if (File.Exists(destination))
            {
                if (!string.Equals(HashFile(destination), HashFile(temporary), StringComparison.Ordinal))
                {
                    throw new IOException("Outbox immutable Return Package conflict.");
                }
                File.Delete(temporary);
                return;
            }
            File.Move(temporary, destination);
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }
    }

    private static string HashFile(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
}
