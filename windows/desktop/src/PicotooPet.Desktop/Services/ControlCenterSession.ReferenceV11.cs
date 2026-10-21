using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>仅复用现有配对凭据读取 Mac Core 的不可变 v1.1 镜头授权，不自行批准或触发 GPU。</summary>
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
