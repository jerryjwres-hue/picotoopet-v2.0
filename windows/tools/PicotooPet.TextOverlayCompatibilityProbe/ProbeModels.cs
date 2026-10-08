using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.TextOverlayCompatibilityProbe;

/// <summary>Closed, bounded status codes; reports never carry raw stderr, absolute paths or exception text.</summary>
internal static class Status
{
    public const string Pass = "PASS";
    public const string Fail = "FAIL";
    public const string NotRun = "NOT_RUN";
    public const string FfmpegUnavailable = "FFMPEG_UNAVAILABLE";
    public const string FilterMissing = "FILTER_MISSING";
    public const string EncoderMissing = "ENCODER_MISSING";
    public const string FontUnavailable = "FONT_UNAVAILABLE";
    public const string GlyphMissing = "GLYPH_MISSING";
    public const string RenderFailed = "RENDER_FAILED";
    public const string OutputInvalid = "OUTPUT_INVALID";
    public const string TimingViolation = "TIMING_VIOLATION";
    public const string GeometryViolation = "GEOMETRY_VIOLATION";
    public const string NotDeterministic = "NOT_DETERMINISTIC";
    public const string GlyphNotDistinct = "GLYPH_NOT_DISTINCT";
    public const string Timeout = "TIMEOUT";
    public const string Cancelled = "CANCELLED";
    public const string Unresponsive = "PROCESS_UNRESPONSIVE";
    public const string NotWindows = "ENVIRONMENT_NOT_WINDOWS";
}

internal sealed record BoundingBox(int X0, int Y0, int X1, int Y1);

internal sealed record RenderCheck(
    string Label,
    string Status,
    long OutputBytes,
    bool FfprobeReadable,
    string? VideoCodec,
    int Width,
    int Height,
    int FrameCount,
    int FirstInkFrame,
    int LastInkFrame,
    BoundingBox? MidCueInkBox,
    int CenterOffsetPx);

internal sealed record BoundedProcessCheck(string Status, long ElapsedMs, bool Bounded);

internal sealed record PathReport(
    string Path,
    string Status,
    bool FilterPresent,
    string? EnglishFont,
    string? ChineseFont,
    IReadOnlyList<RenderCheck> Renders,
    bool Deterministic,
    bool ChineseGlyphsDistinct,
    BoundedProcessCheck? Cancellation,
    BoundedProcessCheck? Timeout);

internal sealed record FontPolicyReport(
    IReadOnlyList<string> CandidatesFound,
    string? SelectedEnglish,
    string? SelectedChinese,
    string MissingFontCheck,
    string MissingGlyphCheck);

internal sealed record ProbeReport(
    string Probe,
    string OsVersion,
    string? FfmpegVersion,
    bool LibassEnabled,
    bool LibfreetypeEnabled,
    bool X264Available,
    bool FfprobeAvailable,
    int TimeoutSeconds,
    bool SimulatedNoFont,
    FontPolicyReport FontPolicy,
    IReadOnlyList<PathReport> Paths,
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

/// <summary>Fixed internally-authored probe profile; nothing here is caller-configurable.</summary>
internal static class Profile
{
    public const int Width = 640;
    public const int Height = 360;
    public const int Fps = 25;
    public const int DurationSeconds = 4;
    public const int CueStartSeconds = 1;
    public const int CueEndSeconds = 3;
    public const int FontSize = 26;
    public const string BackgroundColor = "0x203040";

    // ── Lower-third safe area: 5% side margins, text block top at 78% height, 5% bottom margin. ──
    public const int SafeLeft = 32;
    public const int SafeRight = 608;
    public const int SafeTop = 240;
    public const int SafeBottom = 342;
    public const int MaxCenterOffsetPx = 10;
    public const int AnalysisRegionTop = 240;
    public const int AnalysisRegionHeight = 120;

    public const string EnglishText = "Caption Test: PicotooPet 0123";
    public const string ChineseText = "字幕测试：皮卡图宠物";
    public const string ChineseAltText = "叠加检查：安全区域内容";
}
