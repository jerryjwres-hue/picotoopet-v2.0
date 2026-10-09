using System.ComponentModel;
using System.Diagnostics;

namespace PicotooPet.PostProductionAudioMuxProbe;

internal sealed record ProcessOutcome(
    int ExitCode,
    bool TimedOut,
    bool Cancelled,
    bool Unresponsive,
    bool StartFailed,
    byte[] Stdout);

/// <summary>
/// Runs only the fixed executables ffmpeg.exe / ffprobe.exe with an ArgumentList (no shell, no caller
/// arguments). Output is size-bounded; timeout and cancellation kill the whole process tree.
/// </summary>
internal static class FfmpegRunner
{
    public const string Ffmpeg = "ffmpeg.exe";
    public const string Ffprobe = "ffprobe.exe";
    private const int MaxStdoutBytes = 64 * 1024 * 1024;
    private static readonly TimeSpan KillGrace = TimeSpan.FromSeconds(5);

    public static async Task<ProcessOutcome> RunAsync(
        string executable,
        IEnumerable<string> arguments,
        string workingDirectory,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        if (executable is not (Ffmpeg or Ffprobe))
        {
            throw new InvalidOperationException("EXECUTABLE_POLICY_DENIED");
        }
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
        };
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
            {
                return new ProcessOutcome(-1, false, false, false, true, []);
            }
        }
        catch (Win32Exception)
        {
            return new ProcessOutcome(-1, false, false, false, true, []);
        }
        process.StandardInput.Close();

        using var timeoutSource = new CancellationTokenSource(timeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutSource.Token);
        var stdout = new MemoryStream();
        var stdoutTask = CopyBoundedAsync(process.StandardOutput.BaseStream, stdout);
        var stderrTask = DrainAsync(process.StandardError.BaseStream);
        try
        {
            await process.WaitForExitAsync(linked.Token).ConfigureAwait(false);
            await Task.WhenAll(stdoutTask, stderrTask).WaitAsync(KillGrace).ConfigureAwait(false);
            return new ProcessOutcome(process.ExitCode, false, false, false, false, stdout.ToArray());
        }
        catch (OperationCanceledException)
        {
            var timedOut = timeoutSource.IsCancellationRequested && !cancellationToken.IsCancellationRequested;
            var stopped = Kill(process);
            return new ProcessOutcome(-1, timedOut, !timedOut, !stopped, false, []);
        }
        catch (TimeoutException)
        {
            Kill(process);
            return new ProcessOutcome(-1, false, false, true, false, []);
        }
    }

    private static bool Kill(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
            return process.WaitForExit(KillGrace);
        }
        catch (InvalidOperationException)
        {
            return true; // already gone
        }
        catch (Win32Exception)
        {
            return false;
        }
    }

    private static async Task CopyBoundedAsync(Stream source, MemoryStream target)
    {
        var buffer = new byte[256 * 1024];
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
            // stderr is drained and discarded; it never enters reports or logs.
        }
    }
}
