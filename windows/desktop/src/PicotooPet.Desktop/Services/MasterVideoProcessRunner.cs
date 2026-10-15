using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

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
    public const string ProcessContainmentFailed = "MASTER_MUX_PROCESS_CONTAINMENT_FAILED";
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

    /// <summary>
    /// 仅对 <see cref="ProcessContainmentFailed"/> 有意义：true 表示清理后仍无法确认已启动的进程树全部退出
    /// （此时调用方必须按“可能残留”处理）；false 表示已确认根进程与 Job 内全部进程都已结束，或根本没有启动进程。
    /// </summary>
    public bool CleanupIncomplete { get; init; }
}

/// <summary>测试接缝：强制进程收容建立阶段的失败，用于验证 fail-closed。生产代码使用 None。</summary>
[Flags]
public enum ProcessContainmentFaults
{
    None = 0,

    /// <summary>Job Object 创建失败（不得启动任何进程）。</summary>
    FailJobCreation = 1,

    /// <summary>系统拒绝把新进程原子加入 Job（使用无效 Job 句柄触发真实的 CreateProcess 失败；不得启动任何进程）。</summary>
    FailEnrollment = 2,

    /// <summary>进程已启动，但入 Job 校验结果被伪造为“不在 Job 中”（必须终止已启动的进程树并失败）。</summary>
    FailEnrollmentVerification = 4,

    /// <summary>所有终止动作（树终止、Job 终止、根进程终止）都不生效，用于证明 CleanupIncomplete 如实上报。</summary>
    SuppressTermination = 8,
}

/// <summary>
/// 固定进程运行器：无 shell；stdout 有界；stderr 只排空；超时与取消都会结束整个进程树。
/// 进程通过 CreateProcess + PROC_THREAD_ATTRIBUTE_JOB_LIST 在创建时原子加入 KILL_ON_JOB_CLOSE 的 Job Object，
/// 因此不存在“已启动但尚未入 Job”的窗口。无法建立收容（Job 创建/入 Job 失败、非 Windows）时 fail-closed：
/// 不启动进程，或终止已启动的进程，并以 <see cref="MasterVideoComposerException.ProcessContainmentFailed"/> 失败。
/// 终止进程树时抛出的“已知可恢复”异常不会覆盖取消/超时语义；无关异常不会被吞掉。
/// </summary>
public sealed class FixedMasterVideoProcessRunner : IMasterVideoProcessRunner
{
    public const string Ffmpeg = "ffmpeg.exe";
    public const string Ffprobe = "ffprobe.exe";
    private const int MaxStdoutBytes = 1024 * 1024;
    private static readonly TimeSpan KillGrace = TimeSpan.FromSeconds(5);

    private readonly Action<Process> _killProcessTree;
    private readonly ProcessContainmentFaults _faults;

    public FixedMasterVideoProcessRunner()
        : this(static process => process.Kill(entireProcessTree: true), ProcessContainmentFaults.None)
    {
    }

    /// <summary>测试接缝：注入进程树终止动作以模拟 Kill 失败；生产代码使用无参构造。</summary>
    public FixedMasterVideoProcessRunner(Action<Process> killProcessTree)
        : this(killProcessTree, ProcessContainmentFaults.None)
    {
    }

    /// <summary>测试接缝：同时注入进程树终止动作与收容阶段故障。</summary>
    public FixedMasterVideoProcessRunner(Action<Process> killProcessTree, ProcessContainmentFaults faults)
    {
        _killProcessTree = killProcessTree ?? throw new ArgumentNullException(nameof(killProcessTree));
        _faults = faults;
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

        // Launch 要么返回已在 Job 内的进程，要么抛出封闭错误（此时没有任何进程存活或已确认终止）。
        using var contained = ContainedProcess.Launch(startInfo, _faults);
        if (_faults.HasFlag(ProcessContainmentFaults.FailEnrollmentVerification) || !contained.IsInJob())
        {
            // 入 Job 校验失败：不能信任收容，立刻终止已启动的进程并失败，且如实报告是否确认清理完成。
            var confirmed = await TerminateAsync(contained).ConfigureAwait(false);
            throw new MasterVideoComposerException(MasterVideoComposerException.ProcessContainmentFailed)
            {
                CleanupIncomplete = !confirmed,
            };
        }

        var stdout = new MemoryStream();
        var stdoutTask = CopyBoundedAsync(contained.Stdout, stdout);
        var stderrTask = DrainAsync(contained.Stderr);
        using var timeoutSource = new CancellationTokenSource(timeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutSource.Token);
        try
        {
            await contained.WaitForExitAsync(linked.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            var terminated = await TerminateAsync(contained).ConfigureAwait(false);
            if (cancellationToken.IsCancellationRequested)
            {
                // 取消语义优先：Kill/排空的任何已知失败都不能把取消改成别的异常。
                throw;
            }
            return new MasterVideoProcessResult(-1, true, string.Empty) { CleanupIncomplete = !terminated };
        }

        // 进程已退出：退出码是权威结果。管道排空超时意味着仍有后代持有管道（输出可能不完整），
        // 如实标记 CleanupIncomplete，由调用方 fail-closed。
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
            contained.ExitCode, false, Encoding.UTF8.GetString(stdout.ToArray()))
        {
            CleanupIncomplete = !drainComplete,
        };
    }

    /// <summary>
    /// 结束整个进程树。只吞掉 .NET 文档化的“可恢复”失败（已退出、Win32、不支持、部分子进程失败）；
    /// 无论树终止是否失败，都会终止 Job（含全部后代）与根进程，并在无关异常传播前完成。
    /// 返回 false 表示在宽限期内仍无法确认根进程与 Job 内进程全部退出（不可恢复的清理限制）。
    /// </summary>
    private async Task<bool> TerminateAsync(ContainedProcess contained)
    {
        var suppress = _faults.HasFlag(ProcessContainmentFaults.SuppressTermination);
        try
        {
            try
            {
                using var process = suppress ? null : contained.TryGetProcess();
                if (process is not null && !contained.HasExited)
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
                // 拒绝访问等：交给下面的 Job / 根进程终止。
            }
            catch (NotSupportedException)
            {
                // 平台不支持进程树终止：交给下面的 Job / 根进程终止。
            }
            catch (AggregateException)
            {
                // Kill(true) 部分子进程无法终止：交给下面的 Job / 根进程终止。
            }
        }
        finally
        {
            if (!suppress)
            {
                // Job 终止不依赖进程树枚举：即使 Kill(true) 失败，根与全部后代也会被结束。
                contained.TerminateJob();
                contained.TerminateRoot();
            }
        }

        var rootExited = contained.WaitForExit(KillGrace);
        return rootExited && await contained.WaitUntilJobEmptyAsync(KillGrace).ConfigureAwait(false);
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
            // 句柄已释放。
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
            // 句柄已释放。
        }
    }
}

/// <summary>
/// 已原子加入 KILL_ON_JOB_CLOSE Job Object 的进程：由 CreateProcess（PROC_THREAD_ATTRIBUTE_JOB_LIST）创建，
/// 进程在执行第一条指令前就在 Job 内，它的任何后代都自动继承 Job，没有“启动后再加入”的竞争窗口。
/// 句柄继承被 PROC_THREAD_ATTRIBUTE_HANDLE_LIST 限定为 stdin/stdout/stderr 三个句柄。
/// 释放时先关闭 Job（结束所有残留成员）再关闭管道。
/// </summary>
internal sealed class ContainedProcess : IDisposable
{
    private const uint LimitKillOnJobClose = 0x2000;
    private const int ExtendedLimitInformationClass = 9;
    private const int BasicAccountingInformationClass = 1;
    private const uint ExtendedStartupInfoPresent = 0x00080000;
    private const uint CreateNoWindow = 0x08000000;
    private const uint StartfUseStdHandles = 0x100;
    private const uint ProcThreadAttributeHandleList = 0x00020002;
    private const uint ProcThreadAttributeJobList = 0x0002000D;
    private const int ErrorFileNotFound = 2;
    private const int ErrorPathNotFound = 3;
    private const uint WaitObject0 = 0;
    private const char Quote = (char)34;
    private const char Backslash = (char)92;

    private readonly SafeJobHandle _job;
    private readonly SafeProcessHandle _process;
    private readonly int _processId;

    private ContainedProcess(
        SafeJobHandle job,
        SafeProcessHandle process,
        int processId,
        FileStream stdout,
        FileStream stderr)
    {
        _job = job;
        _process = process;
        _processId = processId;
        Stdout = stdout;
        Stderr = stderr;
    }

    public FileStream Stdout { get; }

    public FileStream Stderr { get; }

    public bool HasExited => WaitForSingleObject(_process, 0) == WaitObject0;

    public int ExitCode => GetExitCodeProcess(_process, out var code) ? unchecked((int)code) : -1;

    /// <summary>创建 Job 并在其中原子启动进程；任何无法建立收容的情况都抛出 ProcessContainmentFailed 且不留进程。</summary>
    public static ContainedProcess Launch(ProcessStartInfo startInfo, ProcessContainmentFaults faults)
    {
        if (!OperatingSystem.IsWindows() || faults.HasFlag(ProcessContainmentFaults.FailJobCreation))
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.ProcessContainmentFailed);
        }

        var job = CreateKillOnCloseJob();
        if (job is null)
        {
            throw new MasterVideoComposerException(MasterVideoComposerException.ProcessContainmentFailed);
        }

        IntPtr stdinRead = IntPtr.Zero, stdinWrite = IntPtr.Zero;
        IntPtr stdoutRead = IntPtr.Zero, stdoutWrite = IntPtr.Zero;
        IntPtr stderrRead = IntPtr.Zero, stderrWrite = IntPtr.Zero;
        try
        {
            var security = new SecurityAttributes { Length = Marshal.SizeOf<SecurityAttributes>(), InheritHandle = true };
            if (!CreatePipe(out stdinRead, out stdinWrite, ref security, 0)
                || !CreatePipe(out stdoutRead, out stdoutWrite, ref security, 0)
                || !CreatePipe(out stderrRead, out stderrWrite, ref security, 0))
            {
                throw new MasterVideoComposerException(MasterVideoComposerException.ProcessContainmentFailed);
            }
            // stdin 的写端立即关闭：子进程读到 EOF，行为等同原先的 StandardInput.Close()。
            CloseHandle(stdinWrite);
            stdinWrite = IntPtr.Zero;

            var processHandle = StartInJob(startInfo, job, faults, stdinRead, stdoutWrite, stderrWrite, out var processId);

            // 子进程端句柄已被继承；父进程必须关闭自己的副本，管道读端才能在子进程树退出后得到 EOF。
            CloseHandle(stdinRead);
            stdinRead = IntPtr.Zero;
            CloseHandle(stdoutWrite);
            stdoutWrite = IntPtr.Zero;
            CloseHandle(stderrWrite);
            stderrWrite = IntPtr.Zero;

            var stdout = new FileStream(new SafeFileHandle(stdoutRead, ownsHandle: true), FileAccess.Read, 1, false);
            stdoutRead = IntPtr.Zero;
            var stderr = new FileStream(new SafeFileHandle(stderrRead, ownsHandle: true), FileAccess.Read, 1, false);
            stderrRead = IntPtr.Zero;
            return new ContainedProcess(job, processHandle, processId, stdout, stderr);
        }
        catch
        {
            // 关闭 Job 会结束其中已启动的任何进程（KILL_ON_JOB_CLOSE），因此失败路径不会留下进程。
            job.Dispose();
            throw;
        }
        finally
        {
            foreach (var handle in new[] { stdinRead, stdinWrite, stdoutRead, stdoutWrite, stderrRead, stderrWrite })
            {
                if (handle != IntPtr.Zero)
                {
                    CloseHandle(handle);
                }
            }
        }
    }

    /// <summary>仅在需要时（树终止的测试接缝 / 默认 Kill(true)）才按 PID 打开 Process 对象；进程已消失返回 null。</summary>
    public Process? TryGetProcess()
    {
        try
        {
            return Process.GetProcessById(_processId);
        }
        catch (ArgumentException)
        {
            return null;
        }
        catch (InvalidOperationException)
        {
            return null;
        }
        catch (Win32Exception)
        {
            return null;
        }
    }

    public Task WaitForExitAsync(CancellationToken cancellationToken)
    {
        return WaitCoreAsync(cancellationToken);
    }

    public bool WaitForExit(TimeSpan timeout)
    {
        return WaitForSingleObject(_process, (uint)Math.Min(timeout.TotalMilliseconds, int.MaxValue - 1)) == WaitObject0;
    }

    public void TerminateJob()
    {
        TerminateJobObject(_job, 1);
    }

    public void TerminateRoot()
    {
        TerminateProcess(_process, 1);
    }

    /// <summary>等待 Job 中没有存活进程；超时返回 false。</summary>
    public async Task<bool> WaitUntilJobEmptyAsync(TimeSpan timeout)
    {
        var deadline = Stopwatch.StartNew();
        while (true)
        {
            if (ActiveProcesses() == 0)
            {
                return true;
            }
            if (deadline.Elapsed >= timeout)
            {
                return false;
            }
            await Task.Delay(25).ConfigureAwait(false);
        }
    }

    public void Dispose()
    {
        // 先关闭 Job（KILL_ON_JOB_CLOSE 结束全部残留成员，管道写端随之关闭），再关闭管道与进程句柄。
        _job.Dispose();
        Stdout.Dispose();
        Stderr.Dispose();
        _process.Dispose();
    }

    private async Task WaitCoreAsync(CancellationToken cancellationToken)
    {
        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var waitHandle = new ManualResetEvent(false);
        waitHandle.SafeWaitHandle = new SafeWaitHandle(_process.DangerousGetHandle(), ownsHandle: false);
        var registered = ThreadPool.RegisterWaitForSingleObject(
            waitHandle, static (state, _) => ((TaskCompletionSource)state!).TrySetResult(), completion, Timeout.Infinite, true);
        try
        {
            using (cancellationToken.Register(static state => ((TaskCompletionSource)state!).TrySetCanceled(), completion))
            {
                await completion.Task.ConfigureAwait(false);
            }
        }
        catch (TaskCanceledException)
        {
            throw new OperationCanceledException(cancellationToken);
        }
        finally
        {
            registered.Unregister(null);
        }
    }

    public bool IsInJob()
    {
        return IsProcessInJob(_process, _job, out var inJob) && inJob;
    }

    private uint ActiveProcesses()
    {
        var size = Marshal.SizeOf<BasicAccounting>();
        var buffer = Marshal.AllocHGlobal(size);
        try
        {
            if (!QueryInformationJobObject(_job, BasicAccountingInformationClass, buffer, (uint)size, IntPtr.Zero))
            {
                return uint.MaxValue;
            }
            return Marshal.PtrToStructure<BasicAccounting>(buffer).ActiveProcesses;
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    private static SafeJobHandle? CreateKillOnCloseJob()
    {
        var handle = CreateJobObject(IntPtr.Zero, null);
        if (handle.IsInvalid)
        {
            handle.Dispose();
            return null;
        }
        var info = new ExtendedLimitInformation();
        info.Basic.LimitFlags = LimitKillOnJobClose;
        var size = Marshal.SizeOf<ExtendedLimitInformation>();
        var buffer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(info, buffer, false);
            if (!SetInformationJobObject(handle, ExtendedLimitInformationClass, buffer, (uint)size))
            {
                handle.Dispose();
                return null;
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
        return handle;
    }

    private static SafeProcessHandle StartInJob(
        ProcessStartInfo startInfo,
        SafeJobHandle job,
        ProcessContainmentFaults faults,
        IntPtr stdin,
        IntPtr stdout,
        IntPtr stderr,
        out int processId)
    {
        // FailEnrollment：把一个绝不可能有效的句柄值放进 JOB_LIST，让系统真实地拒绝 CreateProcess。
        var jobValue = faults.HasFlag(ProcessContainmentFaults.FailEnrollment)
            ? new IntPtr(0x0BADF00D)
            : job.DangerousGetHandle();

        var attributeSize = IntPtr.Zero;
        InitializeProcThreadAttributeList(IntPtr.Zero, 2, 0, ref attributeSize);
        var attributeList = Marshal.AllocHGlobal(attributeSize);
        var jobBuffer = Marshal.AllocHGlobal(IntPtr.Size);
        var inheritBuffer = Marshal.AllocHGlobal(IntPtr.Size * 3);
        var attributesInitialized = false;
        try
        {
            if (!InitializeProcThreadAttributeList(attributeList, 2, 0, ref attributeSize))
            {
                throw new MasterVideoComposerException(MasterVideoComposerException.ProcessContainmentFailed);
            }
            attributesInitialized = true;

            Marshal.WriteIntPtr(jobBuffer, jobValue);
            if (!UpdateProcThreadAttribute(attributeList, 0, new IntPtr(ProcThreadAttributeJobList), jobBuffer, new IntPtr(IntPtr.Size), IntPtr.Zero, IntPtr.Zero))
            {
                throw new MasterVideoComposerException(MasterVideoComposerException.ProcessContainmentFailed);
            }
            Marshal.WriteIntPtr(inheritBuffer, 0, stdin);
            Marshal.WriteIntPtr(inheritBuffer, IntPtr.Size, stdout);
            Marshal.WriteIntPtr(inheritBuffer, IntPtr.Size * 2, stderr);
            if (!UpdateProcThreadAttribute(attributeList, 0, new IntPtr(ProcThreadAttributeHandleList), inheritBuffer, new IntPtr(IntPtr.Size * 3), IntPtr.Zero, IntPtr.Zero))
            {
                throw new MasterVideoComposerException(MasterVideoComposerException.ProcessContainmentFailed);
            }

            var info = new StartupInfoEx
            {
                StartupInfo = new StartupInfo
                {
                    Size = (uint)Marshal.SizeOf<StartupInfoEx>(),
                    Flags = StartfUseStdHandles,
                    StdInput = stdin,
                    StdOutput = stdout,
                    StdError = stderr,
                },
                AttributeList = attributeList,
            };
            var commandLine = BuildCommandLine(startInfo);
            var workingDirectory = string.IsNullOrEmpty(startInfo.WorkingDirectory) ? null : startInfo.WorkingDirectory;
            if (!CreateProcess(
                    null, commandLine, IntPtr.Zero, IntPtr.Zero, true,
                    ExtendedStartupInfoPresent | CreateNoWindow, IntPtr.Zero, workingDirectory, ref info, out var created))
            {
                var error = Marshal.GetLastWin32Error();
                throw new MasterVideoComposerException(
                    error is ErrorFileNotFound or ErrorPathNotFound
                        ? MasterVideoComposerException.FfmpegUnavailable
                        : MasterVideoComposerException.ProcessContainmentFailed);
            }
            CloseHandle(created.Thread);
            processId = (int)created.ProcessId;
            return new SafeProcessHandle(created.Process, ownsHandle: true);
        }
        finally
        {
            if (attributesInitialized)
            {
                DeleteProcThreadAttributeList(attributeList);
            }
            Marshal.FreeHGlobal(attributeList);
            Marshal.FreeHGlobal(jobBuffer);
            Marshal.FreeHGlobal(inheritBuffer);
        }
    }

    /// <summary>按 CommandLineToArgvW 规则拼接命令行；FileName 是已校验的固定可执行文件名。</summary>
    private static StringBuilder BuildCommandLine(ProcessStartInfo startInfo)
    {
        var builder = new StringBuilder(startInfo.FileName);
        foreach (var argument in startInfo.ArgumentList)
        {
            builder.Append(' ');
            AppendArgument(builder, argument);
        }
        return builder;
    }

    private static void AppendArgument(StringBuilder builder, string argument)
    {
        if (argument.Length > 0 && !argument.Any(char.IsWhiteSpace) && argument.IndexOf(Quote) < 0)
        {
            builder.Append(argument);
            return;
        }
        builder.Append(Quote);
        var backslashes = 0;
        foreach (var character in argument)
        {
            if (character == Backslash)
            {
                backslashes++;
            }
            else if (character == Quote)
            {
                builder.Append(Backslash, (backslashes * 2) + 1);
                builder.Append(Quote);
                backslashes = 0;
            }
            else
            {
                builder.Append(Backslash, backslashes);
                backslashes = 0;
                builder.Append(character);
            }
        }
        builder.Append(Backslash, backslashes * 2);
        builder.Append(Quote);
    }

    private sealed class SafeJobHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        public SafeJobHandle()
            : base(ownsHandle: true)
        {
        }

        protected override bool ReleaseHandle() => CloseHandle(handle);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes
    {
        public int Length;
        public IntPtr SecurityDescriptor;
        [MarshalAs(UnmanagedType.Bool)]
        public bool InheritHandle;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfo
    {
        public uint Size;
        public IntPtr Reserved;
        public IntPtr Desktop;
        public IntPtr Title;
        public uint X;
        public uint Y;
        public uint XSize;
        public uint YSize;
        public uint XCountChars;
        public uint YCountChars;
        public uint FillAttribute;
        public uint Flags;
        public ushort ShowWindow;
        public ushort Reserved2;
        public IntPtr Reserved2Pointer;
        public IntPtr StdInput;
        public IntPtr StdOutput;
        public IntPtr StdError;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfoEx
    {
        public StartupInfo StartupInfo;
        public IntPtr AttributeList;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInformation
    {
        public IntPtr Process;
        public IntPtr Thread;
        public uint ProcessId;
        public uint ThreadId;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimit
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimitInformation
    {
        public BasicLimit Basic;
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BasicAccounting
    {
        public long TotalUserTime;
        public long TotalKernelTime;
        public long ThisPeriodTotalUserTime;
        public long ThisPeriodTotalKernelTime;
        public uint TotalPageFaultCount;
        public uint TotalProcesses;
        public uint ActiveProcesses;
        public uint TotalTerminatedProcesses;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeJobHandle CreateJobObject(IntPtr attributes, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(SafeJobHandle job, int informationClass, IntPtr information, uint length);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryInformationJobObject(SafeJobHandle job, int informationClass, IntPtr information, uint length, IntPtr returnLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateJobObject(SafeJobHandle job, uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsProcessInJob(SafeProcessHandle process, SafeJobHandle job, [MarshalAs(UnmanagedType.Bool)] out bool result);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcess(SafeProcessHandle process, uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(SafeProcessHandle handle, uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(SafeProcessHandle process, out uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreatePipe(out IntPtr readPipe, out IntPtr writePipe, ref SecurityAttributes attributes, uint size);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool InitializeProcThreadAttributeList(IntPtr attributeList, int attributeCount, int flags, ref IntPtr size);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UpdateProcThreadAttribute(
        IntPtr attributeList, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previousValue, IntPtr returnSize);

    [DllImport("kernel32.dll")]
    private static extern void DeleteProcThreadAttributeList(IntPtr attributeList);

    [DllImport("kernel32.dll", EntryPoint = "CreateProcessW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcess(
        string? applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string? currentDirectory,
        ref StartupInfoEx startupInfo,
        out ProcessInformation processInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
