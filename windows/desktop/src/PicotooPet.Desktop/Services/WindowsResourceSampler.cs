using System.IO;
using System.Runtime.InteropServices;

namespace PicotooPet.Desktop.Services;

/// <summary>Windows 本地只读资源快照；null 表示本次采样不可用，界面不得伪造数值。</summary>
public sealed record WindowsResourceSnapshot(
    double? CpuPercent,
    double? MemoryPercent,
    double? DiskPercent,
    DateTimeOffset SampledAt)
{
    /// <summary>将原始百分比限制在 UI 合法范围。</summary>
    public static double? Normalize(double? value) =>
        value is null || double.IsNaN(value.Value) || double.IsInfinity(value.Value)
            ? null
            : Math.Clamp(value.Value, 0d, 100d);
}

/// <summary>使用 Windows 原生只读 API 采样 CPU / 内存，并使用 DriveInfo 读取系统盘占用。</summary>
public sealed class WindowsResourceSampler
{
    private ulong? _previousIdle;
    private ulong? _previousKernel;
    private ulong? _previousUser;

    /// <summary>执行一次有界本地采样；任何单项失败都只降级该项，不影响主程序。</summary>
    public WindowsResourceSnapshot Sample()
    {
        var cpu    = TrySampleCpu();
        var memory = TrySampleMemory();
        var disk   = TrySampleDisk();

        return new WindowsResourceSnapshot(
            WindowsResourceSnapshot.Normalize(cpu),
            WindowsResourceSnapshot.Normalize(memory),
            WindowsResourceSnapshot.Normalize(disk),
            DateTimeOffset.UtcNow);
    }

    private double? TrySampleCpu()
    {
        if (!OperatingSystem.IsWindows())
        {
            return null;
        }

        try
        {
            if (!GetSystemTimes(out var idleTime, out var kernelTime, out var userTime))
            {
                return null;
            }

            var idle   = ToUInt64(idleTime);
            var kernel = ToUInt64(kernelTime);
            var user   = ToUInt64(userTime);

            if (_previousIdle is null || _previousKernel is null || _previousUser is null)
            {
                _previousIdle   = idle;
                _previousKernel = kernel;
                _previousUser   = user;
                return null;
            }

            var idleDelta   = idle - _previousIdle.Value;
            var kernelDelta = kernel - _previousKernel.Value;
            var userDelta   = user - _previousUser.Value;

            _previousIdle   = idle;
            _previousKernel = kernel;
            _previousUser   = user;

            var totalDelta = kernelDelta + userDelta;
            if (totalDelta == 0)
            {
                return null;
            }

            var busyDelta = totalDelta > idleDelta
                ? totalDelta - idleDelta
                : 0UL;
            return busyDelta * 100d / totalDelta;
        }
        catch (Exception) when (OperatingSystem.IsWindows())
        {
            // Sampling fault : local UI telemetry is best-effort and must never break task/navigation flow.
            return null;
        }
    }

    private static double? TrySampleMemory()
    {
        if (!OperatingSystem.IsWindows())
        {
            return null;
        }

        try
        {
            var status = new MemoryStatusEx
            {
                Length = (uint)Marshal.SizeOf<MemoryStatusEx>(),
            };
            if (!GlobalMemoryStatusEx(ref status) || status.TotalPhysical == 0)
            {
                return null;
            }

            var used = status.TotalPhysical - status.AvailablePhysical;
            return used * 100d / status.TotalPhysical;
        }
        catch (Exception) when (OperatingSystem.IsWindows())
        {
            // Sampling fault : keep the resource card alive and show an unavailable placeholder.
            return null;
        }
    }

    private static double? TrySampleDisk()
    {
        try
        {
            var systemDirectory = Environment.GetFolderPath(Environment.SpecialFolder.System);
            var root = Path.GetPathRoot(systemDirectory);
            if (string.IsNullOrWhiteSpace(root))
            {
                return null;
            }

            var drive = new DriveInfo(root);
            if (!drive.IsReady || drive.TotalSize <= 0)
            {
                return null;
            }

            var used = drive.TotalSize - drive.AvailableFreeSpace;
            return used * 100d / drive.TotalSize;
        }
        catch (Exception)
        {
            // Sampling fault : DriveInfo availability varies during mount/eject operations.
            return null;
        }
    }

    private static ulong ToUInt64(FileTime fileTime) =>
        ((ulong)fileTime.HighDateTime << 32) | fileTime.LowDateTime;

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetSystemTimes(
        out FileTime idleTime,
        out FileTime kernelTime,
        out FileTime userTime);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GlobalMemoryStatusEx(ref MemoryStatusEx buffer);

    [StructLayout(LayoutKind.Sequential)]
    private struct FileTime
    {
        public uint LowDateTime;
        public uint HighDateTime;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
    private struct MemoryStatusEx
    {
        public uint Length;
        public uint MemoryLoad;
        public ulong TotalPhysical;
        public ulong AvailablePhysical;
        public ulong TotalPageFile;
        public ulong AvailablePageFile;
        public ulong TotalVirtual;
        public ulong AvailableVirtual;
        public ulong AvailableExtendedVirtual;
    }
}
