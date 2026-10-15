using System.ComponentModel;
using System.Diagnostics;
using PicotooPet.Desktop.Services;

namespace PicotooPet.PostProductionMasterMux.SmokeTests;

/// <summary>
/// C009B Job Object fail-closed 的真实 Windows 验收（Issue #83）：
/// 注入 Job 创建失败、入 Job 失败（系统真实拒绝）、入 Job 校验失败 + 进程树 Kill 失败、终止被抑制；
/// 用真实 ffmpeg 进程与 PID 谱系断言“不留后代、不虚报清理成功”，并验证参数引号往返。
/// 缺环境返回 UNVERIFIED，绝不伪造 PASS。
/// </summary>
internal static class RealFailClosed
{
    public static async Task<string> RunAsync()
    {
        if (!OperatingSystem.IsWindows())
        {
            return "UNVERIFIED(not windows)";
        }
        var root = Path.Combine(Path.GetTempPath(), "picotoo mux failclosed " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var runner = new FixedMasterVideoProcessRunner();
            try
            {
                var version = await RealWindowsAcceptance.RunAsync(runner, "ffmpeg.exe", ["-hide_banner", "-version"], root).ConfigureAwait(false);
                if (version.ExitCode != 0)
                {
                    return "UNVERIFIED(ffmpeg unavailable)";
                }
            }
            catch (MasterVideoComposerException)
            {
                return "UNVERIFIED(ffmpeg unavailable)";
            }

            await ArgvRoundTripAsync(runner, Path.Combine(root, "argv dir")).ConfigureAwait(false);
            Console.WriteLine("MASTER_MUX_FAILCLOSED_ARGV_ROUNDTRIP=PASS");
            await NothingStartedAsync(root, ProcessContainmentFaults.FailJobCreation, "JOB_CREATE").ConfigureAwait(false);
            await NothingStartedAsync(root, ProcessContainmentFaults.FailEnrollment, "ENROLL").ConfigureAwait(false);
            await VerificationFailureAsync(Path.Combine(root, "verify")).ConfigureAwait(false);
            await SuppressedTerminationAsync(Path.Combine(root, "suppress")).ConfigureAwait(false);
            return "PASS";
        }
        finally
        {
            for (var attempt = 0; attempt < 5 && Directory.Exists(root); attempt++)
            {
                try
                {
                    Directory.Delete(root, recursive: true);
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    await Task.Delay(500).ConfigureAwait(false);
                }
            }
        }
    }

    /// <summary>CreateProcess 命令行拼接必须与 CommandLineToArgvW 往返：空格目录、引号、反斜杠、结尾反斜杠。</summary>
    private static async Task ArgvRoundTripAsync(IMasterVideoProcessRunner runner, string directory)
    {
        Directory.CreateDirectory(directory);
        var title = "a \"quoted\" b\\ c \\\\\"d\\";
        var output = Path.Combine(directory, "tagged.mp4");
        var made = await RealWindowsAcceptance.RunAsync(runner, "ffmpeg.exe",
        [
            "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=64x64:r=24:d=0.5",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-metadata", "title=" + title, "-f", "mp4", output,
        ], directory).ConfigureAwait(false);
        Check.Equal(0, made.ExitCode, "含空格路径与特殊参数的 ffmpeg 必须成功");
        var probed = await RealWindowsAcceptance.RunAsync(runner, "ffprobe.exe",
            ["-hide_banner", "-loglevel", "error", "-show_entries", "format_tags=title", "-of", "default=nw=1:nk=1", output], directory)
            .ConfigureAwait(false);
        Check.Equal(0, probed.ExitCode, "ffprobe 必须成功");
        Check.Equal(title, probed.Stdout.TrimEnd('\r', '\n'), "参数必须无损往返");
    }

    private static HashSet<int> OwnFfmpegChildren()
    {
        var self = Environment.ProcessId;
        return ProcessLineage.Snapshot().Values
            .Where(e => e.ParentPid == self && e.ExeName.Equals("ffmpeg.exe", StringComparison.OrdinalIgnoreCase))
            .Select(e => e.Pid)
            .ToHashSet();
    }

    private static List<string> StressArguments(string directory)
    {
        var visual = Path.Combine(directory, "visual.mp4");
        var wav = TestMedia.Segment(directory, 9, 48000, 1, 48000, 0, 2000, 440);
        var arguments = FixedFfmpegMasterVideoComposer.BuildMuxArguments(
            visual, [wav], 7_200_000, Path.Combine(directory, "stress.partial.mp4")).ToList();
        arguments.Insert(arguments.IndexOf("-i"), "-stream_loop");
        arguments.Insert(arguments.IndexOf("-stream_loop") + 1, "-1");
        arguments.InsertRange(arguments.IndexOf("-f"), ["-t", "7200.000"]);
        return arguments;
    }

    /// <summary>Job 创建失败 / 系统拒绝入 Job：封闭错误码、不启动任何进程、清理标记为已完成。</summary>
    private static async Task NothingStartedAsync(string root, ProcessContainmentFaults fault, string marker)
    {
        var directory = Path.Combine(root, marker);
        Directory.CreateDirectory(directory);
        var before = OwnFfmpegChildren();
        var killerCalls = 0;
        var runner = new FixedMasterVideoProcessRunner(_ => killerCalls++, fault);
        var clock = Stopwatch.StartNew();
        MasterVideoComposerException? failure = null;
        try
        {
            await RealWindowsAcceptance.RunAsync(runner, "ffmpeg.exe", ["-hide_banner", "-version"], directory).ConfigureAwait(false);
        }
        catch (MasterVideoComposerException exception)
        {
            failure = exception;
        }
        Check.True(failure is not null, $"{marker}：必须失败而不是静默退化");
        Check.Equal(MasterVideoComposerException.ProcessContainmentFailed, failure!.Code, $"{marker}：封闭错误码");
        Check.True(!failure.CleanupIncomplete, $"{marker}：没有启动任何进程，不应报告清理未完成");
        Check.Equal(0, killerCalls, $"{marker}：没有进程可终止");
        Check.True(clock.ElapsedMilliseconds <= 15000, $"{marker}：必须有界");
        await Task.Delay(500).ConfigureAwait(false);
        var started = OwnFfmpegChildren().Except(before).ToList();
        Check.True(started.Count == 0, $"{marker}：不得启动 ffmpeg 子进程 [{string.Join(',', started)}]");
        Console.WriteLine($"MASTER_MUX_FAILCLOSED_{marker}=PASS");
    }

    /// <summary>进程已启动但入 Job 校验失败，且进程树 Kill 同时失败：必须靠 Job 终止，后代为 0，不留进程，不虚报。</summary>
    private static async Task VerificationFailureAsync(string directory)
    {
        var helper = new FixedMasterVideoProcessRunner();
        await RealWindowsAcceptance.GenerateVisualAsync(helper, directory, 640, 360).ConfigureAwait(false);
        var args = StressArguments(directory);
        var rootPid = -1;
        var childrenSeen = 0;
        var killerCalls = 0;
        var runner = new FixedMasterVideoProcessRunner(
            process =>
            {
                killerCalls++;
                rootPid = process.Id;
                // 让根进程有时间产生后代，证明清理的确面对着一个真实的后代。
                Thread.Sleep(1000);
                childrenSeen = ProcessLineage.Snapshot().Values.Count(e => e.ParentPid == rootPid);
                throw new AggregateException(new Win32Exception(5));
            },
            ProcessContainmentFaults.FailEnrollmentVerification);

        var clock = Stopwatch.StartNew();
        MasterVideoComposerException? failure = null;
        try
        {
            await RealWindowsAcceptance.RunAsync(runner, "ffmpeg.exe", args, directory, TimeSpan.FromMinutes(10)).ConfigureAwait(false);
        }
        catch (MasterVideoComposerException exception)
        {
            failure = exception;
        }
        Check.True(failure is not null, "VERIFY：必须失败");
        Check.Equal(MasterVideoComposerException.ProcessContainmentFailed, failure!.Code, "VERIFY：封闭错误码");
        Check.True(!failure.CleanupIncomplete, "VERIFY：Job 终止后清理应确认完成");
        Check.Equal(1, killerCalls, "VERIFY：进程树终止被尝试且失败");
        Check.True(rootPid > 0 && childrenSeen >= 1, $"VERIFY：必须观察到真实后代 root={rootPid} children={childrenSeen}");
        Check.True(clock.ElapsedMilliseconds <= 30000, $"VERIFY：必须有界 elapsedMs={clock.ElapsedMilliseconds}");
        await AssertNoOwnedLiveAsync(rootPid, "VERIFY").ConfigureAwait(false);
        Console.WriteLine($"MASTER_MUX_FAILCLOSED_VERIFY=PASS root={rootPid} children_before_kill={childrenSeen} owned_live_after=0");
    }

    /// <summary>
    /// 所有终止动作都被抑制：运行器必须如实报告 CleanupIncomplete=true（不得虚报成功）；
    /// 之后释放 Job（KILL_ON_JOB_CLOSE）才是最终兜底，断言后代为 0。
    /// </summary>
    private static async Task SuppressedTerminationAsync(string directory)
    {
        var helper = new FixedMasterVideoProcessRunner();
        await RealWindowsAcceptance.GenerateVisualAsync(helper, directory, 640, 360).ConfigureAwait(false);
        var args = StressArguments(directory);
        var before = OwnFfmpegChildren();
        var runner = new FixedMasterVideoProcessRunner(_ => { }, ProcessContainmentFaults.SuppressTermination);
        var clock = Stopwatch.StartNew();
        var result = await RealWindowsAcceptance.RunAsync(runner, "ffmpeg.exe", args, directory, TimeSpan.FromSeconds(1.5)).ConfigureAwait(false);
        Check.True(result.TimedOut && result.ExitCode == -1, "SUPPRESS：超时语义不变");
        Check.True(result.CleanupIncomplete, "SUPPRESS：终止被抑制时必须如实报告 CleanupIncomplete=true");
        Check.True(clock.ElapsedMilliseconds <= 30000, $"SUPPRESS：必须有界 elapsedMs={clock.ElapsedMilliseconds}");

        // RunAsync 返回时 using 已释放 Job：残留的根与后代必须被 KILL_ON_JOB_CLOSE 结束。
        await Task.Delay(1000).ConfigureAwait(false);
        var leaked = OwnFfmpegChildren().Except(before).ToList();
        Check.True(leaked.Count == 0, $"SUPPRESS：释放 Job 后不得残留 [{string.Join(',', leaked)}]");
        Console.WriteLine("MASTER_MUX_FAILCLOSED_SUPPRESS_TERMINATION=PASS cleanup_incomplete_reported=True owned_live_after_dispose=0");
    }

    private static async Task AssertNoOwnedLiveAsync(int rootPid, string stage)
    {
        List<string> owned = [];
        for (var attempt = 0; attempt < 25; attempt++)
        {
            var snapshot = ProcessLineage.Snapshot();
            owned = snapshot.Values
                .Where(e => e.Pid == rootPid || ProcessLineage.IsDescendantOf(e.Pid, rootPid, snapshot))
                .Select(e => $"{e.Pid}:{e.ExeName}")
                .ToList();
            if (owned.Count == 0)
            {
                return;
            }
            await Task.Delay(200).ConfigureAwait(false);
        }
        throw new InvalidOperationException($"{stage}：仍有被测根进程的存活成员 [{string.Join(',', owned)}]");
    }
}
