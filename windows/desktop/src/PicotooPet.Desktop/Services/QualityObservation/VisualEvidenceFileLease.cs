using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.Desktop.Services.QualityObservation;

// Reuse the existing namespace pins, never key access. Read sharing permits CPU decoders.
internal sealed class VisualEvidenceFileLease : IDisposable
{
    private readonly WorkerKeyNamespace _parents;
    private readonly FileStream _file;
    private readonly string _path;
    private readonly (uint Volume, uint High, uint Low, uint SizeHigh, uint SizeLow, long Created, long Written) _stamp;
    public VisualEvidenceFileLease(string path)
    {
        _path = Path.GetFullPath(path);
        ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(_path)!, _path);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(_path)) throw new VisualObservationException("FILE_UNVERIFIED");
        _parents = new WorkerKeyNamespace(Path.GetDirectoryName(_path)!);
        try
        {
            _file = new FileStream(_path, FileMode.Open, FileAccess.Read, FileShare.Read);
            try { _stamp = Stamp(); CheckPath(); }
            catch { _file.Dispose(); throw; }
        }
        catch { _parents.Dispose(); throw; }
    }
    private (uint, uint, uint, uint, uint, long, long) Stamp()
    {
        if (!GetFileInformationByHandle(_file.SafeFileHandle, out var i) || i.Links != 1
            || (i.Attributes & 0x410) != 0 || i.High == 0 && i.Low == 0)
            throw new VisualObservationException("FILE_ID_UNVERIFIED");
        return (i.Volume, i.High, i.Low, i.SizeHigh, i.SizeLow, i.Created, i.Written);
    }
    private void CheckPath()
    {
        var buffer = new char[32768]; var n = GetFinalPathNameByHandleW(_file.SafeFileHandle, buffer, buffer.Length, 0);
        if (n <= 0 || n >= buffer.Length || !string.Equals(new string(buffer, 0, n), @"\\?\" + _path, StringComparison.OrdinalIgnoreCase))
            throw new VisualObservationException("FILE_PATH_CHANGED");
    }
    public void Recheck()
    {
        CheckPath(); if (_stamp != Stamp()) throw new VisualObservationException("FILE_CHANGED");
        ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(_path)!, _path);
    }
    public void Dispose() { _file.Dispose(); _parents.Dispose(); }
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    private struct NativeInfo
    {
        public uint Attributes;
        public long Created, Accessed, Written;
        public uint Volume, SizeHigh, SizeLow, Links, High, Low;
    }
#pragma warning disable SYSLIB1054
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern int GetFinalPathNameByHandleW(SafeFileHandle file, [Out] char[] path, int size, int flags);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out NativeInfo info);
#pragma warning restore SYSLIB1054
}
