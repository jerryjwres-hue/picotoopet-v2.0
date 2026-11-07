using System.Security.Cryptography;
using System.Text.Json;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>字段分组：身份/场景事实与创作意图分开显示。</summary>
public enum OwnerReviewFieldGroup
{
    IdentityAndSceneFacts,
    CreativeIntent,
}

/// <summary>单字段当前决定（无默认值；null 代表主人尚未决定）。</summary>
public sealed class OwnerReviewFieldState
{
    public OwnerReviewFieldState(OwnerFieldProposal proposal)
    {
        Proposal = proposal;
        Group = proposal.AuthorityKind == OwnerReviewWire.AuthorityCreativeIntent
                || proposal.FieldPath.StartsWith("allowed_events", StringComparison.Ordinal)
            ? OwnerReviewFieldGroup.CreativeIntent
            : OwnerReviewFieldGroup.IdentityAndSceneFacts;
    }

    public OwnerFieldProposal Proposal { get; }
    public OwnerReviewFieldGroup Group { get; }
    public string? Decision { get; set; }
    public string CorrectedText { get; set; } = string.Empty;

    /// <summary>Core 标记为 UNKNOWN/CONFLICT 的字段不允许直接 CONFIRM。</summary>
    public bool CanConfirm => Proposal.Status == OwnerReviewWire.StatusExplicit;
}

/// <summary>Commit 门禁原因，供 UI 精确提示。</summary>
public enum OwnerReviewCommitBlock
{
    None,
    NoPreview,
    PreviewStale,
    NeedsHuman,
    NotExplicitlyConfirmed,
    AlreadyCommitted,
}

/// <summary>
/// 一次主人审核会话状态：提案 → 逐字段决定 → Core 预览 → 显式提交。
/// 任何决定变化都会使既有预览失效；预览内容永远来自 Core，客户端不计算权威摘要。
/// </summary>
public sealed class OwnerReviewDraft
{
    private static readonly char[] SplitChars = ['\n', '\r', ';', '；'];
    private readonly Dictionary<string, OwnerReviewFieldState> _fields;
    private string? _previewedFingerprint;

    public OwnerReviewDraft(OwnerReviewProposal proposal)
    {
        Proposal = proposal;
        _fields = proposal.Fields
            .OrderBy(pair => pair.Key, StringComparer.Ordinal)
            .ToDictionary(pair => pair.Key, pair => new OwnerReviewFieldState(pair.Value), StringComparer.Ordinal);
    }

    public OwnerReviewProposal Proposal { get; }
    public IReadOnlyCollection<OwnerReviewFieldState> Fields => _fields.Values;
    public OwnerReviewPreview? Preview { get; private set; }
    public OwnerReviewCommit? Committed { get; private set; }
    public bool OwnerExplicitlyConfirmed { get; set; }

    /// <summary>当前预览对应的幂等键；同一预览的重试复用同一键，新预览换新键。</summary>
    public string? IdempotencyKey { get; private set; }

    public IEnumerable<OwnerReviewFieldState> Group(OwnerReviewFieldGroup group) =>
        _fields.Values.Where(field => field.Group == group);

    public void SetDecision(string fieldPath, string? decision, string? correctedText = null)
    {
        if (!_fields.TryGetValue(fieldPath, out var field))
        {
            throw new ArgumentException("未知字段。", nameof(fieldPath));
        }
        if (decision is not (null or OwnerReviewWire.DecisionConfirm or OwnerReviewWire.DecisionCorrect
            or OwnerReviewWire.DecisionUnknown))
        {
            throw new ArgumentException("决定必须是 CONFIRM / CORRECT / UNKNOWN。", nameof(decision));
        }
        field.Decision = decision;
        field.CorrectedText = correctedText ?? string.Empty;
        InvalidatePreview();
    }

    /// <summary>所有字段都已明确决定，且 CONFIRM/CORRECT 条件成立。返回第一个问题的中文说明。</summary>
    public string? FirstValidationProblem()
    {
        foreach (var field in _fields.Values)
        {
            if (field.Decision is null)
            {
                return $"字段 {field.Proposal.FieldPath} 尚未决定（不允许默认确认）。";
            }
            if (field.Decision == OwnerReviewWire.DecisionConfirm && !field.CanConfirm)
            {
                return $"字段 {field.Proposal.FieldPath} 来源未知或冲突，不能直接确认，请更正或标记未知。";
            }
            if (field.Decision == OwnerReviewWire.DecisionCorrect
                && string.IsNullOrWhiteSpace(field.CorrectedText))
            {
                return $"字段 {field.Proposal.FieldPath} 选择了更正，必须填写更正值。";
            }
        }
        return null;
    }

    public OwnerReviewPreviewRequest BuildPreviewRequest()
    {
        if (FirstValidationProblem() is { } problem)
        {
            throw new InvalidOperationException(problem);
        }
        var decisions = _fields.Values
            .Select(field => new OwnerFieldDecision(
                field.Proposal.FieldPath,
                field.Decision!,
                field.Decision == OwnerReviewWire.DecisionCorrect ? ToJson(field.CorrectedText, field.Proposal.Value) : null))
            .ToList();
        return new OwnerReviewPreviewRequest(
            Proposal.GoalId, Proposal.ReviewActorId, Proposal.ProposalDigest, decisions);
    }

    /// <summary>接受 Core 返回的预览，并为这一预览分配新的幂等键。</summary>
    public void AcceptPreview(OwnerReviewPreview preview)
    {
        ArgumentNullException.ThrowIfNull(preview);
        if (preview.ProposalDigest != Proposal.ProposalDigest || preview.GoalId != Proposal.GoalId)
        {
            throw new OwnerReviewException(OwnerReviewFailureKind.Conflict, 409, "OWNER_REVIEW_PREVIEW_MISMATCH");
        }
        Preview = preview;
        _previewedFingerprint = Fingerprint();
        OwnerExplicitlyConfirmed = false;
        IdempotencyKey = "owner-review-" + Guid.NewGuid().ToString("N");
    }

    public OwnerReviewCommitBlock CommitBlock()
    {
        if (Committed is not null)
        {
            return OwnerReviewCommitBlock.AlreadyCommitted;
        }
        if (Preview is null)
        {
            return OwnerReviewCommitBlock.NoPreview;
        }
        if (_previewedFingerprint != Fingerprint())
        {
            return OwnerReviewCommitBlock.PreviewStale;
        }
        if (Preview.Outcome != OwnerReviewWire.OutcomeReady || Preview.StateFacts is null)
        {
            return OwnerReviewCommitBlock.NeedsHuman;
        }
        return OwnerExplicitlyConfirmed ? OwnerReviewCommitBlock.None : OwnerReviewCommitBlock.NotExplicitlyConfirmed;
    }

    public OwnerReviewCommitRequest BuildCommitRequest()
    {
        if (CommitBlock() != OwnerReviewCommitBlock.None || Preview is null)
        {
            throw new InvalidOperationException("提交条件未满足：" + CommitBlock());
        }
        return new OwnerReviewCommitRequest(
            BuildPreviewRequest(),
            Preview.SourceRevisionDigest,
            Preview.ReviewDigest,
            Preview.PreviewDigest);
    }

    public void MarkCommitted(OwnerReviewCommit commit) => Committed = commit;

    private void InvalidatePreview()
    {
        Preview = null;
        _previewedFingerprint = null;
        IdempotencyKey = null;
        OwnerExplicitlyConfirmed = false;
    }

    private string Fingerprint()
    {
        var text = string.Join(
            "\n",
            _fields.Values.Select(f => $"{f.Proposal.FieldPath}\u001f{f.Decision}\u001f{f.CorrectedText}"));
        return Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(text)));
    }

    /// <summary>
    /// 更正值按提案值类型发送：列表字段按行/分号拆分为字符串数组，其余为字符串。
    /// Core 对类型和证据绑定拥有最终裁决权。
    /// </summary>
    private static JsonElement ToJson(string text, JsonElement? proposed)
    {
        object payload = proposed is { ValueKind: JsonValueKind.Array }
            ? text.Split(SplitChars, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            : text.Trim();
        using var document = JsonDocument.Parse(JsonSerializer.Serialize(payload));
        return document.RootElement.Clone();
    }
}
