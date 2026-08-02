using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>展示真实连接、健康、Worker、任务和折叠诊断摘要的总览页面。</summary>
public sealed class OverviewPageViewModel : PageViewModel
{
    /// <summary>从一次会话快照创建只读总览。</summary>
    public OverviewPageViewModel(
        ControlCenterSessionSnapshot snapshot,
        string connectionText)
        : base("总览")
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        ConnectionText = connectionText;
        HealthText     = snapshot.HealthText;
        WorkerText     = FormatWorker(snapshot.State.Worker);
        WorkerReason   = FormatWorkerReason(snapshot.State.Worker);
        LatencyText    = snapshot.LatencyText;
        StatusMessage  = snapshot.StatusMessage;
        Tasks = snapshot.State.Tasks.Tasks
            .Select(task => TaskRowViewModel.FromRecord(task, snapshot.State.Worker))
            .ToArray();
    }

    /// <summary>当前连接状态。</summary>
    public string ConnectionText { get; }

    /// <summary>Mac Core 健康摘要。</summary>
    public string HealthText { get; }

    /// <summary>真实任务执行器状态。</summary>
    public string WorkerText { get; }

    /// <summary>执行器不可用原因。</summary>
    public string WorkerReason { get; }

    /// <summary>折叠诊断区显示的 p95 延迟。</summary>
    public string LatencyText { get; }

    /// <summary>当前会话状态说明。</summary>
    public string StatusMessage { get; }

    /// <summary>真实任务快照。</summary>
    public IReadOnlyList<TaskRowViewModel> Tasks { get; }

    /// <summary>当前任务数量。</summary>
    public int TaskCount => Tasks.Count;

    /// <summary>因 Worker 不可用而等待的任务数量。</summary>
    public int WaitingForWorkerCount => Tasks.Count(task => task.IsWaitingForWorker);

    private static string FormatWorker(WorkerSnapshot worker)
    {
        if (worker.Available)
        {
            return string.IsNullOrWhiteSpace(worker.WorkerId)
                ? "在线"
                : $"在线 · {worker.WorkerId}";
        }
        return worker.State switch
        {
            "starting"     => "启动中",
            "degraded"     => "降级",
            "offline"      => "离线",
            "not_deployed" => "未部署",
            _              => "不可用",
        };
    }

    private static string FormatWorkerReason(WorkerSnapshot worker) => worker.Reason switch
    {
        "worker_runtime_not_installed" => "Queued 任务不会自动执行。",
        _ when string.IsNullOrWhiteSpace(worker.Reason) => "服务端未提供原因。",
        _ => worker.Reason,
    };
}
