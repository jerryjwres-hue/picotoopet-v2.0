using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>Uses the existing paired Bearer token and bounded JSON client; no second authentication.</summary>
public sealed partial class MacCoreProductionClient
{
    public Task<ProductionReferenceAuthorizationV11Record> GetReferenceAuthorizationV11Async(
        string productionJobId, string productionTaskId, CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionReferenceAuthorizationV11Record>(
            HttpMethod.Get,
            $"api/v1/production/jobs/{Escape(productionJobId)}/tasks/{Escape(productionTaskId)}/reference-authorization",
            null, cancellationToken);
}
