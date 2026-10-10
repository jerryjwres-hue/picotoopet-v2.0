using System.ComponentModel;
using System.Diagnostics;
using System.Text;

namespace PicotooPet.Desktop.Services;

public sealed record MasterVideoProcessResult(int ExitCode, bool TimedOut, string Stdout)
{
    /// <summary>
    /// 超时/取消后无法确认进程已终止，或退出后管道排空超时。结果语义（超时/取消/退出码）不受影响；
    /// 这只是对不可恢复的清理限制的诚实标记（例如进程被 EDR 保护、句柄被子进程继承）。
    /// </summary>
    public bool CleanupIncomplete { get; init; }
}

/// <summary>C009B 进程边界：只执行固定的 ffmpeg.exe / ffprobe.exe。</summary>
public interface IMasterVideoProcessRunner
{
    Task<MasterVideoProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken);
}

/// <summary>C009B 内部有界错误；Message 永远是封闭码，不含 stderr、路径或文案。</summary>
public sealed class MasterVideoComposerException : Exception
{
    public const string FfmpegUnavailable = "MASTER_MUX_FFMPEG_UNAVAILABLE";
    public const string FfmpegFailed = "MASTER_MUX_FFMPEG_FAILED";
    public const string FfmpegTimeout = "MASTER_MUX_FFMPEG_TIMEOUT";
    public const string RequestInvalid = "MASTER_MUX_REQUEST_INVALID";
    public const string PathInvalid = "MASTER_MUX_PATH_INVALID";
    public const string VisualInvalid = "MASTER_MUX_VISUAL_INVALID";
    public const string NarrationInvalid = "MASTER_MUX_NARRATION_INVALID";
    public const string SegmentTooLong = "MASTER_MUX_SEGMENT_TOO_LONG";
    public const string ProbeInvalid = "MASTER_MUX_PROBE_INVALID";
    public const string OutputInvalid = "MASTER_MUX_OUTPUT_INVALID";

    public MasterVideoComposerException(string code, Exception? innerException = null)
        : base(code, innerException)
    {
        Code = code;
    }

    public string Code { get; }
}

/// <summary>
/// 固定进程运行器：无 shell；stdout 有界；stderr 只排空；超时与取消都会结束整个进程树。
/// 终止进程树时抛出的“已知可恢复”异常不会覆盖取消/超时语义；无关异常不会被吞掉。
/// </summary>
public sealed class FixedMasterVideoProcessRunner : IMasterVideoProcessRunner
{
    public const string Ffmpeg = "ffmpeg.exe";
    public const string Ffprobe = "ffprobe.exe";
    private const int MaxStdoutBytes = 1024 * 1024;
    private static readonly TimeSpan KillGrace = TimeSpan.FromSeconds(5);

    private readonly Action<Process> _killProcessTree;

    public FixedMasterVideoProcessRunner()
        : this(static process => process.Kill(entireProcessTree: true))
    {
    }

    /// <summary>测试接缝：注入进程树终止动作以模拟 Kill 失败；生产代码使用无参构造。</summary>
    public FixedMasterVideoProcessRunner(Action<Process> killProcessTree)
    {
        _killProcessTree = killProcessTree ?? throw new ArgumentNullException(nameof(killProcessTree));
    }

    public async Task<MasterVideoProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(startInfo);
        if (startInfo.UseShellExecute
            || !(string.Equals(startInfo.FileName, Ffmpeg, StringComparison.OrdinalIgnoreCase)
                || string.Equals(startInfo.FileName, Ffprobe, StringComparison.OrdinalIgnoreCase)))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.FfmpegUnavailable);
        }
        startInfo.RedirectStandardOutput = true;
        startInfo.RedirectStandardError = true;
        startInfo.RedirectStandardInput = true;
        startInfo.CreateNoWindow = true;

        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
            {
                throw new MasterVideoComposerException(MasterVideoComposerException.FfmpegUnavailable);
            }
        }
        catch (Win32Exception exception)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.FfmpegUnavailable, exception);
        }
        process.StandardInput.Close();

        var stdout = new MemoryStream();
        var stdoutTask = CopyBoundedAsync(process.StandardOutput.BaseStream, stdout);
        var stderrTask = DrainAsync(process.StandardError.BaseStream);
        using var timeoutSource = new CancellationTokenSource(timeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutSource.Token);
        try
        {
            await process.WaitForExitAsync(linked.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            var terminated = Terminate(process);
            if (cancellationToken.IsCancellationRequested)
            {
                // 取消语义优先：Kill/排空的任何已知失败都不能把取消改成别的异常。
                throw;
            }
            return new MasterVideoProcessResult(-1, true, string.Empty) { CleanupIncomplete = !terminated };
        }

        // 进程已退出：退出码是权威结果。管道排空超时只意味着输出可能不完整（由调用方的解析/校验兜底），
        // 不能被误报成 mux 超时。
        var drainComplete = true;
        try
        {
            await Task.WhenAll(stdoutTask, stderrTask).WaitAsync(KillGrace, cancellationToken).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            drainComplete = false;
        }
        // 取消发生在排空期间：OperationCanceledException 直接传播（进程已退出）。
        return new MasterVideoProcessResult(
            process.ExitCode, false, Encoding.UTF8.GetString(stdout.ToArray()))
        {
            CleanupIncomplete = !drainComplete,
        };
    }

    /// <summary>
    /// 结束整个进程树。只吞掉 .NET 文档化的“可恢复”失败（已退出、Win32、不支持、部分子进程失败）；
    /// 无论树终止是否失败，都会兜底终止主进程，并在无关异常传播前完成兜底。
    /// 返回 false 表示在宽限期内仍无法确认退出（不可恢复的清理限制）。
    /// </summary>
    private bool Terminate(Process process)
    {
        try
        {
            try
            {
                if (!process.HasExited)
                {
                    _killProcessTree(process);
                }
            }
            catch (InvalidOperationException)
            {
                // 进程已退出。
            }
            catch (Win32Exception)
            {
                // 拒绝访问等：交给下面的单进程兜底。
            }
            catch (NotSupportedException)
            {
                // 平台不支持进程树终止：交给下面的单进程兜底。
            }
            catch (AggregateException)
            {
                // Kill(true) 部分子进程无法终止：交给下面的单进程兜底。
            }
        }
        finally
        {
            try
            {
                if (!process.HasExited)
                {
                    process.Kill();
                }
            }
            catch (InvalidOperationException)
            {
                // 进程已退出。
            }
            catch (Win32Exception)
            {
                // 无法终止：由下面的有界等待如实报告。
            }
        }

        try
        {
            // 同步等待有 KillGrace 上限；返回值如实反映是否确认退出。
            return process.WaitForExit(KillGrace);
        }
        catch (InvalidOperationException)
        {
            return true;
        }
    }

    // 进程被终止或 Process 被释放时管道会被拆除；这属于预期的 IO 结束，不能变成未观察到的任务异常。
    private static async Task CopyBoundedAsync(Stream source, MemoryStream target)
    {
        var buffer = new byte[16 * 1024];
        try
        {
            while (true)
            {
                var read = await source.ReadAsync(buffer).ConfigureAwait(false);
                if (read == 0)
                {
                    return;
                }
                if (target.Length + read <= MaxStdoutBytes)
                {
                    target.Write(buffer, 0, read);
                }
            }
        }
        catch (IOException)
        {
            // 管道已被拆除。
        }
        catch (ObjectDisposedException)
        {
            // Process 已释放。
        }
    }

    private static async Task DrainAsync(Stream source)
    {
        var buffer = new byte[16 * 1024];
        try
        {
            while (await source.ReadAsync(buffer).ConfigureAwait(false) > 0)
            {
                // stderr 只被排空；永不进入异常、日志、UI 或清单。
            }
        }
        catch (IOException)
        {
            // 管道已被拆除。
        }
        catch (ObjectDisposedException)
        {
            // Process 已释放。
        }
    }
}
