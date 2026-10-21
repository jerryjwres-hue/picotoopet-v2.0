using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

public sealed partial class ControlCenterSession
{
    public async Task<ProductionReferenceAuthorizationV11Record> GetReferenceAuthorizationV11Async(
        string productionJobId, string productionTaskId, CancellationToken cancellationToken)
    {
        await using var client = CreateProductionClient();
        return await client.GetReferenceAuthorizationV11Async(
            productionJobId, productionTaskId, cancellationToken).ConfigureAwait(false);
    }
}
