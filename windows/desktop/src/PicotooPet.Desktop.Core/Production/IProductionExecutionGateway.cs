using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>既有 Core claim/lease/attempt/result 边界；没有 WPF、GPU 或本地终态权限。</summary>
public interface IProductionExecutionGateway
{
    Task<ProductionPlanRecord> GetProductionPlanAsync(string job, CancellationToken ct);
    Task<ProductionClaimRecord> ClaimProductionJobAsync(string job, string executor, CancellationToken ct);
    Task<ProductionJobRecord> HeartbeatProductionJobAsync(string job, string executor, string lease, CancellationToken ct);
    Task<ProductionTaskRecord> MarkProductionAttemptAsync(string job, string task, ProductionTaskAttemptRequest request, CancellationToken ct);
    Task<ProductionTaskRecord> CommitProductionResultAsync(string job, string task, ProductionTaskCommitRequest request, CancellationToken ct);
    Task<ProductionTaskRecord> FailProductionTaskAsync(string job, string task, ProductionTaskFailureRequest request, CancellationToken ct);
    Task<ProductionPackageRecord?> GetProductionPackageAsync(string job, CancellationToken ct);
}

/// <summary>独立用户进程复用原 MacCoreProductionClient，禁止创建第二套服务端队列。</summary>
public sealed class HeadlessProductionGateway(MacCoreProductionClient client) : IProductionExecutionGateway
{
    public Task<ProductionPlanRecord> GetProductionPlanAsync(string job, CancellationToken ct) => client.GetPlanAsync(job, ct);
    public Task<ProductionClaimRecord> ClaimProductionJobAsync(string job, string executor, CancellationToken ct) => client.ClaimAsync(job, executor, ct);
    public Task<ProductionJobRecord> HeartbeatProductionJobAsync(string job, string executor, string lease, CancellationToken ct) => client.HeartbeatAsync(job, executor, lease, ct);
    public Task<ProductionTaskRecord> MarkProductionAttemptAsync(string job, string task, ProductionTaskAttemptRequest request, CancellationToken ct) => client.MarkAttemptAsync(job, task, request, ct);
    public Task<ProductionTaskRecord> CommitProductionResultAsync(string job, string task, ProductionTaskCommitRequest request, CancellationToken ct) => client.CommitResultAsync(job, task, request, ct);
    public Task<ProductionTaskRecord> FailProductionTaskAsync(string job, string task, ProductionTaskFailureRequest request, CancellationToken ct) => client.FailProductionTaskAsync(job, task, request, ct);
    public Task<ProductionPackageRecord?> GetProductionPackageAsync(string job, CancellationToken ct) => client.GetPackageAsync(job, ct);
}
