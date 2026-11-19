using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>生产页使用的剧集与分镜数据。</summary>
public sealed record EpisodeSummary(
    [property: JsonPropertyName("episode_id")] string EpisodeId,
    [property: JsonPropertyName("title")] string Title);

public sealed record EpisodeReview(
    [property: JsonPropertyName("shots")] ShotReview[] Shots,
    [property: JsonPropertyName("can_assemble")] bool CanAssemble);

public sealed record ShotReview(
    [property: JsonPropertyName("shot_id")] string ShotId,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("redo_count")] int RedoCount,
    [property: JsonPropertyName("candidates")] ReviewCandidate[] Candidates);

public sealed record ReviewCandidate(
    [property: JsonPropertyName("artifact_id")] string ArtifactId,
    [property: JsonPropertyName("task_id")] string TaskId,
    [property: JsonPropertyName("kind")] string Kind,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("take")] int Take,
    [property: JsonPropertyName("decision")] string? Decision,
    [property: JsonPropertyName("note")] string Note,
    [property: JsonPropertyName("thumbnail_id")] string? ThumbnailId,
    [property: JsonPropertyName("qc")] JsonElement Qc,
    [property: JsonPropertyName("seed")] long? Seed = null,
    [property: JsonPropertyName("source_id")] string? SourceId = null,
    [property: JsonPropertyName("task_type")] string? TaskType = null);

public sealed record EpisodeImportResult(
    [property: JsonPropertyName("episode_id")] string EpisodeId,
    [property: JsonPropertyName("inserted_count")] int InsertedCount,
    [property: JsonPropertyName("existing_count")] int ExistingCount,
    [property: JsonPropertyName("updated_count")] int UpdatedCount = 0,
    [property: JsonPropertyName("conflict_count")] int ConflictCount = 0);

public sealed record ArtifactDecisionRequest(
    [property: JsonPropertyName("decision")] string Decision,
    [property: JsonPropertyName("note")] string Note);

public sealed record PreviewContent(
    [property: JsonPropertyName("jpeg_base64")] string JpegBase64);
