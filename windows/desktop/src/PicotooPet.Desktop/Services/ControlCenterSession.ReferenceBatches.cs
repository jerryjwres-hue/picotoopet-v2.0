using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>复用现有 Core 配对凭证提交待审核参考图片；此处绝不直接批准或启动 GPU。</summary>
public sealed partial class ControlCenterSession : IReferenceBatchGateway
{
    public async Task<ReferenceBatchReceipt> RegisterReferenceBatchAsync(
        ReferenceBatchRequest request, string idempotencyKey, CancellationToken cancellationToken)
    {
        await using var client = CreateGoalCenterClient();
        return await client.RegisterReferenceBatchAsync(request, idempotencyKey, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ReferenceBatchReceipt> GetReferenceBatchAsync(string approvalId, CancellationToken cancellationToken)
    {
        await using var client = CreateGoalCenterClient();
        return await client.GetReferenceBatchAsync(approvalId, cancellationToken).ConfigureAwait(false);
    }
}
