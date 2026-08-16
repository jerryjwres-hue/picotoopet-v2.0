using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>简单模式允许选择的有限任务类型。</summary>
public enum OperatorTaskKind
{
    SystemDiagnostic,
    BusinessAnalysis,
    ContentPlan,
    WebResearch,
}

/// <summary>任务向导固定选项；不可用能力必须明确禁用，而不是伪执行。</summary>
public sealed record OperatorTaskOption(
    OperatorTaskKind Kind,
    string Title,
    string Description,
    bool IsAvailable,
    string AvailabilityText,
    NavigationRoute? HandoffRoute = null);

/// <summary>受控新任务向导；只执行固定安全任务或进入现有受控业务页面。</summary>
public sealed class NewTaskWizardViewModel : ObservableObject
{
    private readonly ControlCenterSession? _session;
    private OperatorTaskOption? _selectedOption;
    private string _objective = string.Empty;
    private string _statusMessage = "先选择你想做什么。";
    private bool _isBusy;
    private int _step = 1;

    public NewTaskWizardViewModel(
        ControlCenterSession session,
        ControlCenterSessionSnapshot snapshot)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        Options = BuildOptions(snapshot);
        _selectedOption = Options.FirstOrDefault(option => option.IsAvailable);
    }

    private NewTaskWizardViewModel()
    {
        Options = new OperatorTaskOption[]
        {
            new(OperatorTaskKind.SystemDiagnostic, "系统诊断", "检查 Core、Worker 和队列状态。", true, "可用"),
            new(OperatorTaskKind.BusinessAnalysis, "业务数据分析", "进入现有业务自动化页选择数据源。", true, "可用", NavigationRoute.BusinessAutomation),
            new(OperatorTaskKind.ContentPlan, "内容方案", "进入现有业务自动化页，从已分析资料继续内容方案。", true, "可用", NavigationRoute.BusinessAutomation),
            new(OperatorTaskKind.WebResearch, "网络调研", "通过 Mac Research Gateway 执行只读网络搜索。", true, "可用"),
        };
        _selectedOption = Options[0];
    }

    public IReadOnlyList<OperatorTaskOption> Options { get; }

    public OperatorTaskOption? SelectedOption
    {
        get => _selectedOption;
        set
        {
            if (SetProperty(ref _selectedOption, value))
            {
                StatusMessage = value is null
                    ? "请选择任务类型。"
                    : value.IsAvailable
                        ? value.Description
                        : value.AvailabilityText;
                RaiseState();
            }
        }
    }

    public string Objective
    {
        get => _objective;
        set
        {
            if (SetProperty(ref _objective, value))
            {
                RaisePropertyChanged(nameof(CanSubmit));
            }
        }
    }

    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetProperty(ref _statusMessage, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaiseState();
            }
        }
    }

    public int Step
    {
        get => _step;
        private set
        {
            if (SetProperty(ref _step, value))
            {
                RaiseState();
            }
        }
    }

    public bool CanGoBack => !IsBusy && Step > 1;
    public bool CanGoNext => !IsBusy && Step == 1 && SelectedOption?.IsAvailable == true;
    public bool CanSubmit =>
        !IsBusy
        && Step == 2
        && SelectedOption?.IsAvailable == true
        && (SelectedOption.Kind != OperatorTaskKind.WebResearch || !string.IsNullOrWhiteSpace(Objective));
    public string SubmitText => SelectedOption?.HandoffRoute is null ? "开始任务" : "继续到受控页面";
    public NavigationRoute? RequestedRoute { get; private set; }
    public string? CreatedTaskId { get; private set; }

    public void Next()
    {
        if (!CanGoNext)
        {
            return;
        }
        Step = 2;
        StatusMessage = SelectedOption?.Kind switch
        {
            OperatorTaskKind.SystemDiagnostic =>
                "系统诊断不需要额外参数；确认后会创建固定诊断任务。",
            OperatorTaskKind.WebResearch =>
                "输入要调研的关键词或问题；本版本只执行只读搜索，不会发帖、回复、点赞或关注。",
            _ => "可以写一句你的目标；下一步仍会进入现有受控业务页面选择真实数据。",
        };
    }

    public void Back()
    {
        if (!CanGoBack)
        {
            return;
        }
        Step = 1;
        StatusMessage = "重新选择你想做什么。";
    }

    public async Task<bool> SubmitAsync(CancellationToken cancellationToken)
    {
        if (!CanSubmit || SelectedOption is null)
        {
            return false;
        }

        if (SelectedOption.HandoffRoute is NavigationRoute route)
        {
            RequestedRoute = route;
            StatusMessage = "将打开现有受控业务页面；不会伪造任务或绕过数据源选择。";
            return true;
        }

        if (_session is null)
        {
            StatusMessage = "当前没有可用的 Mac Core 会话。";
            return false;
        }

        IsBusy = true;
        try
        {
            if (SelectedOption.Kind == OperatorTaskKind.SystemDiagnostic)
            {
                var task = await _session.CreateDiagnosticSnapshotAsync(
                    $"operator-diagnostic-{Guid.NewGuid():N}",
                    cancellationToken);
                CreatedTaskId = task.TaskId;
                StatusMessage = "诊断任务已创建，可在“进行中”查看状态。";
                return true;
            }

            if (SelectedOption.Kind == OperatorTaskKind.WebResearch)
            {
                // Windows 只提交固定 research.search 抽象任务；真正工具调用只发生在 Mac Worker。
                var request = new TaskCreateRequest(
                    "research.search",
                    new Dictionary<string, object?>
                    {
                        ["query"] = Objective.Trim(),
                        ["limit"] = 5,
                    },
                    Priority: 60,
                    ResourceTag: "research-gateway",
                    MaxAttempts: 2,
                    TimeoutSeconds: 120,
                    CloudPolicy: "local_only");
                var task = await _session.CreateTaskAsync(request, cancellationToken);
                CreatedTaskId = task.TaskId;
                StatusMessage = "网络调研任务已创建，Mac Research Gateway 正在只读执行。";
                return true;
            }

            StatusMessage = "当前选项还没有安全的直接执行映射。";
            return false;
        }
        finally
        {
            IsBusy = false;
        }
    }

    public static NewTaskWizardViewModel CreateForSmokeTest() => new();

    private static OperatorTaskOption[] BuildOptions(
        ControlCenterSessionSnapshot snapshot)
    {
        var supported = snapshot.State.Worker.SupportedTaskTypes;
        var diagnostic = supported.Contains(
            "system.diagnostic_snapshot",
            StringComparer.Ordinal);
        var business = supported.Contains(
            "business.local_intelligence.v1",
            StringComparer.Ordinal);
        var creative = supported.Contains(
            "creative.content_plan.v1",
            StringComparer.Ordinal);
        var research = supported.Contains(
            "research.search",
            StringComparer.Ordinal);

        return new OperatorTaskOption[]
        {
            new(
                OperatorTaskKind.SystemDiagnostic,
                "系统诊断",
                "检查 Core、Worker 和队列状态。",
                diagnostic,
                diagnostic ? "可用" : "当前 Worker 不支持系统诊断"),
            new(
                OperatorTaskKind.BusinessAnalysis,
                "业务数据分析",
                "进入现有业务自动化页选择数据源并使用本地智能分析。",
                business,
                business ? "可用" : "当前 Worker 不支持业务数据分析",
                business ? NavigationRoute.BusinessAutomation : null),
            new(
                OperatorTaskKind.ContentPlan,
                "内容方案",
                "进入现有业务自动化页，从合格分析结果继续内容方案。",
                creative,
                creative ? "可用" : "当前 Worker 不支持内容方案",
                creative ? NavigationRoute.BusinessAutomation : null),
            new(
                OperatorTaskKind.WebResearch,
                "网络调研",
                "通过 Mac Research Gateway 执行只读网络搜索；结果仍进入现有任务/结果体系。",
                research,
                research ? "可用" : "Mac Research Gateway 尚未连接到 Worker"),
        };
    }

    private void RaiseState()
    {
        RaisePropertyChanged(nameof(CanGoBack));
        RaisePropertyChanged(nameof(CanGoNext));
        RaisePropertyChanged(nameof(CanSubmit));
        RaisePropertyChanged(nameof(SubmitText));
    }
}
