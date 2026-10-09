using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.PostProductionAudioMuxProbe;

/// <summary>Closed, bounded codes; reports never carry raw stderr, absolute paths or exception text.</summary>
internal static class Status
{
    public const string Pass = "PASS";
    public const string Fail = "FAIL";
    public const string NotRun = "NOT_RUN";
    public const string FfmpegUnavailable = "FFMPEG_UNAVAILABLE";
    public const string AacEncoderMissing = "AAC_ENCODER_MISSING";
    public const string SegmentTooLong = "NARRATION_SEGMENT_TOO_LONG";
    public const string SegmentOutsideTimeline = "NARRATION_SEGMENT_OUTSIDE_TIMELINE";
    public const string SegmentOverlap = "NARRATION_SEGMENT_OVERLAP";
    public const string SegmentInvalid = "NARRATION_SEGMENT_INVALID";
    public const string MuxFailed = "MUX_FAILED";
    public const string OutputInvalid = "OUTPUT_INVALID";
    public const string Timeout = "TIMEOUT";
    public const string Cancelled = "CANCELLED";
    public const string Unresponsive = "PROCESS_UNRESPONSIVE";
    public const string NotWindows = "ENVIRONMENT_NOT_WINDOWS";
}

internal sealed record VideoFacts(
    string Codec,
    int Width,
    int Height,
    string FrameRate,
    string PixelFormat,
    int PacketCount);

internal sealed record AudioFacts(string Codec, string Profile, int SampleRate, int Channels);

internal sealed record WavReport(string Label, int SampleRate, int Channels, long DurationMs, int StartMs, int WindowEndMs);

internal sealed record FinalStreamFacts(
    int VideoStreams,
    int AudioStreams,
    int OtherStreams,
    VideoFacts? Video,
    AudioFacts? Audio,
    double DurationSeconds,
    long Bytes);

internal sealed record WindowCheck(string Name, string Kind, int FromMs, int ToMs, double Rms, int StrongestHz, bool Ok);

internal sealed record BoundedCheck(string Status, long ElapsedMs, bool Bounded);

internal sealed record NegativeCheck(string Status, bool FfmpegInvoked, bool OutputExists, bool Rejected);

internal sealed record ProbeReport(
    string Probe,
    string OsVersion,
    string? FfmpegVersion,
    bool AacEncoderPresent,
    bool FfprobeAvailable,
    VideoFacts? InputVideo,
    IReadOnlyList<WavReport> InputWavs,
    string CommandShape,
    FinalStreamFacts? Final,
    bool VideoStreamCopyProven,
    string? InputVideoPacketMd5,
    string? FinalVideoPacketMd5,
    bool DurationWithinTolerance,
    IReadOnlyList<WindowCheck> AudioTimelineChecks,
    BoundedCheck? Cancellation,
    BoundedCheck? Timeout,
    NegativeCheck? OverlongNarration,
    bool FailureLeavesNoOutput,
    string Status,
    string SuggestedDecision);

internal static class ProbeJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    };
}

/// <summary>One Core-authored narration placement: start and the allotted window end, in integer ms.</summary>
internal sealed record NarrationPlacement(string Label, int StartMs, int WindowEndMs, string WavFile);

/// <summary>Fixed internally-authored profile; nothing here is caller-configurable.</summary>
internal static class Profile
{
    public const int Width = 640;
    public const int Height = 360;
    public const int Fps = 25;
    public const int TimelineMs = 8000;
    public const int AudioRate = 48000;
    public const int EdgeMarginMs = 150;
    public const double DurationToleranceSeconds = 0.15;
    public const double ToneMinRms = 3000;
    public const double SilenceMaxRms = 200;
}
