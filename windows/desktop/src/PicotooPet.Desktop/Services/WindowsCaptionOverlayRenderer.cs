using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>闭集输出档位的固定版式；字号/边距只由 output_profile_id 决定。</summary>
public sealed record TextOverlayLayout(int Width, int Height, int Fps, int FontSize, int BoxBorder);

public sealed record PreparedOverlayCue(CaptionOverlayCueRecord Cue, ResolvedOverlayFont Font);

public sealed record TextOverlayMediaFacts(
    string VideoCodec,
    string PixelFormat,
    int Width,
    int Height,
    double DurationSeconds,
    bool HasNonVideoStream);

/// <summary>
/// S004 已在真实 Windows 验证的 FFmpeg drawtext 路径：文案只经 UTF-8 textfile 进入 FFmpeg，
/// 字体/文本文件是隔离工作目录里的内部生成相对名，滤镜串完全由内部时间与固定样式生成。
/// </summary>
public sealed class WindowsCaptionOverlayRenderer
{
    public const string RendererProfileId = "c008b.drawtext.v1";
    private static readonly TimeSpan RenderTimeout = TimeSpan.FromMinutes(10);
    private static readonly TimeSpan ProbeTimeout = TimeSpan.FromSeconds(30);
    private const double MaxFitFraction = 0.90;
    private const double LatinEm = 0.62;

    private readonly ITextOverlayProcessRunner _runner;

    public WindowsCaptionOverlayRenderer(ITextOverlayProcessRunner runner) =>
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));

    /// <summary>closed C005 档位 → 固定几何与字号。</summary>
    public static TextOverlayLayout LayoutFor(string outputProfileId) => outputProfileId switch
    {
        "video.landscape.v1" => new TextOverlayLayout(832, 480, 24, 34, 12),
        "video.vertical.v1" => new TextOverlayLayout(480, 832, 24, 28, 10),
        "video.square.v1" => new TextOverlayLayout(640, 640, 24, 30, 10),
        _ => throw new TextOverlayException(TextOverlayException.PlanInvalid),
    };

    /// <summary>为每条 cue 解析闭集字体并确认文本可在标题安全区单行显示。</summary>
    public static IReadOnlyList<PreparedOverlayCue> PrepareCues(
        CaptionOverlayPlanRecord plan,
        WindowsTextOverlayFontPolicy fonts)
    {
        ArgumentNullException.ThrowIfNull(plan);
        ArgumentNullException.ThrowIfNull(fonts);
        var layout = LayoutFor(plan.OutputProfileId);
        var prepared = new List<PreparedOverlayCue>();
        var previousStart = -1;
        for (var index = 0; index < plan.Overlays.Count; index++)
        {
            var cue = plan.Overlays[index];
            if (cue.Order != index + 1
                || cue.StartMs < previousStart
                || cue.EndMs <= cue.StartMs
                || cue.EndMs > plan.TargetRuntimeMs
                || cue.Text.Any(static ch => char.IsControl(ch))
                || EstimatedWidth(cue.Text, layout) > layout.Width * MaxFitFraction)
            {
                throw new TextOverlayException(TextOverlayException.PlanInvalid);
            }
            previousStart = cue.StartMs;
            prepared.Add(new PreparedOverlayCue(cue, fonts.Resolve(cue.Text)));
        }
        return prepared;
    }

    /// <summary>保守宽度估计：全角/汉字 1.0 em，其余 0.62 em，加两侧 box 边距。</summary>
    private static double EstimatedWidth(string text, TextOverlayLayout layout)
    {
        double ems = 0;
        foreach (var rune in text.EnumerateRunes())
        {
            ems += rune.Value >= 0x2E80 ? 1.0 : LatinEm;
        }
        return (ems * layout.FontSize) + (2 * layout.BoxBorder);
    }

    private static string Seconds(int milliseconds) =>
        string.Create(
            CultureInfo.InvariantCulture,
            $"{milliseconds / 1000}.{milliseconds % 1000:D3}");

    /// <summary>
    /// 只生成内部命名的 drawtext 链：expansion=none 让 textfile 内容永不被当作表达式；
    /// 窗口为 [start, end) 的整数毫秒。
    /// </summary>
    public static string BuildFilterChain(
        TextOverlayLayout layout,
        IReadOnlyList<(PreparedOverlayCue Cue, string FontFile, string TextFile)> items) =>
        string.Join(
            ',',
            items.Select(item =>
                "drawtext="
                + $"fontfile={item.FontFile}:textfile={item.TextFile}:expansion=none"
                + $":fontsize={layout.FontSize}:fontcolor=white:box=1:boxcolor=black@0.5"
                + $":boxborderw={layout.BoxBorder}:x=(w-text_w)/2:y=h*0.78"
                + $":enable='gte(t,{Seconds(item.Cue.Cue.StartMs)})*lt(t,{Seconds(item.Cue.Cue.EndMs)})'"));

    /// <summary>在隔离工作目录渲染并返回已验证的 H.264 MP4（目录内固定内部文件名）。</summary>
    public async Task<(string OutputFileName, TextOverlayMediaFacts Facts)> RenderAsync(
        string sourcePath,
        string workDirectory,
        CaptionOverlayPlanRecord plan,
        IReadOnlyList<PreparedOverlayCue> cues,
        CancellationToken cancellationToken)
    {
        var layout = LayoutFor(plan.OutputProfileId);
        var sourceFacts = await ProbeAsync(sourcePath, workDirectory, cancellationToken).ConfigureAwait(false);
        if (sourceFacts.Width != layout.Width || sourceFacts.Height != layout.Height)
        {
            throw new TextOverlayException(TextOverlayException.SourceInvalid);
        }

        // 去重字体：同一身份只复制一次，文件名为内部生成的 font_NN.<ext>。
        var fontFiles = new Dictionary<string, string>(StringComparer.Ordinal);
        var items = new List<(PreparedOverlayCue Cue, string FontFile, string TextFile)>();
        foreach (var cue in cues)
        {
            if (!fontFiles.TryGetValue(cue.Font.IdentitySha256, out var fontFile))
            {
                fontFile = string.Create(
                    CultureInfo.InvariantCulture,
                    $"font_{fontFiles.Count + 1:D2}{Path.GetExtension(cue.Font.FileName).ToLowerInvariant()}");
                await File.WriteAllBytesAsync(Path.Combine(workDirectory, fontFile), cue.Font.Bytes, cancellationToken)
                    .ConfigureAwait(false);
                fontFiles[cue.Font.IdentitySha256] = fontFile;
            }
            var textFile = string.Create(CultureInfo.InvariantCulture, $"cue_{cue.Cue.Order:D3}.txt");
            await File.WriteAllTextAsync(
                Path.Combine(workDirectory, textFile),
                cue.Cue.Text,
                new UTF8Encoding(false),
                cancellationToken).ConfigureAwait(false);
            items.Add((cue, fontFile, textFile));
        }

        const string outputFileName = "render.mp4";
        var startInfo = NewStartInfo(TextOverlayProcessRunner.Ffmpeg, workDirectory);
        foreach (var argument in new[]
        {
            "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", sourcePath,
            "-vf", BuildFilterChain(layout, items),
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-threads", "1", "-pix_fmt", "yuv420p",
            "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
            "-movflags", "+faststart", "-f", "mp4", outputFileName,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }
        var result = await _runner.RunAsync(startInfo, RenderTimeout, cancellationToken).ConfigureAwait(false);
        if (result.TimedOut)
        {
            throw new TextOverlayException(TextOverlayException.FfmpegTimeout);
        }
        if (result.ExitCode != 0)
        {
            throw new TextOverlayException(TextOverlayException.FfmpegFailed);
        }

        var outputPath = Path.Combine(workDirectory, outputFileName);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(outputPath) || new FileInfo(outputPath).Length <= 0)
        {
            throw new TextOverlayException(TextOverlayException.OutputInvalid);
        }
        var facts = await ProbeAsync(outputPath, workDirectory, cancellationToken).ConfigureAwait(false);
        if (facts.VideoCodec != "h264"
            || facts.PixelFormat != "yuv420p"
            || facts.Width != layout.Width
            || facts.Height != layout.Height
            || facts.HasNonVideoStream
            || Math.Abs(facts.DurationSeconds - sourceFacts.DurationSeconds) > 0.1)
        {
            throw new TextOverlayException(TextOverlayException.OutputInvalid);
        }
        return (outputFileName, facts);
    }

    /// <summary>ffprobe 读取固定字段；解析失败按源/输出无效处理，stderr 永不外泄。</summary>
    public async Task<TextOverlayMediaFacts> ProbeAsync(
        string mediaPath,
        string workDirectory,
        CancellationToken cancellationToken)
    {
        var startInfo = NewStartInfo(TextOverlayProcessRunner.Ffprobe, workDirectory);
        foreach (var argument in new[]
        {
            "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,width,height,pix_fmt:format=duration",
            "-of", "json", mediaPath,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }
        var result = await _runner.RunAsync(startInfo, ProbeTimeout, cancellationToken).ConfigureAwait(false);
        if (result.TimedOut)
        {
            throw new TextOverlayException(TextOverlayException.FfmpegTimeout);
        }
        if (result.ExitCode != 0)
        {
            throw new TextOverlayException(TextOverlayException.OutputInvalid);
        }
        try
        {
            using var document = JsonDocument.Parse(result.Stdout);
            var streams = document.RootElement.GetProperty("streams");
            var video = streams.EnumerateArray()
                .FirstOrDefault(static item => item.TryGetProperty("codec_type", out var type)
                    && type.GetString() == "video");
            if (video.ValueKind != JsonValueKind.Object)
            {
                throw new TextOverlayException(TextOverlayException.OutputInvalid);
            }
            var hasOther = streams.EnumerateArray().Any(static item =>
                !item.TryGetProperty("codec_type", out var type) || type.GetString() != "video");
            var duration = double.Parse(
                document.RootElement.GetProperty("format").GetProperty("duration").GetString()!,
                CultureInfo.InvariantCulture);
            return new TextOverlayMediaFacts(
                video.GetProperty("codec_name").GetString() ?? string.Empty,
                video.GetProperty("pix_fmt").GetString() ?? string.Empty,
                video.GetProperty("width").GetInt32(),
                video.GetProperty("height").GetInt32(),
                duration,
                hasOther);
        }
        catch (Exception exception) when (exception is JsonException
            or KeyNotFoundException
            or InvalidOperationException
            or FormatException)
        {
            throw new TextOverlayException(TextOverlayException.OutputInvalid, exception);
        }
    }

    private static ProcessStartInfo NewStartInfo(string executable, string workDirectory) => new()
    {
        FileName = executable,
        WorkingDirectory = workDirectory,
        UseShellExecute = false,
        CreateNoWindow = true,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
    };
}
