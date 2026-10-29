using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>Pin namespace ancestors against rename; never follow a raced-in reparse point.</summary>
internal sealed class WorkerKeyNamespace : IDisposable
{
    private readonly List<SafeFileHandle> _handles = [];
    internal WorkerKeyNamespace(string root)
    {
        try
        {
            var ancestors = new Stack<string>();
            for (DirectoryInfo? dir = new(root); dir is not null; dir = dir.Parent) ancestors.Push(dir.FullName);
            foreach (var dir in ancestors) _handles.Add(Open(dir, true));
        }
        catch { Dispose(); throw; }
    }
    internal static FileStream ReadKey(string path) => new(Open(path, false), FileAccess.Read);
    private static SafeFileHandle Open(string path, bool directory)
    {
        var full = Path.GetFullPath(path.Replace('/', '\\'));
        if (!full.StartsWith(@"\\?\", StringComparison.Ordinal)) full = @"\\?\" + full;
        var handle = CreateFileW(full, directory ? 0x80u : 0x80000000u,
            directory ? 3u : 0u, IntPtr.Zero, 3, 0x00200000u | (directory ? 0x02000000u : 0u), IntPtr.Zero);
        if (handle.IsInvalid) { var error = Marshal.GetLastWin32Error(); handle.Dispose(); throw new IOException("WORKER_KEY_PIN_FAILED", new Win32Exception(error)); }
        if (!GetFileInformationByHandleEx(handle, 9, out var attributes, 8)
            || (attributes.FileAttributes & 0x400) != 0 || ((attributes.FileAttributes & 0x10) != 0) != directory)
        { handle.Dispose(); throw new UnauthorizedAccessException("WORKER_KEY_REPARSE_OR_TYPE_INVALID"); }
        return handle;
    }
    public void Dispose() { for (var i = _handles.Count - 1; i >= 0; i--) _handles[i].Dispose(); _handles.Clear(); }
    [StructLayout(LayoutKind.Sequential)]
    private struct NativeAttributes { public uint FileAttributes; public uint ReparseTag; }
#pragma warning disable SYSLIB1054
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(SafeFileHandle handle, int kind, out NativeAttributes info, uint size);
#pragma warning restore SYSLIB1054
}
