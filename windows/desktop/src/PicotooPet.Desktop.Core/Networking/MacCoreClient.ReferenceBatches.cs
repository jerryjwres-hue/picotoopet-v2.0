using PicotooPet.Desktop.Core.Contracts;

#pragma warning disable CA1822 // Compile-only RED scaffold, replaced after native behavioral failure.

namespace PicotooPet.Desktop.Core.Networking;

public interface IReferenceBatchGateway
{
    Task<ReferenceBatchReceipt> RegisterReferenceBatchAsync(
        ReferenceBatchRequest request, string idempotencyKey, CancellationToken cancellationToken);
    Task<ReferenceBatchReceipt> GetReferenceBatchAsync(string approvalId, CancellationToken cancellationToken);
}

public sealed partial class MacCoreClient : IReferenceBatchGateway
{
    public Task<ReferenceBatchReceipt> RegisterReferenceBatchAsync(
        ReferenceBatchRequest request, string idempotencyKey, CancellationToken cancellationToken) =>
        throw new NotImplementedException("RED: authenticated reference batch registration");

    public Task<ReferenceBatchReceipt> GetReferenceBatchAsync(string approvalId, CancellationToken cancellationToken) =>
        throw new NotImplementedException("RED: authenticated reference batch observation");
}
