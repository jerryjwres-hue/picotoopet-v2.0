using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>复用现有 Core 配对凭证提交待审核参考图片；此处绝不直接批准或启动 GPU。</summary>
public sealed partial class ControlCenterSession : IReviewedThreeShotPlanGateway, IReviewedLtxPilotGateway
{
    public async Task<ReferenceBatchReceipt> RegisterReferenceBatchAsync(
        ReferenceBatchRequest request, string idempotencyKey, CancellationToken cancellationToken)
    {
        await using var client = CreateGoalCenterClient();
        return await client.RegisterReferenceBatchAsync(request, idempotencyKey, cancellationToken).ConfigureAwait(false);
    }

    // 复用 Production REST 客户端和同一配对会话；不启动 Worker。
    public async Task<ProductionJobRecord> CreateReviewedThreeShotV11Async(ProductionJobCreateRequest request,
        string approvedReferenceId, CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.CreateReviewedThreeShotV11Async(request, approvedReferenceId, cancellationToken).ConfigureAwait(false);
    }

    public Task<ProductionPlanRecord> ReadReviewedProductionPlanAsync(string jobId, CancellationToken cancellationToken)
        => GetProductionPlanAsync(jobId, cancellationToken);

    // 01. Same paired session, existing frozen v1.2 contract; no lease or GPU.
    public async Task<ProductionJobRecord> FreezeReviewedLtxPilotAsync(string creativePackageId,
        string approvalId, string idempotencyKey, CancellationToken cancellationToken,
        string? selectedShotId = null)
    {
        using var client = CreateWorkerChallengePreflightClient();
        return await client.FreezeLtxPilotAsync(creativePackageId, approvalId, idempotencyKey,
            cancellationToken, selectedShotId).ConfigureAwait(false);
    }

    public async Task<System.Text.Json.JsonElement> ReadReviewedLtxPlanAsync(string jobId, CancellationToken cancellationToken)
    {
        using var client = CreateWorkerChallengePreflightClient();
        return await client.GetLtxPlanAsync(jobId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ReferenceBatchReceipt> GetReferenceBatchAsync(string approvalId, CancellationToken cancellationToken)
    {
        await using var client = CreateGoalCenterClient();
        return await client.GetReferenceBatchAsync(approvalId, cancellationToken).ConfigureAwait(false);
    }
}
