using System.ComponentModel;
using System.Diagnostics;
using System.Text;

namespace PicotooPet.Desktop.Services;

public sealed record MasterVideoProcessResult(int ExitCode, bool TimedOut, string Stdout);

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
/// </summary>
public sealed class FixedMasterVideoProcessRunner : IMasterVideoProcessRunner
{
    public const string Ffmpeg = "ffmpeg.exe";
    public const string Ffprobe = "ffprobe.exe";
    private const int MaxStdoutBytes = 1024 * 1024;
    private static readonly TimeSpan KillGrace = TimeSpan.FromSeconds(5);

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
            await Task.WhenAll(stdoutTask, stderrTask).WaitAsync(KillGrace, cancellationToken).ConfigureAwait(false);
            return new MasterVideoProcessResult(
                process.ExitCode, false, Encoding.UTF8.GetString(stdout.ToArray()));
        }
        catch (OperationCanceledException)
        {
            Kill(process);
            if (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            return new MasterVideoProcessResult(-1, true, string.Empty);
        }
        catch (TimeoutException)
        {
            Kill(process);
            return new MasterVideoProcessResult(-1, true, string.Empty);
        }
    }

    private static void Kill(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
            process.WaitForExit(KillGrace);
        }
        catch (InvalidOperationException)
        {
            // 进程已结束。
        }
        catch (Win32Exception)
        {
            // 无法终止时由调用方的有界超时兜底。
        }
    }

    private static async Task CopyBoundedAsync(Stream source, MemoryStream target)
    {
        var buffer = new byte[16 * 1024];
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

    private static async Task DrainAsync(Stream source)
    {
        var buffer = new byte[16 * 1024];
        while (await source.ReadAsync(buffer).ConfigureAwait(false) > 0)
        {
            // stderr 只被排空；永不进入异常、日志、UI 或清单。
        }
    }
}
