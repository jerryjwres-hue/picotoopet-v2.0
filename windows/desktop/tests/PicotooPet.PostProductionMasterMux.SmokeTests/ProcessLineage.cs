using System.Diagnostics;
using System.Runtime.InteropServices;

namespace PicotooPet.PostProductionMasterMux.SmokeTests;

/// <summary>
/// 仅测试用：用 Toolhelp 快照还原“谁是谁的子进程”，把残留 ffmpeg 归因到被测命令的根进程，
/// 而不是依赖全局 GetProcessesByName 计数。日志只含 PID / 父 PID / 可执行文件名，不含参数或路径。
/// </summary>
internal static class ProcessLineage
{
    private const uint Th32csSnapProcess = 0x2;

    internal readonly record struct Entry(int Pid, int ParentPid, string ExeName);

    /// <summary>当前系统进程快照（pid → 条目）。已退出进程的子进程仍保留其 ParentPid，可据此回溯。</summary>
    public static Dictionary<int, Entry> Snapshot()
    {
        var result = new Dictionary<int, Entry>();
        var handle = CreateToolhelp32Snapshot(Th32csSnapProcess, 0);
        if (handle == IntPtr.Zero || handle == new IntPtr(-1))
        {
            return result;
        }
        try
        {
            var entry = new ProcessEntry32 { Size = (uint)Marshal.SizeOf<ProcessEntry32>() };
            for (var ok = Process32First(handle, ref entry); ok; ok = Process32Next(handle, ref entry))
            {
                result[(int)entry.ProcessId] = new Entry((int)entry.ProcessId, (int)entry.ParentProcessId, entry.ExeFile);
            }
        }
        finally
        {
            CloseHandle(handle);
        }
        return result;
    }

    /// <summary>pid 是否沿父链回溯到 rootPid（要求每一级创建时间不早于其父，以排除 PID 复用）。</summary>
    public static bool IsDescendantOf(int pid, int rootPid, IReadOnlyDictionary<int, Entry> snapshot)
    {
        var current = pid;
        for (var depth = 0; depth < 32; depth++)
        {
            if (!snapshot.TryGetValue(current, out var entry))
            {
                return false;
            }
            if (entry.ParentPid == rootPid)
            {
                return true;
            }
            current = entry.ParentPid;
        }
        return false;
    }

    public static DateTime? StartTimeUtc(Process process)
    {
        try
        {
            return process.StartTime.ToUniversalTime();
        }
        catch (Exception exception) when (exception is InvalidOperationException or System.ComponentModel.Win32Exception or NotSupportedException)
        {
            return null;
        }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ProcessEntry32
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

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Process32First(IntPtr snapshot, ref ProcessEntry32 entry);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Process32Next(IntPtr snapshot, ref ProcessEntry32 entry);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
