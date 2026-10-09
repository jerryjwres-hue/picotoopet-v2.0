using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

public sealed record TextOverlayProcessResult(int ExitCode, bool TimedOut, string Stdout);

public interface ITextOverlayProcessRunner
{
    Task<TextOverlayProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken);
}

/// <summary>固定 ffmpeg.exe / ffprobe.exe 进程边界：无 shell、有界 stdout、超时与取消杀死整个进程树。</summary>
public sealed class TextOverlayProcessRunner : ITextOverlayProcessRunner
{
    public const string Ffmpeg = "ffmpeg.exe";
    public const string Ffprobe = "ffprobe.exe";
    private const int MaxStdoutBytes = 256 * 1024;
    private static readonly TimeSpan KillGrace = TimeSpan.FromSeconds(5);

    public async Task<TextOverlayProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(startInfo);
        if (startInfo.UseShellExecute
            || !(string.Equals(startInfo.FileName, Ffmpeg, StringComparison.OrdinalIgnoreCase)
                || string.Equals(startInfo.FileName, Ffprobe, StringComparison.OrdinalIgnoreCase)))
        {
            throw new TextOverlayException(TextOverlayException.FfmpegUnavailable);
        }

        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
            {
                throw new TextOverlayException(TextOverlayException.FfmpegUnavailable);
            }
        }
        catch (Win32Exception exception)
        {
            throw new TextOverlayException(TextOverlayException.FfmpegUnavailable, exception);
        }

        var stdout = new MemoryStream();
        var stdoutTask = CopyBoundedAsync(process.StandardOutput.BaseStream, stdout);
        var stderrTask = DrainAsync(process.StandardError.BaseStream);
        using var timeoutSource = new CancellationTokenSource(timeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            timeoutSource.Token);
        try
        {
            await process.WaitForExitAsync(linked.Token).ConfigureAwait(false);
            await Task.WhenAll(stdoutTask, stderrTask)
                .WaitAsync(KillGrace, cancellationToken).ConfigureAwait(false);
            return new TextOverlayProcessResult(
                process.ExitCode,
                false,
                Encoding.UTF8.GetString(stdout.ToArray()));
        }
        catch (OperationCanceledException)
        {
            Kill(process);
            if (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            return new TextOverlayProcessResult(-1, true, string.Empty);
        }
        catch (TimeoutException)
        {
            Kill(process);
            return new TextOverlayProcessResult(-1, true, string.Empty);
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
            // stderr 只被排空；永不进入日志、异常或清单。
        }
    }
}
