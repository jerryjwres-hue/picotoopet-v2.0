using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Mac Core 持久化的不可变 Coding Escalation 决策投影。</summary>
public sealed record CodingEscalationDecisionRecord(
    [property: JsonPropertyName("decision_id")] string DecisionId,
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("decision_digest")] string DecisionDigest,
    [property: JsonPropertyName("policy_version")] string PolicyVersion,
    [property: JsonPropertyName("chosen_provider")] string ChosenProvider,
    [property: JsonPropertyName("decision")] CodingEscalationDecision Decision,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>只读抠门仲裁结果；不包含模型、命令、工作目录或执行参数。</summary>
public sealed record CodingEscalationDecision(
    [property: JsonPropertyName("policy_version")] string PolicyVersion,
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("task_class")] string TaskClass,
    [property: JsonPropertyName("eligibility")] bool Eligibility,
    [property: JsonPropertyName("action")] string Action,
    [property: JsonPropertyName("local_quality_score")] double LocalQualityScore,
    [property: JsonPropertyName("confidence_center")] double ConfidenceCenter,
    [property: JsonPropertyName("confidence_lower")] double ConfidenceLower,
    [property: JsonPropertyName("confidence_upper")] double ConfidenceUpper,
    [property: JsonPropertyName("risk_score")] double RiskScore,
    [property: JsonPropertyName("reason_codes")] string[] ReasonCodes,
    [property: JsonPropertyName("candidate_provider_scores")]
    CodingProviderCandidateScore[] CandidateProviderScores,
    [property: JsonPropertyName("provider_history")]
    CodingProviderHistoryEvaluation[] ProviderHistory,
    [property: JsonPropertyName("chosen_provider")] string ChosenProvider,
    [property: JsonPropertyName("external_sessions_remaining")] int ExternalSessionsRemaining,
    [property: JsonPropertyName("decision_digest")] string DecisionDigest);

/// <summary>一个 Provider 的保守效用分数；只用于解释，不授予执行权限。</summary>
public sealed record CodingProviderCandidateScore(
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("utility")] double Utility,
    [property: JsonPropertyName("eligible")] bool Eligible,
    [property: JsonPropertyName("reason_codes")] string[] ReasonCodes);

/// <summary>基于本地验证历史计算的 Wilson 95% 区间投影。</summary>
public sealed record CodingProviderHistoryEvaluation(
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("sample_size")] int SampleSize,
    [property: JsonPropertyName("success_count")] int SuccessCount,
    [property: JsonPropertyName("success_rate")] double SuccessRate,
    [property: JsonPropertyName("wilson95_lower")] double Wilson95Lower,
    [property: JsonPropertyName("wilson95_upper")] double Wilson95Upper,
    [property: JsonPropertyName("history_sufficient")] bool HistorySufficient);
