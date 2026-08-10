using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>业务 Work Package/Result Package 的真实 Mac Core 会话扩展。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<BusinessWorkPackageRecord[]> GetBusinessWorkPackagesAsync(
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessAutomationClient();
        return await client.GetWorkPackagesAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<BusinessUploadPrepareResponse> PrepareBusinessUploadAsync(
        BusinessUploadPrepareRequest request,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessAutomationClient();
        return await client.PrepareUploadAsync(request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<BusinessUploadSessionRecord> UploadBusinessChunkAsync(
        string uploadSessionId,
        long offset,
        string sha256,
        ReadOnlyMemory<byte> payload,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessAutomationClient();
        return await client.UploadChunkAsync(
            uploadSessionId,
            offset,
            sha256,
            payload,
            cancellationToken).ConfigureAwait(false);
    }

    public async Task<BusinessWorkPackageRecord> FinalizeBusinessUploadAsync(
        string uploadSessionId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessAutomationClient();
        return await client.FinalizeUploadAsync(uploadSessionId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<BusinessWorkPackageRecord> CancelBusinessWorkPackageAsync(
        string workPackageId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessAutomationClient();
        return await client.CancelWorkPackageAsync(workPackageId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<BusinessResultPackageRecord?> GetBusinessResultAsync(
        string workPackageId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessAutomationClient();
        return await client.GetResultAsync(workPackageId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<byte[]> DownloadBusinessResultAsync(
        string workPackageId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessAutomationClient();
        return await client.DownloadResultAsync(workPackageId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<DeepAiHandoffRecord?> GetBusinessDeepAiHandoffAsync(
        string workPackageId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessAutomationClient();
        return await client.GetDeepAiHandoffAsync(workPackageId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<byte[]> DownloadBusinessDeepAiHandoffAsync(
        string workPackageId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessAutomationClient();
        return await client.DownloadDeepAiHandoffAsync(workPackageId, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreBusinessAutomationClient CreateBusinessAutomationClient()
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
        return MacCoreBusinessAutomationClient.Create(
            MacCoreClientOptions.CreateDefault(new Uri(baseUrl, UriKind.Absolute), token));
    }
}
