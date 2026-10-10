using System.ComponentModel;
using System.Diagnostics;
using PicotooPet.Desktop.Services;

namespace PicotooPet.PostProductionMasterMux.SmokeTests;

/// <summary>
/// C009B 加固的真实 Windows 验收：持有的 FileShare.Read 句柄与真实 ffprobe/ffmpeg 兼容、
/// composer 持有句柄期间（每次进程调用点）的替换/删除/改写全部被拒绝、Kill 失败不覆盖取消/超时语义、取消后无泄漏输出与孤儿进程。
/// 缺环境返回 UNVERIFIED，绝不伪造 PASS。
/// </summary>
internal static class RealHardening
{
    public static async Task<string> RunAsync()
    {
        if (!OperatingSystem.IsWindows())
        {
            return "UNVERIFIED(not windows)";
        }
        var root = Path.Combine(Path.GetTempPath(), "picotoo-mux-hard-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var runner = new FixedMasterVideoProcessRunner();
            try
            {
                var probe = await RealWindowsAcceptance.RunAsync(runner, "ffprobe.exe", ["-hide_banner", "-version"], root).ConfigureAwait(false);
                var mpeg = await RealWindowsAcceptance.RunAsync(runner, "ffmpeg.exe", ["-hide_banner", "-version"], root).ConfigureAwait(false);
                if (probe.ExitCode != 0 || mpeg.ExitCode != 0)
                {
                    return "UNVERIFIED(ffmpeg/ffprobe unavailable)";
                }
            }
            catch (MasterVideoComposerException)
            {
                return "UNVERIFIED(ffmpeg/ffprobe unavailable)";
            }

            await HeldHandlesAsync(runner, Path.Combine(root, "held")).ConfigureAwait(false);
            Console.WriteLine("MASTER_MUX_HARDENING_REAL_HELD_HANDLES=PASS");
            await KillSemanticsAsync(Path.Combine(root, "kill")).ConfigureAwait(false);
            Console.WriteLine("MASTER_MUX_HARDENING_REAL_KILL_SEMANTICS=PASS");
            await CancelMidMuxAsync(runner, Path.Combine(root, "cancel")).ConfigureAwait(false);
            Console.WriteLine("MASTER_MUX_HARDENING_REAL_CANCEL_NO_LEAK=PASS");
            return "PASS";
        }
        finally
        {
            DeleteBestEffort(root);
        }
    }

    /// <summary>测试临时目录清理：重试后仍被占用也不得掩盖真正的断言失败。</summary>
    private static void DeleteBestEffort(string root)
    {
        for (var attempt = 0; attempt < 5 && Directory.Exists(root); attempt++)
        {
            try
            {
                Directory.Delete(root, recursive: true);
            }
            catch (IOException)
            {
                Thread.Sleep(500);
            }
            catch (UnauthorizedAccessException)
            {
                Thread.Sleep(500);
            }
        }
    }

    private static async Task<(VerifiedMasterVisual Visual, VerifiedMasterNarrationSegment Segment)> PrepareAsync(
        IMasterVideoProcessRunner runner, string directory)
    {
        var visualPath = await RealWindowsAcceptance.GenerateVisualAsync(runner, directory, 832, 480).ConfigureAwait(false);
        var bytes = await File.ReadAllBytesAsync(visualPath).ConfigureAwait(false);
        var visual = new VerifiedMasterVisual(visualPath, TestMedia.Sha(bytes), bytes.LongLength, "c004");
        var segment = TestMedia.Segment(directory, 1, 48000, 1, 48000, 500, 1500, 440);
        return (visual, segment);
    }

    /// <summary>每次 ffprobe/ffmpeg 调用点（句柄由 composer 持有，且真实进程随后读取），视觉与 WAV 的写入/删除/重命名/覆盖都必须被拒绝，且合成仍成功。</summary>
    private static async Task HeldHandlesAsync(IMasterVideoProcessRunner inner, string directory)
    {
        var (visual, segment) = await PrepareAsync(inner, directory).ConfigureAwait(false);
        var work = Path.Combine(directory, "work");
        Directory.CreateDirectory(work);
        var output = Path.Combine(work, "master.mp4");
        var observer = new ObservingRunner(inner, info =>
        {
            foreach (var target in new[] { visual.Path, segment.WavPath })
            {
                AssertBlocked(() => File.WriteAllBytes(target, [0, 1, 2]), "写入", target);
                AssertBlocked(() => File.Delete(target), "删除", target);
                AssertBlocked(() => File.Move(target, target + ".moved"), "重命名", target);
                AssertBlocked(() => File.Copy(Path.Combine(work, "nonexistent"), target, true), "覆盖", target);
                using var read = new FileStream(target, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            }
        });
        await new FixedFfmpegMasterVideoComposer(observer).ComposeAsync(
            new MasterVideoCompositionRequest(visual, [segment], 6000, output), CancellationToken.None).ConfigureAwait(false);
        Check.True(observer.Observed >= 2, "必须观察到 ffprobe 与 ffmpeg 进程运行");
        Check.True(File.Exists(output), "持有句柄时合成必须成功");
        // 成功后句柄已释放。
        File.Move(visual.Path, visual.Path + ".after");
        File.Move(segment.WavPath, segment.WavPath + ".after");
    }

    private static void AssertBlocked(Action action, string operation, string target)
    {
        try
        {
            action();
        }
        catch (IOException)
        {
            return;
        }
        catch (UnauthorizedAccessException)
        {
            return;
        }
        throw new InvalidOperationException($"运行期间对输入的{operation}未被阻止：{Path.GetFileName(target)}");
    }

    private static List<string> StressArguments(string directory, string stressOutput)
    {
        var wav = TestMedia.Segment(directory, 9, 48000, 1, 48000, 0, 2000, 440);
        var arguments = FixedFfmpegMasterVideoComposer.BuildMuxArguments(
            Path.Combine(directory, "visual.mp4"), [wav], 7_200_000, stressOutput).ToList();
        arguments.Insert(arguments.IndexOf("-i"), "-stream_loop");
        arguments.Insert(arguments.IndexOf("-stream_loop") + 1, "-1");
        arguments.InsertRange(arguments.IndexOf("-f"), ["-t", "7200.000"]);
        return arguments;
    }

    /// <summary>注入 Kill 失败：已知异常不改变超时/取消语义，兜底终止进程；无关异常传播且不留孤儿。</summary>
    private static async Task KillSemanticsAsync(string directory)
    {
        var helper = new FixedMasterVideoProcessRunner();
        await RealWindowsAcceptance.GenerateVisualAsync(helper, directory, 640, 360).ConfigureAwait(false);
        var args = StressArguments(directory, Path.Combine(directory, "stress.partial.mp4"));
        var before = Process.GetProcessesByName("ffmpeg").Length;

        var knownFailures = new (string Name, Action<Process> Killer)[]
        {
            ("AggregateException", _ => throw new AggregateException(new Win32Exception(5))),
            ("NotSupportedException", _ => throw new NotSupportedException()),
            ("Win32Exception", _ => throw new Win32Exception(5)),
            ("InvalidOperationException", _ => throw new InvalidOperationException()),
            ("no-op killer", _ => { }),
        };
        foreach (var (name, killer) in knownFailures)
        {
            var runner = new FixedMasterVideoProcessRunner(killer);
            var clock = Stopwatch.StartNew();
            var timedOut = await RealWindowsAcceptance.RunAsync(runner, "ffmpeg.exe", args, directory, TimeSpan.FromSeconds(1)).ConfigureAwait(false);
            Check.True(timedOut.TimedOut, $"Kill 失败（{name}）不得改变超时语义");
            Check.True(!timedOut.CleanupIncomplete, $"兜底终止后清理应完成（{name}）");
            // 设计上界：1 s 超时 + 5 s 终止宽限 + 进程启动；CI 负载下留足余量，仍远小于无界。
            Check.True(clock.ElapsedMilliseconds <= 30000, $"超时必须有界（{name}）elapsedMs={clock.ElapsedMilliseconds}");

            using var source = new CancellationTokenSource(TimeSpan.FromMilliseconds(300));
            var cancelled = false;
            try
            {
                await RealWindowsAcceptance.RunAsync(runner, "ffmpeg.exe", args, directory, TimeSpan.FromMinutes(10), source.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                cancelled = true;
            }
            Check.True(cancelled, $"Kill 失败（{name}）不得改变取消语义");
        }

        var unrelated = new FixedMasterVideoProcessRunner(_ => throw new FormatException("unrelated"));
        try
        {
            await RealWindowsAcceptance.RunAsync(unrelated, "ffmpeg.exe", args, directory, TimeSpan.FromSeconds(1)).ConfigureAwait(false);
            throw new InvalidOperationException("无关异常必须传播");
        }
        catch (FormatException)
        {
            // 预期：不被吞掉，且 finally 兜底已结束进程。
        }

        await Task.Delay(1000).ConfigureAwait(false);
        Check.True(Process.GetProcessesByName("ffmpeg").Length <= before, "不得残留 ffmpeg 孤儿进程");
    }

    /// <summary>真实 mux 中途取消：抛出取消、不留 master.mp4/partial、不残留孤儿进程、输入句柄已释放。</summary>
    private static async Task CancelMidMuxAsync(IMasterVideoProcessRunner inner, string directory)
    {
        var (visual, segment) = await PrepareAsync(inner, directory).ConfigureAwait(false);
        var work = Path.Combine(directory, "work");
        Directory.CreateDirectory(work);
        var output = Path.Combine(work, "master.mp4");
        var before = Process.GetProcessesByName("ffmpeg").Length;
        using var source = new CancellationTokenSource();
        var observer = new ObservingRunner(inner, info =>
        {
            if (info.FileName == "ffmpeg.exe" && !info.ArgumentList.Contains("-version"))
            {
                source.Cancel();
            }
        });
        var cancelled = false;
        try
        {
            await new FixedFfmpegMasterVideoComposer(observer).ComposeAsync(
                new MasterVideoCompositionRequest(visual, [segment], 6000, output), source.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            cancelled = true;
        }
        Check.True(cancelled, "中途取消必须抛出取消");
        Check.True(!File.Exists(output), "取消后不得留下输出");
        Check.True(Directory.GetFiles(work).Length == 0, "取消后工作目录不得有残留文件");
        await Task.Delay(1000).ConfigureAwait(false);
        Check.True(Process.GetProcessesByName("ffmpeg").Length <= before, "不得残留 ffmpeg 孤儿进程");
        File.Move(visual.Path, visual.Path + ".after");
        File.Move(segment.WavPath, segment.WavPath + ".after");
    }

    private sealed class ObservingRunner(IMasterVideoProcessRunner inner, Action<ProcessStartInfo> onStart) : IMasterVideoProcessRunner
    {
        public int Observed { get; private set; }

        public async Task<MasterVideoProcessResult> RunAsync(ProcessStartInfo startInfo, TimeSpan timeout, CancellationToken cancellationToken)
        {
            Observed++;
            // 此时 composer 已持有输入句柄；先在“进程启动前”的窗口触发观察动作。
            onStart(startInfo);
            return await inner.RunAsync(startInfo, timeout, cancellationToken).ConfigureAwait(false);
        }
    }
}
