using System.Collections.ObjectModel;
using System.Text.Json;
using PicotooPet.Desktop.Core.OwnerReview;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>单字段审核行：来源、可信等级与 CONFIRM / CORRECT / UNKNOWN 决定。</summary>
public sealed class OwnerReviewFieldRowViewModel : ObservableObject
{
    private readonly OwnerReviewFieldState _state;
    private readonly Action _changed;

    internal OwnerReviewFieldRowViewModel(
        OwnerReviewFieldState state,
        IReadOnlyDictionary<string, OwnerEvidenceSummary> evidence,
        Action changed)
    {
        _state = state;
        _changed = changed;
        var proposal = state.Proposal;
        FieldPath = proposal.FieldPath;
        Label = OwnerReviewLabels.Field(proposal.FieldPath);
        StatusText = OwnerReviewLabels.Status(proposal.Status);
        ValueText = proposal.Value is { } value && value.ValueKind != JsonValueKind.Null
            ? Render(value)
            : "（Core 没有给出建议值）";
        evidence.TryGetValue(proposal.EvidenceId ?? string.Empty, out var source);
        SourceText = source is null
            ? "来源：无（需要人工补充，系统不使用默认值）"
            : $"来源：{source.Source} · 证据 {source.EvidenceId}";
        TrustText = source is null
            ? "可信等级：无"
            : $"可信等级：{source.TrustLevel} · {OwnerReviewLabels.Authority(proposal.AuthorityKind)}"
              + (source.PhotoBytesVerified ? " · 照片字节已由 Core 校验" : " · 照片字节未经 Core 校验（仅主人声明）");
        CanConfirm = state.CanConfirm;
    }

    public string FieldPath { get; }
    public string Label { get; }
    public string StatusText { get; }
    public string ValueText { get; }
    public string SourceText { get; }
    public string TrustText { get; }
    public bool CanConfirm { get; }
    public bool IsIdentity => _state.Group == OwnerReviewFieldGroup.IdentityAndSceneFacts;

    public bool IsConfirm
    {
        get => _state.Decision == OwnerReviewWire.DecisionConfirm;
        set { if (value) Choose(OwnerReviewWire.DecisionConfirm); }
    }

    public bool IsCorrect
    {
        get => _state.Decision == OwnerReviewWire.DecisionCorrect;
        set { if (value) Choose(OwnerReviewWire.DecisionCorrect); }
    }

    public bool IsUnknown
    {
        get => _state.Decision == OwnerReviewWire.DecisionUnknown;
        set { if (value) Choose(OwnerReviewWire.DecisionUnknown); }
    }

    public string CorrectedText
    {
        get => _state.CorrectedText;
        set
        {
            if (_state.CorrectedText == value) return;
            _state.CorrectedText = value;
            // 修改更正值同样会让既有预览失效。
            _changed();
            RaisePropertyChanged();
        }
    }

    public string? Decision => _state.Decision;

    private void Choose(string decision)
    {
        _state.Decision = decision;
        RaisePropertyChanged(nameof(IsConfirm));
        RaisePropertyChanged(nameof(IsCorrect));
        RaisePropertyChanged(nameof(IsUnknown));
        RaisePropertyChanged(nameof(Decision));
        _changed();
    }

    private static string Render(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.String => value.GetString() ?? string.Empty,
        JsonValueKind.Array => string.Join("；", value.EnumerateArray().Select(Render)),
        _ => value.GetRawText(),
    };
}

/// <summary>中文标签集中处。</summary>
internal static class OwnerReviewLabels
{
    public static string Field(string path) => path switch
    {
        "subject_lock.species" => "物种",
        "subject_lock.breed_or_type" => "品种 / 类型",
        "subject_lock.coat_or_appearance" => "毛色与外貌",
        "subject_lock.distinguishing_marks" => "显著特征（鼻纹、眉斑、耳朵）",
        "subject_lock.subject_id" => "主体标识",
        "pose_lock.body_pose" => "身体姿态",
        "pose_lock.head_direction" => "头部朝向",
        "pose_lock.support_surface" => "支撑面",
        "scene_lock.environment" => "场景环境",
        "scene_lock.lighting" => "光线",
        "scene_lock.temporary_accessories" => "场景内临时配件（恢复圈、围巾）",
        "camera_lock.allowed_framings" => "允许的取景",
        "allowed_events" => "允许的动作（创作意图）",
        _ => path,
    };

    public static string Status(string status) => status switch
    {
        OwnerReviewWire.StatusExplicit => "来源明确",
        OwnerReviewWire.StatusUnknown => "来源未知（需人工补充）",
        OwnerReviewWire.StatusConflict => "来源冲突（需人工裁决）",
        _ => status,
    };

    public static string Authority(string? authority) => authority switch
    {
        OwnerReviewWire.AuthorityOwnerAttestation => "主人声明",
        OwnerReviewWire.AuthorityApprovedReference => "已批准参考",
        OwnerReviewWire.AuthorityCreativeIntent => "主人创作意图",
        _ => "权威来源未标注",
    };

    public static string Block(OwnerReviewCommitBlock block) => block switch
    {
        OwnerReviewCommitBlock.None => "可以提交",
        OwnerReviewCommitBlock.NoPreview => "请先生成预览。",
        OwnerReviewCommitBlock.PreviewStale => "决定已变化，预览已失效，请重新预览。",
        OwnerReviewCommitBlock.NeedsHuman => "Core 预览为 NEEDS_HUMAN，不能提交；请补全或更正字段后重新预览。",
        OwnerReviewCommitBlock.NotExplicitlyConfirmed => "请勾选“我已逐项核对预览”后再提交。",
        OwnerReviewCommitBlock.AlreadyCommitted => "本次审核已提交。",
        _ => block.ToString(),
    };
}

/// <summary>主人结构化审核面板的视图模型：加载提案 → 逐字段决定 → 预览 → 显式提交。</summary>
public sealed class OwnerReviewViewModel : ObservableObject
{
    private readonly OwnerReviewClient _client;
    private readonly IOwnerReviewCredentialStore _credentials;
    private OwnerReviewDraft? _draft;
    private string _goalId = string.Empty;
    private string _statusText = "请输入 Goal ID 并加载提案。";
    private string _errorText = string.Empty;
    private string _previewSummary = string.Empty;
    private string _commitSummary = string.Empty;
    private bool _ownerConfirmed;
    private bool _staticPetStorySelected;
    private bool _busy;

    private readonly bool _livePinnedSsh;

    public OwnerReviewViewModel(
        OwnerReviewClient client,
        IOwnerReviewCredentialStore credentials,
        bool livePinnedSsh = false)
    {
        _client = client;
        _credentials = credentials;
        _livePinnedSsh = livePinnedSsh;
        LoadProposalCommand = new AsyncRelayCommand(LoadAsync, ShowError, () => !string.IsNullOrWhiteSpace(GoalId));
        PreviewCommand = new AsyncRelayCommand(PreviewAsync, ShowError, () => _draft is not null && _draft.Committed is null);
        CommitCommand = new AsyncRelayCommand(CommitAsync, ShowError, () => _draft?.CommitBlock() == OwnerReviewCommitBlock.None);
        CancelCommand = new AsyncRelayCommand(CancelAsync, ShowError);
        RefreshCredentialStatus();
    }

    public string TransportBanner => _livePinnedSsh
        ? "已通过固定主机密钥的 SSH 标准输入/输出通道连接 Mac Core（无本地监听端口、无明文回退）。需要主人专用凭据；设备令牌与 Worker 身份不会被使用。"
        : "加密传输尚未验收（" + OwnerReviewTransportGate.StatusLabel + "）：当前版本仅用合成资料与 Mock 验证，不会明文调用真实 Core。";

    public AsyncRelayCommand LoadProposalCommand { get; }
    public AsyncRelayCommand PreviewCommand { get; }
    public AsyncRelayCommand CommitCommand { get; }
    public AsyncRelayCommand CancelCommand { get; }

    public ObservableCollection<OwnerReviewFieldRowViewModel> IdentityFields { get; } = [];
    public ObservableCollection<OwnerReviewFieldRowViewModel> IntentFields { get; } = [];

    public string CredentialStatus { get; private set; } = string.Empty;
    public bool HasProposal => _draft is not null;
    public string ProposalHeader { get; private set; } = string.Empty;
    public string EvidenceNotice { get; private set; } = string.Empty;
    public string? IdempotencyKey => _draft?.IdempotencyKey;
    public OwnerReviewDraft? Draft => _draft;

    public string GoalId
    {
        get => _goalId;
        set
        {
            if (SetProperty(ref _goalId, value)) LoadProposalCommand.NotifyCanExecuteChanged();
        }
    }

    public string StatusText { get => _statusText; private set => SetProperty(ref _statusText, value); }
    public string ErrorText { get => _errorText; private set => SetProperty(ref _errorText, value); }
    public string PreviewSummary { get => _previewSummary; private set => SetProperty(ref _previewSummary, value); }
    public string CommitSummary { get => _commitSummary; private set => SetProperty(ref _commitSummary, value); }
    public bool Busy { get => _busy; private set => SetProperty(ref _busy, value); }

    /// <summary>主人必须显式勾选；预览变化后自动清除，绝无默认确认。</summary>
    /// <summary>Optional static-story authorization is a distinct user decision.</summary>
    public bool StaticPetStorySelected
    {
        get => _staticPetStorySelected;
        set
        {
            if (!SetProperty(ref _staticPetStorySelected, value)) return;
            if (_draft is not null) _draft.StaticPetStorySelected = value;
            PreviewSummary = string.Empty;
            OwnerConfirmed = false;
            CommitCommand.NotifyCanExecuteChanged();
        }
    }

    public bool OwnerConfirmed
    {
        get => _ownerConfirmed;
        set
        {
            if (!SetProperty(ref _ownerConfirmed, value)) return;
            if (_draft is not null) _draft.OwnerExplicitlyConfirmed = value;
            CommitCommand.NotifyCanExecuteChanged();
        }
    }

    /// <summary>保存主人专用凭据；绝不读取或写入设备令牌。</summary>
    public void SaveCredential(string credential)
    {
        try
        {
            _credentials.Save(credential);
            ErrorText = string.Empty;
        }
        catch (ArgumentException)
        {
            ErrorText = "主人审核凭据格式无效。";
        }
        RefreshCredentialStatus();
    }

    public void ClearCredential()
    {
        _credentials.Delete();
        RefreshCredentialStatus();
    }

    private void RefreshCredentialStatus()
    {
        CredentialStatus = string.IsNullOrEmpty(_credentials.Read())
            ? "主人审核凭据：未配置（专用 DPAPI 存储，与设备令牌分离）"
            : "主人审核凭据：已保存（专用 DPAPI 存储，不显示明文）";
        RaisePropertyChanged(nameof(CredentialStatus));
    }

    private async Task LoadAsync()
    {
        ErrorText = string.Empty;
        Busy = true;
        try
        {
            var proposal = await _client.GetProposalAsync(GoalId.Trim(), CancellationToken.None).ConfigureAwait(true);
            BuildDraft(proposal);
            StatusText = "提案已加载：请逐字段选择 确认 / 更正 / 未知，然后生成预览。";
        }
        finally
        {
            Busy = false;
        }
    }

    private async Task PreviewAsync()
    {
        ErrorText = string.Empty;
        var draft = _draft ?? throw new InvalidOperationException("尚未加载提案。");
        if (draft.FirstValidationProblem() is { } problem)
        {
            ErrorText = problem;
            return;
        }
        Busy = true;
        try
        {
            var preview = await _client.PreviewAsync(draft.BuildPreviewRequest(), CancellationToken.None).ConfigureAwait(true);
            draft.AcceptPreview(preview);
            OwnerConfirmed = false;
            PreviewSummary = DescribePreview(preview);
            StatusText = preview.Outcome == OwnerReviewWire.OutcomeReady
                ? "Core 预览为 READY：请核对摘要后显式提交。"
                : "Core 预览为 NEEDS_HUMAN：不能提交，请补全或更正后重新预览。";
        }
        finally
        {
            Busy = false;
            CommitCommand.NotifyCanExecuteChanged();
        }
    }

    private async Task CommitAsync()
    {
        ErrorText = string.Empty;
        var draft = _draft ?? throw new InvalidOperationException("尚未加载提案。");
        var block = draft.CommitBlock();
        if (block != OwnerReviewCommitBlock.None)
        {
            ErrorText = OwnerReviewLabels.Block(block);
            return;
        }
        Busy = true;
        try
        {
            var key = draft.IdempotencyKey ?? throw new InvalidOperationException("缺少幂等键。");
            var commit = await _client.CommitAsync(draft.BuildCommitRequest(), key, CancellationToken.None).ConfigureAwait(true);
            draft.MarkCommitted(commit);
            CommitSummary = $"已提交：{commit.CommitmentId}\nfacts_id={commit.FactsId}\nfacts_digest={commit.FactsDigest}";
            StatusText = "主人审核已提交（不会自动创建 Goal、运行 Creative 或 GPU）。";
        }
        finally
        {
            Busy = false;
            CommitCommand.NotifyCanExecuteChanged();
            PreviewCommand.NotifyCanExecuteChanged();
        }
    }

    /// <summary>离开审核：丢弃本地草稿，不触发任何 Core 写入、Creative 或 GPU。</summary>
    private Task CancelAsync()
    {
        _draft = null;
        IdentityFields.Clear();
        IntentFields.Clear();
        PreviewSummary = string.Empty;
        CommitSummary = string.Empty;
        ErrorText = string.Empty;
        OwnerConfirmed = false;
        StatusText = "已离开审核；未提交任何内容。";
        RaisePropertyChanged(nameof(HasProposal));
        return Task.CompletedTask;
    }

    private void BuildDraft(OwnerReviewProposal proposal)
    {
        _draft = new OwnerReviewDraft(proposal);
        var evidence = proposal.SourceEvidence.ToDictionary(item => item.EvidenceId, StringComparer.Ordinal);
        IdentityFields.Clear();
        IntentFields.Clear();
        foreach (var field in _draft.Fields)
        {
            var row = new OwnerReviewFieldRowViewModel(field, evidence, OnDecisionChanged);
            (row.IsIdentity ? IdentityFields : IntentFields).Add(row);
        }
        PreviewSummary = string.Empty;
        CommitSummary = string.Empty;
        _ownerConfirmed = false;
        _staticPetStorySelected = false;
        RaisePropertyChanged(nameof(OwnerConfirmed));
        RaisePropertyChanged(nameof(StaticPetStorySelected));
        ProposalHeader = $"Goal {proposal.GoalId} · 主体 {proposal.SubjectKey} · 审核人 {proposal.ReviewActorId}";
        EvidenceNotice = proposal.SourceEvidence.Any(item => !item.PhotoBytesVerified)
            ? "注意：照片字节未经 Core 校验，所有身份事实均为主人声明；文字审核本身不授权 I2V。"
            : "照片字节已由 Core 校验；文字审核本身仍不授权 I2V。";
        RaisePropertyChanged(nameof(ProposalHeader));
        RaisePropertyChanged(nameof(EvidenceNotice));
        RaisePropertyChanged(nameof(HasProposal));
        PreviewCommand.NotifyCanExecuteChanged();
        CommitCommand.NotifyCanExecuteChanged();
    }

    private void OnDecisionChanged()
    {
        PreviewSummary = string.Empty;
        if (_ownerConfirmed)
        {
            _ownerConfirmed = false;
            RaisePropertyChanged(nameof(OwnerConfirmed));
        }
        CommitCommand.NotifyCanExecuteChanged();
    }

    private static string DescribePreview(OwnerReviewPreview preview) =>
        $"结果：{preview.Outcome}\n"
        + (preview.ReasonCodes.Count > 0 ? "原因码：" + string.Join("、", preview.ReasonCodes) + "\n" : string.Empty)
        + $"proposal_digest={preview.ProposalDigest}\n"
        + $"source_revision_digest={preview.SourceRevisionDigest}\n"
        + $"review_digest={preview.ReviewDigest}\n"
        + $"preview_digest={preview.PreviewDigest}\n"
        + $"静态故事策略：{preview.StoryPolicyOptIn ?? "未选择（保持原验收规则）"}\n"
        + "（以上摘要全部由 Core 计算，Windows 不生成替代摘要。）";

    private void ShowError(Exception error)
    {
        switch (error)
        {
            case OwnerReviewException known:
                ErrorText = known.ChineseMessage;
                if (known.RequiresReload)
                {
                    // 409 must invalidate the ACTUAL draft, not only its displayed text.
                    _draft?.DiscardPreviewAfterConflict();
                    _draft = null;
                    IdentityFields.Clear();
                    IntentFields.Clear();
                    PreviewSummary = string.Empty;
                    CommitSummary = string.Empty;
                    OwnerConfirmed = false;
                    RaisePropertyChanged(nameof(HasProposal));
                    PreviewCommand.NotifyCanExecuteChanged();
                    StatusText = "数据已过期，必须重新加载提案才能再次预览或提交。";
                }
                break;
            case ArgumentException:
                ErrorText = "输入格式无效，请检查 Goal ID。";
                break;
            default:
                ErrorText = "主人审核操作失败，请稍后重试。";
                break;
        }
        CommitCommand.NotifyCanExecuteChanged();
    }
}
