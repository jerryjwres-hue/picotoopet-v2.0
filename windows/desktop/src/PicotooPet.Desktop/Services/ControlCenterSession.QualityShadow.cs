using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>24.1 Shadow API 复用 Mac Core 配对凭据；Windows 不持有策略编辑权限。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<QualityShadowRunRecord> CreateQualityShadowRunAsync(
        QualityShadowRunCreateRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateQualityShadowClient();
        return await client.CreateAsync(request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<QualityShadowRunRecord>> GetQualityShadowRunsAsync(
        string? candidateId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateQualityShadowClient();
        return await client.GetRunsAsync(candidateId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<QualityShadowRunRecord> ReconcileQualityShadowRunAsync(
        string shadowRunId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateQualityShadowClient();
        return await client.ReconcileAsync(shadowRunId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<QualityShadowArmMetricRecord>> GetQualityShadowMetricsAsync(
        string shadowRunId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateQualityShadowClient();
        return await client.GetMetricsAsync(shadowRunId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<QualityShadowReviewRecord> ReviewQualityShadowRunAsync(
        string shadowRunId,
        QualityShadowReviewRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateQualityShadowClient();
        return await client.ReviewAsync(shadowRunId, request, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreQualityShadowClient CreateQualityShadowClient()
    {
        ThrowIfDisposed();
        string macBaseUrl;
        lock (_snapshotGate)
        {
            macBaseUrl = _macBaseUrl;
        }
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core，无法使用 Shadow API。");
        }
        if (!Uri.TryCreate(macBaseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("已保存的 Mac Core 地址无效。");
        }
        return MacCoreQualityShadowClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
    }
}
