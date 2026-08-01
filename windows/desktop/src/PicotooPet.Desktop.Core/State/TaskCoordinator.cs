using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.State;

/// <summary>把 REST 任务操作与状态仓库连接起来。</summary>
public sealed class TaskCoordinator
{
    private readonly MacCoreClient _client;
    private readonly AppStateStore _stateStore;

    /// <summary>创建任务协调器。</summary>
    public TaskCoordinator(MacCoreClient client, AppStateStore stateStore)
    {
        _client     = client;
        _stateStore = stateStore;
    }

    /// <summary>创建任务并立即把服务端快照加入界面，随后由事件流校正。</summary>
    public async Task<TaskRecord> CreateAsync(
        TaskCreateRequest request,
        CancellationToken cancellationToken = default)
    {
        var idempotencyKey = Guid.NewGuid().ToString("N");
        var task = await _client.CreateTaskAsync(
            request,
            idempotencyKey,
            cancellationToken).ConfigureAwait(false);
        _stateStore.UpsertTask(task);
        return task;
    }
}
