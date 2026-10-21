using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

public sealed partial class MacCoreProductionClient
{
    /// <summary>Read existing Core exact-ID endpoint, never fall back to bounded recent-job enumeration.</summary>
    public Task<ProductionJobRecord> GetJobAsync(string productionJobId, CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionJobRecord>(HttpMethod.Get,
            $"api/v1/production/jobs/{Escape(productionJobId)}", null, cancellationToken);
}
