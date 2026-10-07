using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

public sealed partial class ControlCenterSession
{
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
