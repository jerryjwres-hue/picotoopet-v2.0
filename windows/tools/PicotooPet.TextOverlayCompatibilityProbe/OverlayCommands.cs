using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace PicotooPet.TextOverlayCompatibilityProbe;

internal enum OverlayPath
{
    Drawtext,
    Libass,
}

/// <summary>
/// Builds the only filter graphs this probe can run. Every file name is probe-authored from a fixed
/// pattern and referenced relative to the managed working directory, so no escaping, caller font,
/// caller path or caller filter string can reach ffmpeg.
/// </summary>
internal static partial class OverlayCommands
{
    [GeneratedRegex("^[A-Za-z0-9_.-]+$")]
    private static partial Regex SafeName();

    public static string Safe(string name) =>
        SafeName().IsMatch(name) ? name : throw new InvalidOperationException("UNSAFE_NAME_DENIED");

    private static string Invariant(int value) => value.ToString(CultureInfo.InvariantCulture);

    public static string Source(int durationSeconds) =>
        $"color=c={Profile.BackgroundColor}:s={Profile.Width}x{Profile.Height}:r={Profile.Fps}:d={Invariant(durationSeconds)}";

    public static string DrawtextFilter(string fontFile, string textFile) =>
        $"drawtext=fontfile={Safe(fontFile)}:textfile={Safe(textFile)}:fontsize={Profile.FontSize}"
        + ":fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=10"
        + ":x=(w-text_w)/2:y=h*0.78"
        + $":enable='between(t,{Invariant(Profile.CueStartSeconds)},{Invariant(Profile.CueEndSeconds)})'";

    public static string LibassFilter(string assFile, string fontsDirectory) =>
        $"subtitles=filename={Safe(assFile)}:fontsdir={Safe(fontsDirectory)}";

    /// <summary>Fixed ASS: bottom-centre, opaque box, 12% bottom margin; one cue window.</summary>
    public static string BuildAss(string family, string text)
    {
        var builder = new StringBuilder();
        builder.Append("[Script Info]\nScriptType: v4.00+\n");
        builder.Append(CultureInfo.InvariantCulture, $"PlayResX: {Profile.Width}\nPlayResY: {Profile.Height}\n");
        builder.Append("WrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n");
        builder.Append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, ");
        builder.Append("Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, ");
        builder.Append("Alignment, MarginL, MarginR, MarginV, Encoding\n");
        builder.Append(CultureInfo.InvariantCulture,
            $"Style: Default,{family},{Profile.FontSize},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,3,2,0,2,32,32,43,1\n\n");
        builder.Append("[Events]\n");
        builder.Append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n");
        builder.Append(CultureInfo.InvariantCulture,
            $"Dialogue: 0,0:00:0{Profile.CueStartSeconds}.00,0:00:0{Profile.CueEndSeconds}.00,Default,,0,0,0,,{text}\n");
        return builder.ToString();
    }

    public static IReadOnlyList<string> RenderArguments(
        int durationSeconds,
        string filter,
        string outputFile) =>
    [
        "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", Source(durationSeconds),
        "-vf", filter,
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-pix_fmt", "yuv420p",
        "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
        "-movflags", "+faststart", "-f", "mp4", Safe(outputFile),
    ];

    public static IReadOnlyList<string> ExtractArguments(string inputFile) =>
    [
        "-hide_banner", "-loglevel", "error", "-nostdin", "-i", Safe(inputFile),
        "-vf", $"crop={Profile.Width}:{Profile.AnalysisRegionHeight}:0:{Profile.AnalysisRegionTop},format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ];

    public static IReadOnlyList<string> DecodeCheckArguments(string inputFile) =>
        ["-hide_banner", "-loglevel", "error", "-nostdin", "-i", Safe(inputFile), "-f", "null", "-"];

    public static IReadOnlyList<string> ProbeArguments(string inputFile) =>
    [
        "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height",
        "-of", "csv=p=0", Safe(inputFile),
    ];
}
