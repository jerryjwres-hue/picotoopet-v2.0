using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>2.3.21.1 End-to-End Business Pipeline 的真实 Mac Core 会话扩展。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<IReadOnlyList<BusinessPipelineRunRecord>> GetBusinessPipelineRunsAsync(
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessPipelineClient();
        return await client.GetRunsAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<BusinessPipelineRunRecord> CreateBusinessPipelineRunAsync(
        BusinessPipelineRunCreateRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateBusinessPipelineClient();
        return await client.CreateRunAsync(request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<BusinessPipelineRunRecord> ReconcileBusinessPipelineRunAsync(
        string pipelineRunId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessPipelineClient();
        return await client.ReconcileAsync(pipelineRunId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<BusinessPipelineRunRecord> CancelBusinessPipelineRunAsync(
        string pipelineRunId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessPipelineClient();
        return await client.CancelAsync(pipelineRunId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<BusinessReturnPackageRecord?> GetBusinessReturnPackageAsync(
        string pipelineRunId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessPipelineClient();
        return await client.GetReturnPackageAsync(pipelineRunId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<byte[]> DownloadBusinessReturnPackageAsync(
        string pipelineRunId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateBusinessPipelineClient();
        return await client.DownloadReturnPackageAsync(pipelineRunId, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreBusinessPipelineClient CreateBusinessPipelineClient()
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
            throw new InvalidOperationException("尚未配对 Mac Core，无法使用 Business Pipeline API。");
        }
        return MacCoreBusinessPipelineClient.Create(
            MacCoreClientOptions.CreateDefault(new Uri(baseUrl, UriKind.Absolute), token));
    }
}
