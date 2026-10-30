using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services.QualityObservation;

public enum VisualObservationVerdict { Review, RejectSuspect, Unverified }
public sealed record VisualObservationResult(VisualObservationVerdict Verdict, string Detail,
    string? EvidenceDirectory = null, byte[]? ContactSheetPng = null);
public sealed record VisualObservationFacts(ProductionJobRecord Job, ProductionPlanRecord Plan, ProductionPackageRecord Package);
public sealed record VisualObservationShot(int Order, string ShotId, string TaskId, string RelativePath,
    string Sha256, long Bytes, int ExpectedFrames, int ExpectedDurationMs, string Action);
public sealed record VisualObservationInput(string SchemaVersion, string JobId, IReadOnlyList<VisualObservationShot> Shots);
public sealed record VisualReadSource(string Path, string ShotId, string TaskId, string Sha256, long Bytes);
public sealed record VisualReadRequest(string JobId, IReadOnlyList<VisualReadSource> Sources, string? VlmEndpoint, string? VlmModel);
public sealed record VisualReadConsent(bool ReadSources, bool TransferFrames = false);

// Read-only interfaces deliberately expose no claim, execution, approval or receipt method.
public interface IVisualObservationFacts : IDisposable
{
    event EventHandler? Invalidated;
    Task<VisualObservationFacts> ReadAsync(string exactJobId, CancellationToken ct);
}
public interface IVisualObservation : IDisposable
{
    event EventHandler? Invalidated;
    Task<VisualObservationResult> ObserveAsync(ProductionJobRecord selected, bool optionalVlm,
        Func<VisualReadRequest, CancellationToken, Task<VisualReadConsent>> consent, CancellationToken ct);
}
public sealed class VisualObserverDeployment : IDisposable
{
    private readonly IDisposable? _lease;
    public VisualObserverDeployment(string observer, string ffprobe, string ffmpeg, string sourceSha,
        string? vlmEndpoint = null, string? vlmModel = null, IDisposable? lease = null)
    { Observer = observer; Ffprobe = ffprobe; Ffmpeg = ffmpeg; SourceSha = sourceSha; VlmEndpoint = vlmEndpoint; VlmModel = vlmModel; _lease = lease; }
    public string Observer { get; }
    public string Ffprobe { get; }
    public string Ffmpeg { get; }
    public string SourceSha { get; }
    public string? VlmEndpoint { get; }
    public string? VlmModel { get; }
    public void Dispose() => _lease?.Dispose();
}
public interface IVisualObservationRuntime
{
    string ConfiguredOutputRoot();
    VisualObserverDeployment OpenDeployment();
    string CreateEvidenceRun();
    Task<int> RunAsync(VisualObserverDeployment deployment, string input, string root, string output, bool transferFrames, CancellationToken ct);
}

internal sealed class VisualObservationException(string code) : Exception(code);
