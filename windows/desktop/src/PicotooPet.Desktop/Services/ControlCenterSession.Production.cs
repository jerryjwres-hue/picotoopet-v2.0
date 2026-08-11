using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>Production API 只复用当前已配对 Mac Core 凭据；不会持久化 renderer 配置。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<IReadOnlyList<ProductionEligibleCreativeRecord>> GetProductionEligibleAsync(
        CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.GetEligibleAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<ProductionJobRecord>> GetProductionJobsAsync(
        CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.GetJobsAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProductionJobRecord> CreateProductionJobAsync(
        ProductionJobCreateRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateProductionClient();
        return await client.CreateJobAsync(request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProductionPlanRecord> GetProductionPlanAsync(
        string productionJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.GetPlanAsync(productionJobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProductionClaimRecord> ClaimProductionJobAsync(
        string productionJobId,
        string executorId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.ClaimAsync(productionJobId, executorId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProductionJobRecord> HeartbeatProductionJobAsync(
        string productionJobId,
        string executorId,
        string leaseToken,
        CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.HeartbeatAsync(
            productionJobId,
            executorId,
            leaseToken,
            cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProductionTaskRecord> MarkProductionAttemptAsync(
        string productionJobId,
        string productionTaskId,
        ProductionTaskAttemptRequest request,
        CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.MarkAttemptAsync(
            productionJobId,
            productionTaskId,
            request,
            cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProductionTaskRecord> CommitProductionResultAsync(
        string productionJobId,
        string productionTaskId,
        ProductionTaskCommitRequest request,
        CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.CommitResultAsync(
            productionJobId,
            productionTaskId,
            request,
            cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProductionJobRecord> CancelProductionJobAsync(
        string productionJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.CancelAsync(productionJobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProductionPackageRecord?> GetProductionPackageAsync(
        string productionJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.GetPackageAsync(productionJobId, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreProductionClient CreateProductionClient()
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
            throw new InvalidOperationException("尚未配对 Mac Core，无法使用 Production API。");
        }
        if (!Uri.TryCreate(macBaseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("已保存的 Mac Core 地址无效。");
        }
        return MacCoreProductionClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
    }
}
