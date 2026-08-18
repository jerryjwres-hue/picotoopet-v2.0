using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>结构化诊断页；仅显示失败元数据、状态和 Trace ID，不拉取日志正文。</summary>
public sealed class DiagnosticsPageViewModel : PageViewModel
{
    private readonly ControlCenterSession? _session;
    private IReadOnlyList<AutomationDiagnosticFact> _facts = Array.Empty<AutomationDiagnosticFact>();
    private AutomationDiagnosticFact? _selectedFact;
    private string _statusMessage = "诊断仅使用结构化安全事实。";
    private bool _isBusy;

    public DiagnosticsPageViewModel(ControlCenterSession session) : base("诊断")
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    private DiagnosticsPageViewModel(IReadOnlyList<AutomationDiagnosticFact> facts) : base("诊断")
    {
        Facts = facts;
        SelectedFact = facts.Count > 0 ? facts[0] : null;
    }

    public IReadOnlyList<AutomationDiagnosticFact> Facts
    {
        get => _facts;
        private set => SetProperty(ref _facts, value);
    }

    public AutomationDiagnosticFact? SelectedFact
    {
        get => _selectedFact;
        set => SetProperty(ref _selectedFact, value);
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
                RaisePropertyChanged(nameof(CanRefresh));
                RaisePropertyChanged(nameof(RefreshActionReason));
            }
        }
    }

    // 操作可用性 --------------------------------------------------------------
    public bool CanRefresh => !IsBusy;

    public string RefreshActionReason => IsBusy
        ? "诊断事实正在刷新，请稍候。"
        : "重新读取结构化诊断事实；不会读取日志正文、Token 或用户文件。";

    public static DiagnosticsPageViewModel CreateForSmokeTest(
        IReadOnlyList<AutomationDiagnosticFact> facts) => new(facts);

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy)
        {
            return;
        }

        var session = _session ?? throw new InvalidOperationException("Smoke test 模式不能访问网络。");
        IsBusy = true;
        try
        {
            var snapshot = await session.GetAutomationDiagnosticsAsync(cancellationToken).ConfigureAwait(false);
            Facts = snapshot.Facts;
            SelectedFact = Facts.Count > 0 ? Facts[0] : null;
            StatusMessage = Facts.Count == 0
                ? "当前没有需要关注的工作流诊断事实。"
                : $"已加载 {Facts.Count} 条结构化诊断事实；未读取日志正文。";
        }
        finally
        {
            IsBusy = false;
        }
    }
}