using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>Creative Intelligence 的真实 Mac Core 会话扩展。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<CreativeEligibleSourceRecord[]> GetCreativeEligibleSourcesAsync(
        CancellationToken cancellationToken)
    {
        await using var client = CreateCreativeIntelligenceClient();
        return await client.GetEligibleSourcesAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<CreativeJobRecord[]> GetCreativeJobsAsync(CancellationToken cancellationToken)
    {
        await using var client = CreateCreativeIntelligenceClient();
        return await client.GetJobsAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<CreativeJobRecord> CreateCreativeJobAsync(
        CreativeJobCreateRequest request,
        CancellationToken cancellationToken)
    {
        await using var client = CreateCreativeIntelligenceClient();
        return await client.CreateJobAsync(request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<CreativeJobRecord> CancelCreativeJobAsync(
        string creativeJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateCreativeIntelligenceClient();
        return await client.CancelJobAsync(creativeJobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<CreativePackageRecord?> GetCreativePackageAsync(
        string creativeJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateCreativeIntelligenceClient();
        return await client.GetPackageAsync(creativeJobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<byte[]> DownloadCreativePackageAsync(
        string creativeJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateCreativeIntelligenceClient();
        return await client.DownloadPackageAsync(creativeJobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<CreativeDeepAiHandoffRecord?> GetCreativeHandoffAsync(
        string creativeJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateCreativeIntelligenceClient();
        return await client.GetHandoffAsync(creativeJobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<byte[]> DownloadCreativeHandoffAsync(
        string creativeJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateCreativeIntelligenceClient();
        return await client.DownloadHandoffAsync(creativeJobId, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreCreativeIntelligenceClient CreateCreativeIntelligenceClient()
    {
        ThrowIfDisposed();
        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core。");
        }
        return MacCoreCreativeIntelligenceClient.Create(
            MacCoreClientOptions.CreateDefault(new Uri(baseUrl, UriKind.Absolute), token));
    }
}
