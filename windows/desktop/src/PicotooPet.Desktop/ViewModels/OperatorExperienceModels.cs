using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>阿拉斯加助手仅表达当前操作体验状态，不产生新的业务事实。</summary>
public enum OperatorAssistantVisualState
{
    Working,          // 在线工作：Core/Worker 在线，并且已有真实活动任务。
    Resting,          // 在线休息：Core/Worker 在线，但当前没有活动任务。
    OfflineSleeping,  // 掉线睡眠：Worker 或控制链不可用，明确显示为离线。
}

/// <summary>把既有 Core/Worker/任务事实收敛成唯一助手视觉状态，避免页面之间状态打架。</summary>
public static class OperatorAssistantStateResolver
{
    /// <summary>供确定性测试和 UI 规则复用的最小状态解析函数。</summary>
    public static OperatorAssistantVisualState Resolve(
        bool coreOnline,
        bool workerOnline,
        bool hasActiveTask)
    {
        if (!coreOnline || !workerOnline)
        {
            return OperatorAssistantVisualState.OfflineSleeping;
        }

        return hasActiveTask
            ? OperatorAssistantVisualState.Working
            : OperatorAssistantVisualState.Resting;
    }

    /// <summary>只读取现有快照；不创建第二份状态源，也不推断虚假的进度。</summary>
    public static OperatorAssistantVisualState FromSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);

        var coreOnline   = snapshot.State.Connection.State == ConnectionState.Online;
        var workerOnline = snapshot.State.Worker.Available
            && string.Equals(snapshot.State.Worker.State, "online", StringComparison.OrdinalIgnoreCase);
        var hasActiveTask = OperatorProjection.FromSnapshot(snapshot).InProgress.Count > 0;

        return Resolve(coreOnline, workerOnline, hasActiveTask);
    }

    /// <summary>返回稳定的绑定键，避免 XAML 依赖本地化文案判断状态。</summary>
    public static string ToKey(OperatorAssistantVisualState state) => state switch
    {
        OperatorAssistantVisualState.Working         => "Working",
        OperatorAssistantVisualState.Resting         => "Resting",
        OperatorAssistantVisualState.OfflineSleeping => "OfflineSleeping",
        _                                             => "OfflineSleeping",
    };

    /// <summary>返回面向用户的短标题。</summary>
    public static string ToTitle(OperatorAssistantVisualState state) => state switch
    {
        OperatorAssistantVisualState.Working         => "在线工作中",
        OperatorAssistantVisualState.Resting         => "休息中",
        OperatorAssistantVisualState.OfflineSleeping => "已掉线",
        _                                             => "已掉线",
    };

    /// <summary>返回与状态一致的辅助说明，不泄露内部工程字段。</summary>
    public static string ToSubtitle(OperatorAssistantVisualState state) => state switch
    {
        OperatorAssistantVisualState.Working         => "正在陪你处理真实任务",
        OperatorAssistantVisualState.Resting         => "暂时空闲，放松一下",
        OperatorAssistantVisualState.OfflineSleeping => "连接恢复后会再次醒来",
        _                                             => "连接恢复后会再次醒来",
    };
}

/// <summary>一个可展示工作组件的固定产品描述；不包含任意执行入口。</summary>
public sealed record OperatorWidgetDescriptor(
    string Id,
    string Title,
    string Description,
    string Glyph,
    bool IsAvailable,
    string AvailabilityText);

/// <summary>首页工作组件的运行时展示卡；状态只来自已有事实或明确的未接入状态。</summary>
public sealed record OperatorWidgetCard(
    string Id,
    string Title,
    string Description,
    string Glyph,
    bool IsAvailable,
    string StatusText,
    string ToneKey);

/// <summary>组件管理窗口使用的只读选项，不允许注入组件类型或执行参数。</summary>
public sealed record OperatorWidgetOption(
    string Id,
    string Title,
    string Description,
    bool IsVisible,
    bool IsAvailable,
    string AvailabilityText)
{
    public string ToggleText => IsVisible ? "隐藏" : "添加";
    public string VisibilityText => IsVisible ? "已显示" : "未显示";
}

/// <summary>固定、闭集的组件目录；未来新增组件必须通过代码评审扩展此目录。</summary>
public static class OperatorWidgetCatalog
{
    private static readonly OperatorWidgetDescriptor[] DefaultWidgets =
    {
        new(
            "search-insight",
            "搜索洞察",
            "为未来有界 Search / 来源采集适配器预留的只读洞察入口。",
            "⌕",
            IsAvailable: false,
            "尚未接入"),
        new(
            "comment-analysis",
            "数据评论分析",
            "聚合既有本地智能分析结果，不在 Windows 保存 Provider 凭据。",
            "▥",
            IsAvailable: true,
            "可配置"),
        new(
            "video-creation",
            "视频创作状态",
            "展示既有视频生产任务的排队、运行和完成状态。",
            "▶",
            IsAvailable: true,
            "可配置"),
        new(
            "content-generation",
            "内容生成",
            "展示既有 Creative Intelligence 内容任务状态。",
            "✎",
            IsAvailable: true,
            "已接入"),
        new(
            "result-optimization",
            "结果优化",
            "汇总已有结果与质量治理事实，不自动触发 Promotion。",
            "✓",
            IsAvailable: true,
            "已接入"),
    };

    /// <summary>返回独立只读副本，调用方不能修改全局目录。</summary>
    public static IReadOnlyList<OperatorWidgetDescriptor> CreateDefault() =>
        Array.AsReadOnly(DefaultWidgets.ToArray());

    /// <summary>只承认目录中已登记的固定 ID。</summary>
    public static bool Contains(string widgetId) =>
        DefaultWidgets.Any(widget => string.Equals(widget.Id, widgetId, StringComparison.Ordinal));
}

/// <summary>只保存显示顺序和隐藏项；未知 ID 在加载时一律丢弃。</summary>
public sealed record OperatorWidgetLayout(
    IReadOnlyList<string> WidgetIds,
    IReadOnlyList<string> HiddenWidgetIds)
{
    /// <summary>按照用户合法顺序去重，再补齐固定目录；未知组件 fail closed。</summary>
    public static OperatorWidgetLayout Normalize(
        IEnumerable<string>? requestedWidgetIds,
        IEnumerable<string>? hiddenWidgetIds = null)
    {
        var catalogIds = OperatorWidgetCatalog.CreateDefault()
            .Select(widget => widget.Id)
            .ToArray();
        var knownIds = new HashSet<string>(catalogIds, StringComparer.Ordinal);
        var ordered  = new List<string>(catalogIds.Length);
        var seen     = new HashSet<string>(StringComparer.Ordinal);

        if (requestedWidgetIds is not null)
        {
            foreach (var widgetId in requestedWidgetIds)
            {
                if (knownIds.Contains(widgetId) && seen.Add(widgetId))
                {
                    ordered.Add(widgetId);
                }
            }
        }

        foreach (var widgetId in catalogIds)
        {
            if (seen.Add(widgetId))
            {
                ordered.Add(widgetId);
            }
        }

        var hidden = hiddenWidgetIds is null
            ? Array.Empty<string>()
            : hiddenWidgetIds
                .Where(knownIds.Contains)
                .Distinct(StringComparer.Ordinal)
                .ToArray();

        return new OperatorWidgetLayout(ordered.AsReadOnly(), Array.AsReadOnly(hidden));
    }
}
