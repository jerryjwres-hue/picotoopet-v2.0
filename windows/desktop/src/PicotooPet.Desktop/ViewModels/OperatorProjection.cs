using System.Globalization;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>简单模式只读任务卡；所有字段都来自既有耐久任务事实。</summary>
public sealed record OperatorTaskCard(
    string TaskId,
    string Title,
    string StageText,
    string StatusText,
    DateTimeOffset UpdatedAt,
    string UpdatedAtText,
    string? ErrorText,
    bool HasResult);

/// <summary>把既有 Core/Worker/任务快照投影为普通用户可读的五入口状态，不建立第二套持久化。</summary>
public sealed record OperatorProjection(
    IReadOnlyList<OperatorTaskCard> PendingReview,
    IReadOnlyList<OperatorTaskCard> InProgress,
    IReadOnlyList<OperatorTaskCard> Completed,
    string CoreStatus,
    string WorkerStatus,
    string WindowsStatus,
    string SystemSummary)
{
    private static readonly HashSet<string> ReviewStatuses = new(StringComparer.OrdinalIgnoreCase)
    {
        "NeedsHuman",
        "NeedsDeepAI",
        "AwaitingApproval",
        "PendingApproval",
        "ApprovalRequired",
    };

    private static readonly HashSet<string> TerminalStatuses = new(StringComparer.OrdinalIgnoreCase)
    {
        "Completed",
        "Failed",
        "Cancelled",
        "Rejected",
    };

    /// <summary>从一次会话快照确定性生成简单模式投影。</summary>
    public static OperatorProjection FromSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);

        var cards = snapshot.State.Tasks.Tasks
            .OrderByDescending(task => task.UpdatedAt)
            .ThenBy(task => task.TaskId, StringComparer.Ordinal)
            .Select(ToCard)
            .ToArray();

        var pendingReview = cards
            .Where(card => IsReviewStatus(GetSourceStatus(snapshot, card.TaskId)))
            .ToArray();
        var completed = cards
            .Where(card => TerminalStatuses.Contains(GetSourceStatus(snapshot, card.TaskId)))
            .ToArray();
        var inProgress = cards
            .Where(card => !IsReviewStatus(GetSourceStatus(snapshot, card.TaskId))
                           && !TerminalStatuses.Contains(GetSourceStatus(snapshot, card.TaskId)))
            .ToArray();

        var coreStatus = snapshot.State.Connection.State switch
        {
            ConnectionState.Online => "在线",
            ConnectionState.Connecting => "连接中",
            ConnectionState.Reconnecting => "正在重连",
            ConnectionState.AuthenticationFailed => "认证失败",
            ConnectionState.Faulted => "连接故障",
            _ => "离线",
        };
        var worker = snapshot.State.Worker;
        var workerStatus = worker.Available
            ? string.Equals(worker.Reason, "idle", StringComparison.OrdinalIgnoreCase)
                ? "在线 · 空闲"
                : $"在线 · {FriendlyWorkerReason(worker.Reason)}"
            : FriendlyWorkerReason(worker.Reason);
        var summary = coreStatus == "在线" && worker.Available
            ? "系统运行正常"
            : "部分执行能力不可用，请查看系统状态";

        return new OperatorProjection(
            pendingReview,
            inProgress,
            completed,
            coreStatus,
            workerStatus,
            "正常",
            summary);
    }

    private static string GetSourceStatus(
        ControlCenterSessionSnapshot snapshot,
        string taskId) =>
        snapshot.State.Tasks.Tasks.First(task => task.TaskId == taskId).Status;

    private static bool IsReviewStatus(string status) => ReviewStatuses.Contains(status);

    private static OperatorTaskCard ToCard(TaskRecord task)
    {
        var title = task.TaskType switch
        {
            "system.diagnostic_snapshot" => "系统诊断",
            "system.noop" => "系统任务",
            "business.local_intelligence.v1" => "业务数据分析",
            "creative.content_plan.v1" => "内容方案",
            _ => "任务",
        };
        var statusText = task.Status switch
        {
            "Queued" => "等待执行",
            "Running" => "处理中",
            "Completed" => "已完成",
            "Failed" => "失败",
            "Cancelled" => "已取消",
            "Rejected" => "已拒绝",
            "NeedsHuman" => "等待人工审核",
            "NeedsDeepAI" => "等待深度 AI 授权",
            "AwaitingApproval" => "等待审核",
            _ => task.Status,
        };
        var stageText = task.Status switch
        {
            "Queued" => "已进入任务队列",
            "Running" => "正在由执行器处理",
            "Completed" => "处理完成",
            "Failed" => "执行失败，需要查看详情",
            "Cancelled" => "任务已停止",
            "Rejected" => "任务已终止",
            "NeedsHuman" => "需要你的决定",
            "NeedsDeepAI" => "需要你的付费 AI 授权",
            "AwaitingApproval" => "等待你的审核",
            _ => "状态已更新",
        };
        var error = string.IsNullOrWhiteSpace(task.ErrorMessage)
            ? null
            : task.ErrorMessage;
        return new OperatorTaskCard(
            task.TaskId,
            title,
            stageText,
            statusText,
            task.UpdatedAt,
            task.UpdatedAt.LocalDateTime.ToString(
                "yyyy-MM-dd HH:mm",
                CultureInfo.InvariantCulture),
            error,
            !string.IsNullOrWhiteSpace(task.ResultId));
    }

    private static string FriendlyWorkerReason(string reason) => reason switch
    {
        "idle" => "空闲",
        "executing" => "正在执行任务",
        "not_deployed" => "Worker 未部署",
        "offline" => "Worker 离线",
        "degraded" => "Worker 状态异常",
        _ when string.IsNullOrWhiteSpace(reason) => "状态未知",
        _ => reason,
    };
}
