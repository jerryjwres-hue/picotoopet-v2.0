using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>桌宠只读视觉状态；不写回 Core、Worker、任务或审批事实。</summary>
public enum AssistantPetMode
{
    Resting,
    Working,
    Waiting,
    Offline,
    Error,
}

/// <summary>把既有会话事实投影成桌宠可见状态，不建立第二套持久化。</summary>
public sealed record AssistantPetPresentation(
    AssistantPetMode Mode,
    string Title,
    string Detail,
    string AssetKey)
{
    // 审核状态只表达“等待用户决定”，不能被桌宠解释成正在执行。
    private static readonly HashSet<string> ReviewStatuses = new(StringComparer.OrdinalIgnoreCase)
    {
        "NeedsHuman",
        "NeedsDeepAI",
        "AwaitingApproval",
        "PendingApproval",
        "ApprovalRequired",
    };

    // 终态不再驱动 Working；历史结果仍由既有任务/结果页面负责展示。
    private static readonly HashSet<string> TerminalStatuses = new(StringComparer.OrdinalIgnoreCase)
    {
        "Completed",
        "Failed",
        "Cancelled",
        "Rejected",
    };

    /// <summary>从单次真实 Session 快照确定性生成桌宠展示。</summary>
    public static AssistantPetPresentation FromSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);

        var connectionState = snapshot.State.Connection.State;
        if (connectionState is ConnectionState.AuthenticationFailed or ConnectionState.Faulted)
        {
            return new AssistantPetPresentation(
                AssistantPetMode.Error,
                "需要关注",
                "连接异常，请查看系统状态",
                "idle");
        }

        var worker = snapshot.State.Worker;
        if (connectionState != ConnectionState.Online || !worker.Available)
        {
            return new AssistantPetPresentation(
                AssistantPetMode.Offline,
                "已离线",
                "当前执行能力不可用",
                "offline");
        }

        var tasks = snapshot.State.Tasks.Tasks;
        var activeCount = tasks.Count(task =>
            !TerminalStatuses.Contains(task.Status)
            && !ReviewStatuses.Contains(task.Status));
        var reviewCount = tasks.Count(task => ReviewStatuses.Contains(task.Status));

        // 实际执行优先于同时存在的待审核任务，避免把忙碌 Worker 错画成空闲。
        if (activeCount > 0)
        {
            var detail = reviewCount > 0
                ? $"正在处理 {activeCount} 个任务 · 另有 {reviewCount} 个待审核"
                : $"正在处理 {activeCount} 个任务";
            return new AssistantPetPresentation(
                AssistantPetMode.Working,
                "工作中",
                detail,
                "working");
        }

        if (reviewCount > 0)
        {
            return new AssistantPetPresentation(
                AssistantPetMode.Waiting,
                "等你确认",
                $"有 {reviewCount} 个任务待你审核",
                "idle");
        }

        return new AssistantPetPresentation(
            AssistantPetMode.Resting,
            "休息中",
            "在线 · 当前空闲",
            "resting");
    }
}
