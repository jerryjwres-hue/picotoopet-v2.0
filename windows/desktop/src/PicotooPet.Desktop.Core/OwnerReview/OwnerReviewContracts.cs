using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>冻结 OpenAPI mac_core_v1 中主人结构化审核常量的客户端镜像。</summary>
public static class OwnerReviewWire
{
    public const string FrozenCoreSha = "66c01c8e61e795982008c763ab2448e02c081831";
    public const string FrozenOpenApiSha256 = "33f90374747d15d43522a1ad4e1dbe411fa2c38ad21d163ca0fdd36985bf6bc6";
    public const string ProposalSchema = "owner_structured_review.proposal.v1";
    public const string PreviewSchema = "owner_structured_review.preview.v1";
    public const string CommitSchema = "owner_structured_review.commit.v1";
    public const string AuthorityOwnerAttestation = "OWNER_ATTESTATION";
    public const string AuthorityApprovedReference = "APPROVED_REFERENCE";
    public const string AuthorityCreativeIntent = "OWNER_CREATIVE_INTENT";
    public const string DecisionConfirm = "CONFIRM";
    public const string DecisionCorrect = "CORRECT";
    public const string DecisionUnknown = "UNKNOWN";
    public const string StatusExplicit = "EXPLICIT";
    public const string StatusUnknown = "UNKNOWN";
    public const string StatusConflict = "CONFLICT";
    public const string OutcomeReady = "READY";
    public const string OutcomeNeedsHuman = "NEEDS_HUMAN";

    internal static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    };
}

/// <summary>Core 返回的证据摘要；永不包含证据正文。</summary>
public sealed record OwnerEvidenceSummary(
    [property: JsonPropertyName("evidence_id")] string EvidenceId,
    [property: JsonPropertyName("evidence_type")] string EvidenceType,
    [property: JsonPropertyName("source")] string Source,
    [property: JsonPropertyName("trust_level")] string TrustLevel,
    [property: JsonPropertyName("raw_hash")] string RawHash,
    [property: JsonPropertyName("photo_bytes_verified")] bool PhotoBytesVerified,
    [property: JsonPropertyName("authority_kind")] string? AuthorityKind = null);

/// <summary>Core 生成的单字段提案；客户端不得自行构造。</summary>
public sealed record OwnerFieldProposal(
    [property: JsonPropertyName("field_path")] string FieldPath,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("authority_kind")] string? AuthorityKind = null,
    [property: JsonPropertyName("evidence_id")] string? EvidenceId = null,
    [property: JsonPropertyName("value")] JsonElement? Value = null,
    [property: JsonPropertyName("value_digest")] string? ValueDigest = null);

/// <summary>GET proposal 响应。</summary>
public sealed record OwnerReviewProposal(
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("creative_job_id")] string CreativeJobId,
    [property: JsonPropertyName("review_actor_id")] string ReviewActorId,
    [property: JsonPropertyName("registry_revision")] int RegistryRevision,
    [property: JsonPropertyName("subject_key")] string SubjectKey,
    [property: JsonPropertyName("creative_profile")] string CreativeProfile,
    [property: JsonPropertyName("source_set_digest")] string SourceSetDigest,
    [property: JsonPropertyName("objective_digest")] string ObjectiveDigest,
    [property: JsonPropertyName("source_revision_digest")] string SourceRevisionDigest,
    [property: JsonPropertyName("source_evidence")] IReadOnlyList<OwnerEvidenceSummary> SourceEvidence,
    [property: JsonPropertyName("fields")] IReadOnlyDictionary<string, OwnerFieldProposal> Fields,
    [property: JsonPropertyName("proposal_digest")] string ProposalDigest,
    [property: JsonPropertyName("schema_version")] string SchemaVersion = OwnerReviewWire.ProposalSchema);

/// <summary>单字段主人决定。</summary>
public sealed record OwnerFieldDecision(
    [property: JsonPropertyName("field_path")] string FieldPath,
    [property: JsonPropertyName("decision")] string Decision,
    [property: JsonPropertyName("corrected_value")] JsonElement? CorrectedValue = null);

/// <summary>POST preview 请求。</summary>
public sealed record OwnerReviewPreviewRequest(
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("review_actor_id")] string ReviewActorId,
    [property: JsonPropertyName("proposal_digest")] string ProposalDigest,
    [property: JsonPropertyName("decisions")] IReadOnlyList<OwnerFieldDecision> Decisions);

/// <summary>POST preview 响应；state_facts 仅作展示，客户端从不计算权威摘要。</summary>
public sealed record OwnerReviewPreview(
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("subject_key")] string SubjectKey,
    [property: JsonPropertyName("review_actor_id")] string ReviewActorId,
    [property: JsonPropertyName("proposal_digest")] string ProposalDigest,
    [property: JsonPropertyName("source_revision_digest")] string SourceRevisionDigest,
    [property: JsonPropertyName("review_digest")] string ReviewDigest,
    [property: JsonPropertyName("preview_digest")] string PreviewDigest,
    [property: JsonPropertyName("outcome")] string Outcome,
    [property: JsonPropertyName("reason_codes")] IReadOnlyList<string> ReasonCodes,
    [property: JsonPropertyName("state_facts")] JsonElement? StateFacts,
    [property: JsonPropertyName("model_calls")] int ModelCalls = 0,
    [property: JsonPropertyName("schema_version")] string SchemaVersion = OwnerReviewWire.PreviewSchema);

/// <summary>POST commit 请求。</summary>
public sealed record OwnerReviewCommitRequest(
    [property: JsonPropertyName("preview_request")] OwnerReviewPreviewRequest PreviewRequest,
    [property: JsonPropertyName("source_revision_digest")] string SourceRevisionDigest,
    [property: JsonPropertyName("review_digest")] string ReviewDigest,
    [property: JsonPropertyName("preview_digest")] string PreviewDigest);

/// <summary>POST commit 201 响应。</summary>
public sealed record OwnerReviewCommit(
    [property: JsonPropertyName("commitment_id")] string CommitmentId,
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("subject_key")] string SubjectKey,
    [property: JsonPropertyName("review_actor_id")] string ReviewActorId,
    [property: JsonPropertyName("source_revision_digest")] string SourceRevisionDigest,
    [property: JsonPropertyName("proposal_digest")] string ProposalDigest,
    [property: JsonPropertyName("review_digest")] string ReviewDigest,
    [property: JsonPropertyName("preview_digest")] string PreviewDigest,
    [property: JsonPropertyName("facts_id")] string FactsId,
    [property: JsonPropertyName("facts_digest")] string FactsDigest,
    [property: JsonPropertyName("schema_version")] string SchemaVersion = OwnerReviewWire.CommitSchema);
