using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

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
