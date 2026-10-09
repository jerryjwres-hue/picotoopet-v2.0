using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.CaptionOverlay.SmokeTests;

/// <summary>
/// 真实 Windows 验收：实际 ffmpeg.exe/ffprobe.exe + 已安装系统字体，处理一份英文和一份中文计划并验证复用。
/// 缺少 ffmpeg 或字体时打印 UNVERIFIED，绝不伪造 PASS。
/// </summary>
internal static class RealFfmpegTests
{
    public static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows())
        {
            Console.WriteLine("CAPTION_OVERLAY_REAL_WINDOWS=UNVERIFIED(not windows)");
            return;
        }
        var workspace = Path.Combine(Path.GetTempPath(), "picotoo-overlay-real-" + Guid.NewGuid().ToString("N"));
        try
        {
            var finalRoot = Path.Combine(workspace, "FinalVideos");
            var overlayRoot = Path.Combine(workspace, "TextOverlay", "v1");
            Directory.CreateDirectory(finalRoot);
            var identity = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("job-1"))).ToLowerInvariant()[..32];
            var sourcePath = Path.Combine(finalRoot, $"final-{identity}.mp4");

            if (!await GenerateSourceAsync(sourcePath).ConfigureAwait(false))
            {
                Console.WriteLine("CAPTION_OVERLAY_REAL_WINDOWS=UNVERIFIED(ffmpeg.exe unavailable)");
                return;
            }
            var sourceBytes = await File.ReadAllBytesAsync(sourcePath).ConfigureAwait(false);
            var source = new FinalVideoArtifact(
                "job-1",
                "package-1",
                new string('e', 64),
                sourcePath,
                Path.Combine(finalRoot, $"final-{identity}.final-video.json"),
                Convert.ToHexString(SHA256.HashData(sourceBytes)).ToLowerInvariant(),
                sourceBytes.LongLength,
                false);
            var service = new WindowsCaptionOverlayService(
                new WindowsCaptionOverlayRenderer(new TextOverlayProcessRunner()),
                new WindowsTextOverlayFontPolicy(),
                finalRoot,
                overlayRoot,
                TimeProvider.System);

            foreach (var (label, text) in new[] { ("english", "Caption Test: PicotooPet 0123"), ("chinese", "字幕测试：皮卡图宠物") })
            {
                var plan = Fixture.Plan(("c1", text, 1000, 3000));
                try
                {
                    var first = await service.ApplyAsync(source, plan, CancellationToken.None).ConfigureAwait(false);
                    SmokeAssert.True(new FileInfo(first.FilePath).Length > 0, $"{label} 输出非空");
                    var second = await service.ApplyAsync(source, plan, CancellationToken.None).ConfigureAwait(false);
                    SmokeAssert.True(second.Reused, $"{label} 重启后复用");
                    SmokeAssert.Equal(first.Sha256, second.Sha256, $"{label} 复用同一输出");
                    Console.WriteLine($"CAPTION_OVERLAY_REAL_{label.ToUpperInvariant()}=PASS");
                }
                catch (TextOverlayException exception) when (exception.Code is TextOverlayException.FontUnavailable
                    or TextOverlayException.GlyphMissing)
                {
                    Console.WriteLine($"CAPTION_OVERLAY_REAL_{label.ToUpperInvariant()}=UNVERIFIED({exception.Code})");
                }
            }
        }
        finally
        {
            if (Directory.Exists(workspace))
            {
                Directory.Delete(workspace, recursive: true);
            }
        }
    }

    /// <summary>固定 lavfi 彩色源，832x480@24 的 6 秒 H.264 MP4（等同 C004 最终产物形态）。</summary>
    private static async Task<bool> GenerateSourceAsync(string outputPath)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "ffmpeg.exe",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in new[]
        {
            "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "color=c=0x203040:s=832x480:r=24:d=6",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", outputPath,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }
        try
        {
            var result = await new TextOverlayProcessRunner()
                .RunAsync(startInfo, TimeSpan.FromMinutes(2), CancellationToken.None).ConfigureAwait(false);
            return result.ExitCode == 0 && File.Exists(outputPath);
        }
        catch (TextOverlayException)
        {
            return false;
        }
    }
}
