using System.IO;
using System.Security.Cryptography;

namespace PicotooPet.Desktop.Services;

/// <summary>只把 Creative Package/Handoff 原子投递到固定 BusinessBridge Outbox。</summary>
public sealed class CreativePackageDeliveryService
{
    private readonly ControlCenterSession _session;

    public CreativePackageDeliveryService(ControlCenterSession session, string? localAppDataRoot = null)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        var localRoot = localAppDataRoot
            ?? Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        Root = Path.Combine(localRoot, "PicotooPet", "BusinessBridge", "Outbox", "Creative");
        Directory.CreateDirectory(Root);
    }

    public string Root { get; }

    public async Task<string> DeliverPackageAsync(string creativeJobId, CancellationToken cancellationToken)
    {
        var package = await _session.GetCreativePackageAsync(creativeJobId, cancellationToken)
            .ConfigureAwait(false)
            ?? throw new InvalidOperationException("Creative Package 尚未生成。");
        if (package.QualityOutcome != "PASS")
        {
            throw new InvalidOperationException("Creative Package 未通过质量门。");
        }
        var payload = await _session.DownloadCreativePackageAsync(creativeJobId, cancellationToken)
            .ConfigureAwait(false);
        return WriteJobFile(creativeJobId, "creative-package.zip", payload);
    }

    public async Task<string> DeliverHandoffAsync(string creativeJobId, CancellationToken cancellationToken)
    {
        var handoff = await _session.GetCreativeHandoffAsync(creativeJobId, cancellationToken)
            .ConfigureAwait(false)
            ?? throw new InvalidOperationException("Creative Deep-AI Handoff 尚未生成。");
        if (handoff.Status != "ManualReady")
        {
            throw new InvalidOperationException("Creative Deep-AI Handoff 尚未进入 ManualReady。");
        }
        var payload = await _session.DownloadCreativeHandoffAsync(creativeJobId, cancellationToken)
            .ConfigureAwait(false);
        return WriteJobFile(creativeJobId, "creative-deep-ai-handoff.zip", payload);
    }

    private string WriteJobFile(string creativeJobId, string fileName, ReadOnlySpan<byte> payload)
    {
        var safeId = Guid.Parse(creativeJobId).ToString();
        var directory = Path.Combine(Root, safeId);
        Directory.CreateDirectory(directory);
        var destination = Path.Combine(directory, fileName);
        var temporary = destination + ".partial-" + Guid.NewGuid().ToString("N");
        try
        {
            File.WriteAllBytes(temporary, payload.ToArray());
            if (File.Exists(destination))
            {
                if (!string.Equals(HashFile(destination), HashFile(temporary), StringComparison.Ordinal))
                {
                    throw new IOException("Creative Outbox immutable file conflict.");
                }
                File.Delete(temporary);
                return destination;
            }
            File.Move(temporary, destination);
            return destination;
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
