using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

public sealed partial class ControlCenterSession
{
    /// <summary>通过现有 Mac Core 配对会话回写最终生产失败。</summary>
    public async Task<ProductionTaskRecord> FailProductionTaskAsync(
        string productionJobId,
        string productionTaskId,
        ProductionTaskFailureRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        await using var client = CreateProductionClient();
        return await client.FailProductionTaskAsync(
            productionJobId,
            productionTaskId,
            request,
            cancellationToken).ConfigureAwait(false);
    }
}
