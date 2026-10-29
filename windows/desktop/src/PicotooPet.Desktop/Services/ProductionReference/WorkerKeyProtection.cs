using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>CurrentUser DPAPI only. No machine scope, UI, fallback, or private-key export.</summary>
internal static class WorkerKeyProtection
{
    internal static byte[] Protect(byte[] bytes) => Transform(bytes, true);
    internal static byte[] Unprotect(byte[] bytes) => Transform(bytes, false);
    private static byte[] Transform(byte[] bytes, bool protect)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows DPAPI required");
        var input = new Blob { Length = bytes.Length, Data = Marshal.AllocHGlobal(bytes.Length) };
        Blob output = default;
        try
        {
            Marshal.Copy(bytes, 0, input.Data, bytes.Length);
            var ok = protect
                ? CryptProtectData(ref input, null, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output)
                : CryptUnprotectData(ref input, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output);
            if (!ok) throw new CryptographicException("WORKER_DPAPI_FAILED", new Win32Exception(Marshal.GetLastWin32Error()));
            if (output.Length is <= 0 or > 16384) throw new CryptographicException("WORKER_DPAPI_LENGTH");
            var result = new byte[output.Length];
            Marshal.Copy(output.Data, result, 0, result.Length);
            return result;
        }
        finally
        {
            Clear(input); Marshal.FreeHGlobal(input.Data);
            if (output.Data != IntPtr.Zero) { Clear(output); _ = LocalFree(output.Data); }
        }
    }
    private static void Clear(Blob blob)
    {
        for (var i = 0; i < blob.Length; i++) Marshal.WriteByte(blob.Data, i, 0);
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct Blob { public int Length; public IntPtr Data; }
#pragma warning disable SYSLIB1054 // No unsafe project setting is required for this tiny DPAPI boundary.
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("crypt32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(ref Blob input, string? description, IntPtr entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("crypt32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(ref Blob input, IntPtr description, IntPtr entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", ExactSpelling = true)]
    private static extern IntPtr LocalFree(IntPtr memory);
#pragma warning restore SYSLIB1054
}
