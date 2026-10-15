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
        // 在子进程能够长期运行之前把它（及已出现的后代）放进 Job Object；Job 关闭即结束全部成员。
        using var job = WindowsProcessJob.TryCreate();
        job?.Adopt(process);

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
            var terminated = await TerminateAsync(process, job).ConfigureAwait(false);
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
    private async Task<bool> TerminateAsync(Process process, WindowsProcessJob? job)
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
            // Job 终止不依赖进程树枚举：即使 Kill(true) 失败，根与所有已加入的后代也会被结束。
            job?.Terminate();
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
            var rootExited = process.WaitForExit(KillGrace);
            return rootExited && (job is null || await job.WaitUntilEmptyAsync(KillGrace).ConfigureAwait(false));
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

/// <summary>
/// Windows Job Object 保护：JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE。被测进程启动后立即加入 Job，并扫描已出现的后代
/// 一并加入；之后新产生的后代自动继承 Job。终止/释放 Job 会结束全部成员，不依赖 Process.Kill(entireProcessTree)。
/// 已知局限：Process.Start 不支持 CREATE_SUSPENDED，根进程在加入 Job 前的极短窗口内产生的后代只能靠随后的扫描补救。
/// 创建/加入失败（旧系统、受限的外层 Job 禁止嵌套）时返回 null / 不加入，行为退化为原有进程树终止，不抛异常。
/// </summary>
internal sealed class WindowsProcessJob : IDisposable
{
    private const uint LimitKillOnJobClose = 0x2000;
    private const int ExtendedLimitInformationClass = 9;
    private const int BasicAccountingInformationClass = 1;
    private const uint ProcessSetQuotaAndTerminate = 0x0100 | 0x0001;
    private const uint Th32csSnapProcess = 0x2;

    private readonly SafeJobHandle _job;

    private WindowsProcessJob(SafeJobHandle job)
    {
        _job = job;
    }

    public static WindowsProcessJob? TryCreate()
    {
        if (!OperatingSystem.IsWindows())
        {
            return null;
        }
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
        return new WindowsProcessJob(handle);
    }

    /// <summary>加入根进程，并把已经出现的后代（根在加入前来得及产生的）也加入。返回根是否成功加入。</summary>
    public bool Adopt(Process root)
    {
        try
        {
            if (!AssignProcessToJobObject(_job, root.SafeHandle))
            {
                return false;
            }
        }
        catch (InvalidOperationException)
        {
            return false;
        }
        for (var pass = 0; pass < 3; pass++)
        {
            if (AdoptDescendants(root.Id) == 0)
            {
                break;
            }
        }
        return true;
    }

    public void Terminate()
    {
        TerminateJobObject(_job, 1);
    }

    /// <summary>等待 Job 中没有存活进程；超时返回 false。</summary>
    public async Task<bool> WaitUntilEmptyAsync(TimeSpan timeout)
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
        _job.Dispose();
    }

    private uint ActiveProcesses()
    {
        var size = Marshal.SizeOf<BasicAccounting>();
        var buffer = Marshal.AllocHGlobal(size);
        try
        {
            if (!QueryInformationJobObject(_job, BasicAccountingInformationClass, buffer, (uint)size, IntPtr.Zero))
            {
                return 0;
            }
            return Marshal.PtrToStructure<BasicAccounting>(buffer).ActiveProcesses;
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    /// <summary>快照父子关系，把 rootPid 的所有后代加入 Job，返回新加入的数量。</summary>
    private int AdoptDescendants(int rootPid)
    {
        var parents = new Dictionary<int, int>();
        var snapshot = CreateToolhelp32Snapshot(Th32csSnapProcess, 0);
        if (snapshot == IntPtr.Zero || snapshot == new IntPtr(-1))
        {
            return 0;
        }
        try
        {
            var entry = new ProcessEntry { Size = (uint)Marshal.SizeOf<ProcessEntry>() };
            for (var ok = Process32First(snapshot, ref entry); ok; ok = Process32Next(snapshot, ref entry))
            {
                parents[(int)entry.ProcessId] = (int)entry.ParentProcessId;
            }
        }
        finally
        {
            CloseHandle(snapshot);
        }

        var adopted = 0;
        foreach (var pid in parents.Keys)
        {
            if (pid == rootPid || !DescendsFrom(pid, rootPid, parents))
            {
                continue;
            }
            var handle = OpenProcess(ProcessSetQuotaAndTerminate, false, (uint)pid);
            if (handle == IntPtr.Zero)
            {
                continue;
            }
            try
            {
                if (IsProcessInJob(handle, _job.DangerousGetHandle(), out var inJob) && inJob)
                {
                    continue;
                }
                if (AssignProcessToJobObject(_job, new SafeProcessHandle(handle, ownsHandle: false)))
                {
                    adopted++;
                }
            }
            finally
            {
                CloseHandle(handle);
            }
        }
        return adopted;
    }

    private static bool DescendsFrom(int pid, int rootPid, Dictionary<int, int> parents)
    {
        var current = pid;
        for (var depth = 0; depth < 32; depth++)
        {
            if (!parents.TryGetValue(current, out var parent))
            {
                return false;
            }
            if (parent == rootPid)
            {
                return true;
            }
            current = parent;
        }
        return false;
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

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ProcessEntry
    {
        public uint Size;
        public uint Usage;
        public uint ProcessId;
        public UIntPtr DefaultHeapId;
        public uint ModuleId;
        public uint Threads;
        public uint ParentProcessId;
        public int PriorityClassBase;
        public uint Flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string ExeFile;
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
    private static extern bool AssignProcessToJobObject(SafeJobHandle job, SafeProcessHandle process);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateJobObject(SafeJobHandle job, uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsProcessInJob(IntPtr process, IntPtr job, [MarshalAs(UnmanagedType.Bool)] out bool result);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, [MarshalAs(UnmanagedType.Bool)] bool inheritHandle, uint processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Process32First(IntPtr snapshot, ref ProcessEntry entry);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Process32Next(IntPtr snapshot, ref ProcessEntry entry);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
