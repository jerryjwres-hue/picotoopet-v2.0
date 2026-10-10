using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;
using PicotooPet.Desktop.Services;

namespace PicotooPet.PostProductionMasterMux.SmokeTests;

/// <summary>
/// 真实 Windows 验收：实际 ffmpeg.exe/ffprobe.exe。覆盖 C005 的三种 24 fps 输出档位，证明 stream-copy
/// （packet MD5 相等）、AAC-LC/48k/mono、定时摆放与静音、立体声 0.5/0.5 平均、取消/超时有界、失败无输出。
/// 缺环境返回 UNVERIFIED，绝不伪造 PASS。
/// </summary>
internal static class RealWindowsAcceptance
{
    private static readonly (string Name, int Width, int Height)[] Profiles =
    [
        ("landscape", 832, 480),
        ("vertical", 480, 832),
        ("square", 640, 640),
    ];

    public static async Task<string> RunAsync()
    {
        if (!OperatingSystem.IsWindows())
        {
            return "UNVERIFIED(not windows)";
        }
        var runner = new FixedMasterVideoProcessRunner();
        var root = Path.Combine(Path.GetTempPath(), "picotoo-mux-real-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            string version;
            try
            {
                version = (await RunAsync(runner, "ffmpeg.exe", ["-hide_banner", "-version"], root).ConfigureAwait(false)).Stdout;
                var probeVersion = await RunAsync(runner, "ffprobe.exe", ["-hide_banner", "-version"], root).ConfigureAwait(false);
                if (probeVersion.ExitCode != 0)
                {
                    return "UNVERIFIED(ffprobe.exe unavailable)";
                }
            }
            catch (MasterVideoComposerException)
            {
                return "UNVERIFIED(ffmpeg.exe unavailable)";
            }
            var encoders = (await RunAsync(runner, "ffmpeg.exe", ["-hide_banner", "-encoders"], root).ConfigureAwait(false)).Stdout;
            if (!Regex.IsMatch(encoders, @"^\s*A\S*\s+aac\s", RegexOptions.Multiline))
            {
                return "UNVERIFIED(native aac encoder unavailable)";
            }
            Console.WriteLine("MASTER_MUX_FFMPEG=" + version.Split('\n', 2)[0].Trim());

            foreach (var (name, width, height) in Profiles)
            {
                await VerifyProfileAsync(runner, Path.Combine(root, name), name, width, height).ConfigureAwait(false);
                Console.WriteLine($"MASTER_MUX_REAL_{name.ToUpperInvariant()}=PASS");
            }
            await VerifyZeroNarrationAsync(runner, Path.Combine(root, "zero")).ConfigureAwait(false);
            await VerifyBoundedAndFailureAsync(runner, Path.Combine(root, "bounded")).ConfigureAwait(false);
            return "PASS";
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    private static async Task<MasterVideoProcessResult> RunAsync(
        IMasterVideoProcessRunner runner,
        string executable,
        IEnumerable<string> arguments,
        string workingDirectory,
        TimeSpan? timeout = null,
        CancellationToken cancellationToken = default)
    {
        var startInfo = new ProcessStartInfo { FileName = executable, UseShellExecute = false, WorkingDirectory = workingDirectory };
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }
        return await runner.RunAsync(startInfo, timeout ?? TimeSpan.FromMinutes(2), cancellationToken).ConfigureAwait(false);
    }

    /// <summary>固定 H.264/yuv420p 24 fps 视觉源（lavfi testsrc2，仅用于验收）。</summary>
    private static async Task<string> GenerateVisualAsync(IMasterVideoProcessRunner runner, string directory, int width, int height)
    {
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "visual.mp4");
        var result = await RunAsync(runner, "ffmpeg.exe",
        [
            "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", $"testsrc2=s={width}x{height}:r=24:d=6.000",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-x264-params", "keyint=24",
            "-f", "mp4", path,
        ], directory).ConfigureAwait(false);
        Check.Equal(0, result.ExitCode, "生成视觉源");
        return path;
    }

    private static async Task<string?> PacketMd5Async(IMasterVideoProcessRunner runner, string file)
    {
        var result = await RunAsync(runner, "ffmpeg.exe",
            ["-hide_banner", "-loglevel", "error", "-nostdin", "-i", file, "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"],
            Path.GetDirectoryName(file)!).ConfigureAwait(false);
        var match = Regex.Match(result.Stdout, "MD5=([0-9a-f]{32})");
        return result.ExitCode == 0 && match.Success ? match.Groups[1].Value : null;
    }

    private static async Task VerifyProfileAsync(IMasterVideoProcessRunner runner, string directory, string name, int width, int height)
    {
        var visualPath = await GenerateVisualAsync(runner, directory, width, height).ConfigureAwait(false);
        var visualBytes = await File.ReadAllBytesAsync(visualPath).ConfigureAwait(false);
        var visual = new VerifiedMasterVisual(visualPath, TestMedia.Sha(visualBytes), visualBytes.LongLength, "c004");

        // seg1 单声道 24 kHz 1500 ms @0（窗口 [0,2000) → 短于窗口）；seg2 立体声(L=R) 44.1 kHz 1500 ms @2500；
        // seg3 单声道 48 kHz 1000 ms @4500（窗口 [4500,6000)）。静音：1500–2500、4000–4500、5500–6000。
        var segments = new List<VerifiedMasterNarrationSegment>
        {
            TestMedia.Segment(directory, 1, 24000, 1, 36000, 0, 2000, 440),
            TestMedia.Segment(directory, 2, 44100, 2, 66150, 2500, 4500, 660),
            TestMedia.Segment(directory, 3, 48000, 1, 48000, 4500, 6000, 880),
        };
        var output = Path.Combine(directory, "work");
        Directory.CreateDirectory(output);
        var outputPath = Path.Combine(output, "master.mp4");
        await new FixedFfmpegMasterVideoComposer().ComposeAsync(
            new MasterVideoCompositionRequest(visual, segments, 6000, outputPath), CancellationToken.None)
            .ConfigureAwait(false);

        // 视频 stream-copy：packet MD5 输入 == 输出。
        var inputMd5 = await PacketMd5Async(runner, visualPath).ConfigureAwait(false);
        var outputMd5 = await PacketMd5Async(runner, outputPath).ConfigureAwait(false);
        Check.True(inputMd5 is not null && inputMd5 == outputMd5, $"{name}: 视频 packet MD5 必须相等");

        // ffprobe：1 视频 + 1 音频；视频元数据不变；AAC LC/48k/mono。
        var probe = new MasterVideoMediaProbe(runner);
        var input = await probe.ProbeAsync(visualPath, CancellationToken.None).ConfigureAwait(false);
        var final = await probe.ProbeAsync(outputPath, CancellationToken.None).ConfigureAwait(false);
        Check.Equal((1, 1, 0), (final.VideoStreams, final.AudioStreams, final.OtherStreams), $"{name}: 1 视频 + 1 音频");
        Check.Equal(input.Video, final.Video, $"{name}: 视频事实（尺寸/fps/像素格式/packet 数）不变");
        Check.Equal(width, final.Video!.Width, $"{name}: 宽");
        Check.Equal(height, final.Video.Height, $"{name}: 高");
        Check.Equal(new MasterAudioStreamFacts("aac", "LC", 48000, 1), final.Audio, $"{name}: AAC-LC/48k/mono");
        Check.True(Math.Abs(final.DurationSeconds - 6.0) <= FixedFfmpegMasterVideoComposer.DurationToleranceSeconds, $"{name}: 时长");

        // 音频摆放：解码为 48 kHz s16le，检查音调窗口与静音窗口，及立体声平均（不放大/不削波）。
        var rawPath = Path.Combine(output, "decoded.raw");
        var decode = await RunAsync(runner, "ffmpeg.exe",
            ["-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", outputPath, "-map", "0:a:0",
             "-f", "s16le", "-ac", "1", "-ar", "48000", rawPath], output).ConfigureAwait(false);
        Check.Equal(0, decode.ExitCode, $"{name}: 解码音频");
        var pcm = await File.ReadAllBytesAsync(rawPath).ConfigureAwait(false);
        (int Start, int End, int Hz, string Label)[] tones = [(150, 1350, 440, "seg1"), (2650, 3850, 660, "seg2"), (4650, 5350, 880, "seg3")];
        var rms = new List<double>();
        foreach (var tone in tones)
        {
            var level = TestMedia.Rms(pcm, tone.Start, tone.End);
            rms.Add(level);
            Check.True(level >= 3000, $"{name}/{tone.Label}: 音调窗口必须有声");
            Check.Equal(tone.Hz, TestMedia.StrongestTone(pcm, tone.Start, tone.End, 440, 660, 880), $"{name}/{tone.Label}: 主频");
        }
        foreach (var gap in new (int Start, int End, string Label)[] { (1650, 2350, "gap1"), (4150, 4350, "gap2"), (5650, 5850, "gap3") })
        {
            Check.True(TestMedia.Rms(pcm, gap.Start, gap.End) <= 200, $"{name}/{gap.Label}: 静音窗口必须静音");
        }
        // 立体声(L=R) 平均后幅度应与同幅单声道接近（±20%），且峰值远离削波。
        Check.True(Math.Abs(rms[1] - rms[0]) / rms[0] < 0.2, $"{name}: 立体声平均后不得放大/衰减超过 20%");
        Check.True(TestMedia.PeakAbs(pcm) < 30000, $"{name}: 不得削波");
    }

    private static async Task VerifyZeroNarrationAsync(IMasterVideoProcessRunner runner, string directory)
    {
        var visualPath = await GenerateVisualAsync(runner, directory, 832, 480).ConfigureAwait(false);
        var bytes = await File.ReadAllBytesAsync(visualPath).ConfigureAwait(false);
        var visual = new VerifiedMasterVisual(visualPath, TestMedia.Sha(bytes), bytes.LongLength, "c004");
        var output = Path.Combine(directory, "work");
        Directory.CreateDirectory(output);
        var outputPath = Path.Combine(output, "master.mp4");
        await new FixedFfmpegMasterVideoComposer().ComposeAsync(
            new MasterVideoCompositionRequest(visual, [], 6000, outputPath), CancellationToken.None).ConfigureAwait(false);
        Check.Equal(visual.Sha256, TestMedia.Sha(await File.ReadAllBytesAsync(outputPath).ConfigureAwait(false)), "零旁白输出逐字节相同");
        var facts = await new MasterVideoMediaProbe(runner).ProbeAsync(outputPath, CancellationToken.None).ConfigureAwait(false);
        Check.Equal(0, facts.AudioStreams, "零旁白不得引入音频");
        Console.WriteLine("MASTER_MUX_REAL_ZERO_NARRATION=PASS");
    }

    /// <summary>取消/超时有界、失败无输出（使用真实命令形状 + 超长循环时间线）。</summary>
    private static async Task VerifyBoundedAndFailureAsync(IMasterVideoProcessRunner runner, string directory)
    {
        var visualPath = await GenerateVisualAsync(runner, directory, 832, 480).ConfigureAwait(false);
        var bytes = await File.ReadAllBytesAsync(visualPath).ConfigureAwait(false);
        var visual = new VerifiedMasterVisual(visualPath, TestMedia.Sha(bytes), bytes.LongLength, "c004");
        var segment = TestMedia.Segment(directory, 1, 48000, 1, 48000, 0, 2000, 440);
        var longArguments = FixedFfmpegMasterVideoComposer.BuildMuxArguments(
            visualPath, [segment], 7_200_000, Path.Combine(directory, "stress.partial.mp4")).ToList();
        longArguments.Insert(longArguments.IndexOf("-i"), "-stream_loop");
        longArguments.Insert(longArguments.IndexOf("-stream_loop") + 1, "-1");
        longArguments.InsertRange(longArguments.IndexOf("-f"), ["-t", "7200.000"]);

        var ffmpegBefore = Process.GetProcessesByName("ffmpeg").Length;
        var clock = Stopwatch.StartNew();
        using (var source = new CancellationTokenSource())
        {
            source.CancelAfter(TimeSpan.FromMilliseconds(300));
            try
            {
                await RunAsync(runner, "ffmpeg.exe", longArguments, directory, TimeSpan.FromMinutes(10), source.Token)
                    .ConfigureAwait(false);
                throw new InvalidOperationException("取消必须抛出");
            }
            catch (OperationCanceledException)
            {
                // 预期：进程树已被结束。
            }
        }
        Check.True(clock.ElapsedMilliseconds <= 8000, "取消必须有界");

        clock.Restart();
        var timedOut = await RunAsync(runner, "ffmpeg.exe", longArguments, directory, TimeSpan.FromSeconds(1)).ConfigureAwait(false);
        Check.True(timedOut.TimedOut && clock.ElapsedMilliseconds <= 8000, "超时必须有界");
        await Task.Delay(500).ConfigureAwait(false);
        Check.True(Process.GetProcessesByName("ffmpeg").Length <= ffmpegBefore, "不得残留 ffmpeg 孤儿进程");
        var stress = Path.Combine(directory, "stress.partial.mp4");
        if (File.Exists(stress))
        {
            File.Delete(stress);
        }

        // 失败（视觉 SHA 正确但不是有效 MP4）→ 不得留下输出。
        var garbage = Encoding.ASCII.GetBytes("not an mp4 at all");
        var garbagePath = Path.Combine(directory, "garbage.mp4");
        await File.WriteAllBytesAsync(garbagePath, garbage).ConfigureAwait(false);
        var work = Path.Combine(directory, "fail-work");
        Directory.CreateDirectory(work);
        var failedOutput = Path.Combine(work, "master.mp4");
        try
        {
            await new FixedFfmpegMasterVideoComposer().ComposeAsync(
                new MasterVideoCompositionRequest(
                    new VerifiedMasterVisual(garbagePath, TestMedia.Sha(garbage), garbage.LongLength, "c004"),
                    [segment], 6000, failedOutput),
                CancellationToken.None).ConfigureAwait(false);
            throw new InvalidOperationException("无效视觉必须失败");
        }
        catch (MasterVideoComposerException)
        {
            // 预期。
        }
        Check.True(!File.Exists(failedOutput), "失败后不得留下输出");
        Console.WriteLine("MASTER_MUX_REAL_BOUNDED_AND_FAILURE=PASS");
    }
}
