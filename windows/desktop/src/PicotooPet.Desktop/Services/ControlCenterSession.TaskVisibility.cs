using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>任务安全删除/恢复与 Research 固定结果读取。</summary>
public sealed partial class ControlCenterSession
{
    /// <summary>
    /// 安全删除显式选择的任务。活动任务先请求取消并观察终态，再由 Mac Core 标记隐藏。
    /// </summary>
    public async Task<TaskVisibilityBatchResponse> HideTasksAsync(
        IReadOnlyList<string> taskIds,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var ids = ValidateTaskIds(taskIds);
        try
        {
            await using var client = CreateTaskLifecycleClient();
            var first = await client.HideTasksAsync(ids, cancellationToken)
                .ConfigureAwait(false);
            var outcomes = new List<TaskVisibilityOutcome>(first.Outcomes.Count);

            foreach (var outcome in first.Outcomes)
            {
                if (outcome.Task is not null)
                {
                    _stateStore.TaskStore.UpsertTask(outcome.Task);
                }
                if (!outcome.Success || !outcome.PendingCancel)
                {
                    outcomes.Add(outcome);
                    continue;
                }

                var observation = await ObserveTaskAsync(
                    outcome.TaskId,
                    cancellationToken).ConfigureAwait(false);
                if (!IsTerminal(observation.Task.Status))
                {
                    outcomes.Add(outcome with
                    {
                        Message = "取消仍在处理中；任务尚未从普通列表隐藏。",
                    });
                    continue;
                }

                var hidden = await client.HideTaskAsync(
                    outcome.TaskId,
                    cancellationToken).ConfigureAwait(false);
                if (hidden.Task is not null)
                {
                    _stateStore.TaskStore.UpsertTask(hidden.Task);
                }
                outcomes.Add(hidden);
            }

            SetStatus($"已处理 {outcomes.Count} 个任务的安全删除请求。");
            return new TaskVisibilityBatchResponse(outcomes);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            _logger.Error("批量安全删除任务失败", exception);
            const string message = "安全删除失败；任务仍由 Mac Core 保存。";
            SetStatus(message);
            throw new InvalidOperationException(message, exception);
        }
    }

    /// <summary>恢复显式选择的已删除任务；原执行状态和结果保持不变。</summary>
    public async Task<TaskVisibilityBatchResponse> RestoreTasksAsync(
        IReadOnlyList<string> taskIds,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var ids = ValidateTaskIds(taskIds);
        try
        {
            await using var client = CreateTaskLifecycleClient();
            var response = await client.RestoreTasksAsync(ids, cancellationToken)
                .ConfigureAwait(false);
            foreach (var outcome in response.Outcomes)
            {
                if (outcome.Task is not null)
                {
                    _stateStore.TaskStore.UpsertTask(outcome.Task);
                }
            }
            SetStatus($"已处理 {response.Outcomes.Count} 个任务的恢复请求。");
            return response;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            _logger.Error("批量恢复任务失败", exception);
            const string message = "恢复任务失败；已删除记录仍完整保留。";
            SetStatus(message);
            throw new InvalidOperationException(message, exception);
        }
    }

    /// <summary>读取 research.search 的固定只读结果合同。</summary>
    public async Task<ResearchSearchResult> GetResearchResultAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(taskId);
        try
        {
            await using var client = CreateTaskLifecycleClient();
            return await client.GetResearchResultAsync(taskId, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            _logger.Error($"读取 Research 结果失败 task_id={taskId}", exception);
            const string message = "Research 结果暂时无法安全显示。";
            SetStatus(message);
            throw new InvalidOperationException(message, exception);
        }
    }

    private TaskLifecycleClient CreateTaskLifecycleClient()
    {
        string macBaseUrl;
        lock (_snapshotGate)
        {
            macBaseUrl = _macBaseUrl;
        }
        var token = _tokenStore.Read();
        ValidateConnectionInput(macBaseUrl, token ?? string.Empty, out var baseUri);
        return new TaskLifecycleClient(
            MacCoreClientOptions.CreateDefault(baseUri, token!));
    }

    private static string[] ValidateTaskIds(IReadOnlyList<string> taskIds)
    {
        ArgumentNullException.ThrowIfNull(taskIds);
        if (taskIds.Count is < 1 or > 100)
        {
            throw new ArgumentOutOfRangeException(
                nameof(taskIds),
                "一次必须选择 1 到 100 个任务。");
        }
        var ids = taskIds.Select(taskId => taskId?.Trim() ?? string.Empty).ToArray();
        if (ids.Any(string.IsNullOrWhiteSpace) || ids.Distinct(StringComparer.Ordinal).Count() != ids.Length)
        {
            throw new ArgumentException("任务 ID 不能为空或重复。", nameof(taskIds));
        }
        return ids;
    }
}
