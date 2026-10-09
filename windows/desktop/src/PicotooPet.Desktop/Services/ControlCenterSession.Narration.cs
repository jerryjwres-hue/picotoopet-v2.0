using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

public sealed partial class ControlCenterSession
{
    // 旁白计划沿用现有认证会话读取；这里只提供只读 Core 投影，不引入新的连接生命周期。
    public async Task<NarrationPlanResponseRecord> GetNarrationPlanAsync(
        string productionJobId,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(productionJobId);
        await using var client = CreateGoalCenterClient();
        return await client.GetNarrationPlanAsync(productionJobId, cancellationToken)
            .ConfigureAwait(false);
    }
}
