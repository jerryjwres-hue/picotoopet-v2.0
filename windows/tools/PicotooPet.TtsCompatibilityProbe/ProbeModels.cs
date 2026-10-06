using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.TtsCompatibilityProbe;

/// <summary>Closed, bounded status codes; reports never carry raw exception text or paths.</summary>
internal static class StatusCodes
{
    public const string Pass = "PASS";
    public const string NoCompatibleVoice = "NO_COMPATIBLE_VOICE";
    public const string EngineUnavailable = "ENGINE_UNAVAILABLE";
    public const string SynthesisFailed = "SYNTHESIS_FAILED";
    public const string Timeout = "TIMEOUT";
    public const string Unresponsive = "ENGINE_UNRESPONSIVE";
    public const string Cancelled = "CANCELLED";
    public const string InvalidWav = "INVALID_WAV";
    public const string NotRun = "NOT_RUN";
}

internal sealed record VoiceInfo(string Id, string Name, string Culture);

internal sealed record WavInfo(
    int AudioFormat,
    int Channels,
    int SampleRate,
    int BitsPerSample,
    long DataBytes,
    long FileBytes,
    long DurationMs);

internal sealed record CancellationReport(string Status, long ElapsedMs, bool Bounded);

internal sealed record EngineReport(
    string Engine,
    string Dependency,
    string Status,
    IReadOnlyList<VoiceInfo> InstalledVoices,
    VoiceInfo? SelectedVoice,
    bool OfflineNoCredentials,
    WavInfo? Wav,
    long SynthesisElapsedMs,
    CancellationReport? Cancellation);

internal sealed record ProbeReport(
    string Probe,
    string Phrase,
    string OsVersion,
    string Runtime,
    int TimeoutSeconds,
    bool SimulatedNoVoice,
    IReadOnlyList<EngineReport> Engines);

internal static class ProbeJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    };
}
