using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

#pragma warning disable CA1822 // Compile-only RED scaffold, replaced after native behavioral failure.

namespace PicotooPet.Desktop.Services;

public sealed partial class ControlCenterSession : IReferenceBatchGateway
{
    public Task<ReferenceBatchReceipt> RegisterReferenceBatchAsync(
        ReferenceBatchRequest request, string idempotencyKey, CancellationToken cancellationToken) =>
        throw new NotImplementedException("RED: paired session reference batch registration");

    public Task<ReferenceBatchReceipt> GetReferenceBatchAsync(string approvalId, CancellationToken cancellationToken) =>
        throw new NotImplementedException("RED: paired session reference batch observation");
}
