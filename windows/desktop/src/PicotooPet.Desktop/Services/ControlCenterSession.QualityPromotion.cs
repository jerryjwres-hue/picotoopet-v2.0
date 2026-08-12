using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>25.1 Promotion API 复用 Mac Core 配对凭据；Windows 只提交闭合治理动作。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<QualityPromotionRecord> CreateQualityPromotionAsync(
        QualityPromotionCreateRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateQualityPromotionClient();
        return await client.CreateAsync(request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<QualityPromotionRecord>> GetQualityPromotionsAsync(
        string? projectKey,
        string? candidateClass,
        CancellationToken cancellationToken)
    {
        await using var client = CreateQualityPromotionClient();
        return await client.GetPromotionsAsync(projectKey, candidateClass, cancellationToken)
            .ConfigureAwait(false);
    }

    public async Task<QualityPromotionRecord> ReconcileQualityPromotionAsync(
        string promotionId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateQualityPromotionClient();
        return await client.ReconcileAsync(promotionId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<QualityPromotionApprovalRequestRecord> GetQualityPromotionActivationRequestAsync(
        string promotionId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateQualityPromotionClient();
        return await client.GetActivationRequestAsync(promotionId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<QualityPromotionRecord> DecideQualityPromotionActivationAsync(
        string promotionId,
        QualityPromotionDecisionRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateQualityPromotionClient();
        return await client.DecideActivationAsync(promotionId, request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<QualityPromotionApprovalRequestRecord> RequestQualityPromotionRollbackAsync(
        string promotionId,
        QualityPromotionRollbackRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateQualityPromotionClient();
        return await client.RequestRollbackAsync(promotionId, request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<QualityPromotionApprovalRequestRecord> GetQualityPromotionRollbackRequestAsync(
        string promotionId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateQualityPromotionClient();
        return await client.GetRollbackRequestAsync(promotionId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<QualityPromotionRecord> DecideQualityPromotionRollbackAsync(
        string promotionId,
        QualityPromotionDecisionRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateQualityPromotionClient();
        return await client.DecideRollbackAsync(promotionId, request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<QualityPromotionHistoryRecord> GetQualityPromotionHistoryAsync(
        string promotionId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateQualityPromotionClient();
        return await client.GetHistoryAsync(promotionId, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreQualityPromotionClient CreateQualityPromotionClient()
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
            throw new InvalidOperationException("尚未配对 Mac Core，无法使用 Promotion API。");
        }
        if (!Uri.TryCreate(macBaseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("已保存的 Mac Core 地址无效。");
        }
        return MacCoreQualityPromotionClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
    }
}
