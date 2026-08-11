using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

public sealed partial class MacCoreProductionClient
{
    /// <summary>将最终本地渲染失败写回当前 Core lease；不接受 renderer 配置。</summary>
    public Task<ProductionTaskRecord> FailProductionTaskAsync(
        string productionJobId,
        string productionTaskId,
        ProductionTaskFailureRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionTaskRecord>(
            HttpMethod.Post,
            $"api/v1/production/jobs/{Escape(productionJobId)}/tasks/{Escape(productionTaskId)}/failure",
            payload,
            cancellationToken);
}
