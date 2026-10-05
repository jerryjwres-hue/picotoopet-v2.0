using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>只格式化 Mac Core 的 Frugal 决策，不提供 Provider 选择或启动命令。</summary>
public sealed class CodingEscalationDecisionViewModel : ObservableObject
{
    private readonly ICodingEscalationDecisionGateway? _gateway;
    private string _goalId = string.Empty;
    private string _decisionSummary = "输入 Coding Goal ID 后查看 Mac Core 的抠门仲裁结果。";
    private string _reasonSummary = "Windows 只读展示；Provider、模型、预算和执行参数均由 Mac Core 决定。";
    private string _historySummary = "历史可靠性：尚未读取。";
    private string _statusMessage = "只读：查询不会创建 Session，也不会消耗 Codex / Claude Code。";
    private bool _isBusy;

    public CodingEscalationDecisionViewModel()
    {
        RefreshCommand = new AsyncRelayCommand(
            () => LoadAsync(CancellationToken.None),
            HandleCommandError,
            () => CanRefresh);
    }

    public CodingEscalationDecisionViewModel(ICodingEscalationDecisionGateway gateway)
        : this()
    {
        _gateway = gateway ?? throw new ArgumentNullException(nameof(gateway));
    }

    public string GoalId
    {
        get => _goalId;
        set
        {
            if (SetProperty(ref _goalId, value))
            {
                RefreshCommand.NotifyCanExecuteChanged();
            }
        }
    }

    public string DecisionSummary
    {
        get => _decisionSummary;
        private set => SetProperty(ref _decisionSummary, value);
    }

    public string ReasonSummary
    {
        get => _reasonSummary;
        private set => SetProperty(ref _reasonSummary, value);
    }

    public string HistorySummary
    {
        get => _historySummary;
        private set => SetProperty(ref _historySummary, value);
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
                RefreshCommand.NotifyCanExecuteChanged();
            }
        }
    }

    public bool CanRefresh => !IsBusy && !string.IsNullOrWhiteSpace(GoalId);

    public AsyncRelayCommand RefreshCommand { get; }

    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null)
        {
            return;
        }
        if (string.IsNullOrWhiteSpace(GoalId))
        {
            StatusMessage = "请输入 Coding Goal ID。";
            return;
        }

        IsBusy = true;
        try
        {
            var record = await _gateway.GetDecisionAsync(GoalId.Trim(), cancellationToken)
                .ConfigureAwait(false);
            Apply(record);
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void Apply(CodingEscalationDecisionRecord record)
    {
        var decision = record.Decision;
        DecisionSummary = FormatDecisionSummary(decision);
        ReasonSummary = decision.ReasonCodes.Length == 0
            ? "原因：Mac Core 未返回额外原因码。"
            : "原因：" + string.Join("；", decision.ReasonCodes.Select(FormatReason));
        HistorySummary = FormatHistory(decision.ProviderHistory);
        StatusMessage =
            $"策略 {record.PolicyVersion} · 决策摘要 {ShortDigest(record.DecisionDigest)} · 只读展示";
    }

    private static string FormatDecisionSummary(CodingEscalationDecision decision)
    {
        var prefix =
            $"本地 {Math.Round(decision.LocalQualityScore):0} 分，置信带 "
            + $"{decision.ConfidenceLower:0.00}–{decision.ConfidenceUpper:0.00}；";
        return decision.ChosenProvider switch
        {
            "codex" => prefix + "选择 Codex；Claude Code 未调用。",
            "claude_code" => prefix + "选择 Claude Code；Codex 未调用。",
            _ when decision.Action == "manual_review" =>
                prefix + "进入人工复核；Codex 与 Claude Code 均未调用。",
            _ when decision.ReasonCodes.Contains(
                "NOT_ELIGIBLE_FOR_CODING_AGENT",
                StringComparer.Ordinal) =>
                prefix + "该任务不属于编码权限，因此未使用外部 Coding AI。",
            _ => prefix + "本地验证通过，因此未使用外部 Coding AI。",
        };
    }

    private static string FormatHistory(CodingProviderHistoryEvaluation[] history)
    {
        if (history.Length == 0)
        {
            return "历史可靠性：冷启动；低样本不会被当成高可信。";
        }

        return "历史可靠性：" + string.Join(
            "；",
            history.Select(item =>
            {
                var provider = FormatProvider(item.Provider);
                var suffix = item.HistorySufficient ? "样本充分" : "样本不足";
                return $"{provider} n={item.SampleSize}，95% 下界 {item.Wilson95Lower:0.00}（{suffix}）";
            }));
    }

    private static string FormatReason(string code) => code switch
    {
        "LOCAL_CONFIDENCE_SUFFICIENT" => "本地置信下界已足够",
        "PROVIDER_RETURN_VALIDATED" => "第一家 Provider 返回已通过本地验证",
        "EXTERNAL_PROVIDER_JUSTIFIED" => "外部 Provider 的保守效用达到阈值",
        "NOT_ELIGIBLE_FOR_CODING_AGENT" => "非编码任务禁止调用 Coding Agent",
        "EXTERNAL_SESSION_CAP_REACHED" => "已达到外部 Session 上限",
        "SECOND_PROVIDER_NOT_JUSTIFIED" => "第二家 Provider 不值得继续花额度",
        "NO_PROVIDER_READY" => "当前没有就绪的 Coding Provider",
        _ => code,
    };

    private static string FormatProvider(string provider) => provider switch
    {
        "codex" => "Codex",
        "claude_code" => "Claude Code",
        _ => provider,
    };

    private static string ShortDigest(string digest) =>
        string.IsNullOrWhiteSpace(digest)
            ? "unknown"
            : digest[..Math.Min(12, digest.Length)];

    private void HandleCommandError(Exception exception)
    {
        StatusMessage = exception switch
        {
            ApiException api when api.Code == "FRUGAL_DECISION_NOT_FOUND" =>
                "该 Goal 尚没有 Coding Escalation 决策。",
            ApiException api => $"读取失败：{api.Message}",
            _ => $"读取失败：{exception.GetType().Name}",
        };
    }
}
