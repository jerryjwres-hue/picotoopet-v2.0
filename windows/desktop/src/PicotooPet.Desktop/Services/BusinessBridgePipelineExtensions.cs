using System.Security.Cryptography;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>把 Core-authored Return Package 幂等投递到既有固定 BusinessBridge Outbox。</summary>
public static class BusinessBridgePipelineExtensions
{
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
