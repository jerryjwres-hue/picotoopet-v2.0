using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>Deep-AI API 只复用当前 Mac Core 配对凭据；Windows 不保存 provider secret/config。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<IReadOnlyList<DeepAiEscalationRecord>> GetDeepAiEscalationsAsync(
        CancellationToken cancellationToken)
    {
        await using var client = CreateDeepAiClient();
        return await client.GetEscalationsAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<DeepAiEscalationRecord> PrepareDeepAiEscalationAsync(
        DeepAiEscalationPrepareRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateDeepAiClient();
        return await client.PrepareAsync(request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<DeepAiEscalationRecord> ReconcileDeepAiEscalationAsync(
        string escalationJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateDeepAiClient();
        return await client.ReconcileAsync(escalationJobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<DeepAiReadinessRecord> GetDeepAiReadinessAsync(
        string escalationJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateDeepAiClient();
        return await client.GetReadinessAsync(escalationJobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<DeepAiUsageRecord> GetDeepAiUsageAsync(
        string escalationJobId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateDeepAiClient();
        return await client.GetUsageAsync(escalationJobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<DeepAiLearningObservationRecord> RecordDeepAiFeedbackAsync(
        string escalationJobId,
        DeepAiFeedbackRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateDeepAiClient();
        return await client.RecordFeedbackAsync(
            escalationJobId,
            request,
            cancellationToken).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<DeepAiLearningEventRecord>> GetDeepAiLearningAsync(
        string? projectKey,
        CancellationToken cancellationToken)
    {
        await using var client = CreateDeepAiClient();
        return await client.GetLearningAsync(projectKey, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreDeepAiClient CreateDeepAiClient()
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
            throw new InvalidOperationException("尚未配对 Mac Core，无法使用 Deep-AI API。");
        }
        if (!Uri.TryCreate(macBaseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("已保存的 Mac Core 地址无效。");
        }
        return MacCoreDeepAiClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
    }
}
