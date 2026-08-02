using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>Control Center 的任务动作边界；错误统一写入脱敏日志。</summary>
public sealed partial class ControlCenterSession
{
    /// <summary>取消可取消任务，并发布 Mac Core 返回的最终快照。</summary>
    public async Task<TaskRecord> CancelTaskAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var coordinator = _coordinator
            ?? throw new InvalidOperationException("尚未连接 Mac Core。");
        try
        {
            var task = await coordinator.CancelTaskAsync(taskId, cancellationToken)
                .ConfigureAwait(false);
            SetStatus($"任务 {taskId} 已取消。");
            return task;
        }
        catch (Exception exception)
        {
            _logger.Error($"取消任务失败 task_id={taskId}", exception);
            SetStatus("取消任务失败；详细信息已写入脱敏日志。");
            throw;
        }
    }

    /// <summary>为失败或取消任务创建新的子任务，不重新打开原任务。</summary>
    public async Task<TaskRecord> RetryTaskAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var coordinator = _coordinator
            ?? throw new InvalidOperationException("尚未连接 Mac Core。");
        try
        {
            var task = await coordinator.RetryTaskAsync(taskId, cancellationToken)
                .ConfigureAwait(false);
            SetStatus($"已创建重试子任务 {task.TaskId}。");
            return task;
        }
        catch (Exception exception)
        {
            _logger.Error($"重试任务失败 task_id={taskId}", exception);
            SetStatus("重试任务失败；详细信息已写入脱敏日志。");
            throw;
        }
    }
}
