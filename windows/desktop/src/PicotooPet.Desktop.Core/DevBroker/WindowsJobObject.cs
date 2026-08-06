using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace PicotooPet.Desktop.Core.DevBroker;

/// <summary>使用 KILL_ON_JOB_CLOSE 约束 Mock Broker 完整进程树。</summary>
[SupportedOSPlatform("windows")]
public sealed class WindowsJobObject : IDisposable
{
    private const int ExtendedLimitInformationClass = 9;
    private const uint JobObjectLimitKillOnJobClose  = 0x00002000;

    private nint _handle;

    /// <summary>创建并配置一个关闭即终止全部进程的 Job Object。</summary>
    public WindowsJobObject()
    {
        _handle = CreateJobObject(nint.Zero, null);
        if (_handle == nint.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        var information = new JobObjectExtendedLimitInformation
        {
            BasicLimitInformation = new JobObjectBasicLimitInformation
            {
                LimitFlags = JobObjectLimitKillOnJobClose,
            },
        };
        var size   = Marshal.SizeOf<JobObjectExtendedLimitInformation>();
        var buffer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(information, buffer, fDeleteOld: false);
            if (!SetInformationJobObject(
                    _handle,
                    ExtendedLimitInformationClass,
                    buffer,
                    checked((uint)size)))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
        }
        catch
        {
            Dispose();
            throw;
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    /// <summary>把已启动进程绑定到当前 Job Object。</summary>
    public void Assign(Process process)
    {
        ArgumentNullException.ThrowIfNull(process);
        ObjectDisposedException.ThrowIf(_handle == nint.Zero, this);
        if (!AssignProcessToJobObject(_handle, process.Handle))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    /// <summary>关闭 Job Object；系统同步终止其中尚未退出的完整进程树。</summary>
    public void Dispose()
    {
        var handle = Interlocked.Exchange(ref _handle, nint.Zero);
        if (handle != nint.Zero)
        {
            _ = CloseHandle(handle);
        }
        GC.SuppressFinalize(this);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        internal ulong ReadOperationCount;
        internal ulong WriteOperationCount;
        internal ulong OtherOperationCount;
        internal ulong ReadTransferCount;
        internal ulong WriteTransferCount;
        internal ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectBasicLimitInformation
    {
        internal long PerProcessUserTimeLimit;
        internal long PerJobUserTimeLimit;
        internal uint LimitFlags;
        internal nuint MinimumWorkingSetSize;
        internal nuint MaximumWorkingSetSize;
        internal uint ActiveProcessLimit;
        internal nuint Affinity;
        internal uint PriorityClass;
        internal uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectExtendedLimitInformation
    {
        internal JobObjectBasicLimitInformation BasicLimitInformation;
        internal IoCounters IoInfo;
        internal nuint ProcessMemoryLimit;
        internal nuint JobMemoryLimit;
        internal nuint PeakProcessMemoryUsed;
        internal nuint PeakJobMemoryUsed;
    }

#pragma warning disable SYSLIB1054 // Job Object 封装避免为整个核心项目开启 unsafe。
    [DllImport(
        "kernel32.dll",
        EntryPoint = "CreateJobObjectW",
        SetLastError = true,
        CharSet = CharSet.Unicode)]
    private static extern nint CreateJobObject(nint jobAttributes, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(
        nint job,
        int informationClass,
        nint information,
        uint informationLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(nint job, nint process);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(nint handle);
#pragma warning restore SYSLIB1054
}
