using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace PicotooPet.Desktop.Core.Security;

/// <summary>使用 Windows Credential Manager 保存设备令牌，不写入配置或日志。</summary>
public sealed class CredentialManagerTokenStore : ITokenStore
{
    private const uint GenericCredential = 1;
    private const uint PersistLocalMachine = 2;
    private const int ErrorNotFound = 1168;
    private readonly string _targetName;

    /// <summary>使用固定 Credential Target 创建存储。</summary>
    public CredentialManagerTokenStore(
        string targetName = "PicotooPetV2/MacCoreApiToken")
    {
        _targetName = targetName;
    }

    /// <summary>读取当前 Windows 用户保存的令牌。</summary>
    public string? Read()
    {
        if (!CredReadW(_targetName, GenericCredential, 0, out var pointer))
        {
            var error = Marshal.GetLastWin32Error();
            if (error == ErrorNotFound)
            {
                return null;
            }
            throw new Win32Exception(error, "读取 Picotoo Pet 设备令牌失败。");
        }

        try
        {
            var credential = Marshal.PtrToStructure<NativeCredential>(pointer);
            if (credential.CredentialBlob == IntPtr.Zero || credential.CredentialBlobSize == 0)
            {
                return null;
            }
            var bytes = new byte[credential.CredentialBlobSize];
            Marshal.Copy(credential.CredentialBlob, bytes, 0, bytes.Length);
            return Encoding.Unicode.GetString(bytes);
        }
        finally
        {
            CredFree(pointer);
        }
    }

    /// <summary>覆盖保存令牌；明文仅在调用栈和 Credential Manager 中短暂存在。</summary>
    public void Save(string token)
    {
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new ArgumentException("设备令牌不能为空。", nameof(token));
        }

        var bytes = Encoding.Unicode.GetBytes(token);
        if (bytes.Length > 2048)
        {
            throw new ArgumentOutOfRangeException(nameof(token), "设备令牌长度异常。 ");
        }

        var blob = Marshal.AllocHGlobal(bytes.Length);
        try
        {
            Marshal.Copy(bytes, 0, blob, bytes.Length);
            var credential = new NativeCredential
            {
                Type               = GenericCredential,
                TargetName         = _targetName,
                CredentialBlobSize = (uint)bytes.Length,
                CredentialBlob     = blob,
                Persist            = PersistLocalMachine,
                UserName           = Environment.UserName,
            };
            if (!CredWriteW(ref credential, 0))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "保存 Picotoo Pet 设备令牌失败。");
            }
        }
        finally
        {
            Marshal.FreeHGlobal(blob);
            CryptographicOperations.ZeroMemory(bytes);
        }
    }

    /// <summary>删除当前用户保存的设备令牌。</summary>
    public void Delete()
    {
        if (CredDeleteW(_targetName, GenericCredential, 0))
        {
            return;
        }
        var error = Marshal.GetLastWin32Error();
        if (error != ErrorNotFound)
        {
            throw new Win32Exception(error, "删除 Picotoo Pet 设备令牌失败。");
        }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct NativeCredential
    {
        public uint Flags;
        public uint Type;
        public string? TargetName;
        public string? Comment;
        public long LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public string? TargetAlias;
        public string? UserName;
    }

    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CredWriteW(ref NativeCredential credential, uint flags);

    [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CredReadW(
        string target,
        uint type,
        uint reservedFlag,
        out IntPtr credentialPointer);

    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CredDeleteW(string target, uint type, uint flags);

    [DllImport("advapi32.dll")]
    private static extern void CredFree(IntPtr buffer);
}
