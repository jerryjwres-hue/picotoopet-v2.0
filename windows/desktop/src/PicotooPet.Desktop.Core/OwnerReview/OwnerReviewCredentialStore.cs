using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>主人审核专用凭据存储抽象；与设备令牌（ITokenStore）完全分离。</summary>
public interface IOwnerReviewCredentialStore
{
    string? Read();
    void Save(string credential);
    void Delete();
}

/// <summary>
/// 仅 CurrentUser DPAPI 加密文件：独立路径、独立 entropy，不读写设备令牌的 Credential Manager 项，
/// 不落日志、不进配置。
/// </summary>
public sealed class DpapiOwnerReviewCredentialStore : IOwnerReviewCredentialStore
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("PicotooPet.OwnerReview.Credential.v1");
    private const int MaxCredentialChars = 512;
    private readonly string _path;

    /// <summary>默认位置：%LOCALAPPDATA%\PicotooPet\OwnerReview\owner-review.cred.dpapi。</summary>
    public DpapiOwnerReviewCredentialStore(string? path = null)
    {
        _path = path ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PicotooPet",
            "OwnerReview",
            "owner-review.cred.dpapi");
    }

    public string? Read()
    {
        if (!File.Exists(_path))
        {
            return null;
        }
        var cipher = File.ReadAllBytes(_path);
        if (cipher.Length is 0 or > 16384)
        {
            return null;
        }
        var plain = Transform(cipher, protect: false);
        try
        {
            return Encoding.UTF8.GetString(plain);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(plain);
        }
    }

    public void Save(string credential)
    {
        if (string.IsNullOrWhiteSpace(credential) || credential.Length > MaxCredentialChars
            || credential.Any(char.IsControl) || credential.Any(char.IsWhiteSpace))
        {
            throw new ArgumentException("主人审核凭据格式无效。", nameof(credential));
        }
        var directory = Path.GetDirectoryName(_path)!;
        Directory.CreateDirectory(directory);
        var plain = Encoding.UTF8.GetBytes(credential);
        try
        {
            var cipher = Transform(plain, protect: true);
            var temporary = _path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllBytes(temporary, cipher);
            File.Move(temporary, _path, overwrite: true);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(plain);
        }
    }

    public void Delete()
    {
        if (File.Exists(_path))
        {
            File.Delete(_path);
        }
    }

    private static byte[] Transform(byte[] bytes, bool protect)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException("Windows DPAPI required");
        }
        var input = new Blob { Length = bytes.Length, Data = Marshal.AllocHGlobal(bytes.Length) };
        var entropy = new Blob { Length = Entropy.Length, Data = Marshal.AllocHGlobal(Entropy.Length) };
        Blob output = default;
        try
        {
            Marshal.Copy(bytes, 0, input.Data, bytes.Length);
            Marshal.Copy(Entropy, 0, entropy.Data, Entropy.Length);
            // 标志 1 = CRYPTPROTECT_UI_FORBIDDEN；不使用 LOCAL_MACHINE 范围。
            var ok = protect
                ? CryptProtectData(ref input, null, ref entropy, IntPtr.Zero, IntPtr.Zero, 1, out output)
                : CryptUnprotectData(ref input, IntPtr.Zero, ref entropy, IntPtr.Zero, IntPtr.Zero, 1, out output);
            if (!ok)
            {
                throw new CryptographicException(
                    "OWNER_REVIEW_DPAPI_FAILED",
                    new Win32Exception(Marshal.GetLastWin32Error()));
            }
            if (output.Length is <= 0 or > 16384)
            {
                throw new CryptographicException("OWNER_REVIEW_DPAPI_LENGTH");
            }
            var result = new byte[output.Length];
            Marshal.Copy(output.Data, result, 0, result.Length);
            return result;
        }
        finally
        {
            Clear(input);
            Marshal.FreeHGlobal(input.Data);
            Marshal.FreeHGlobal(entropy.Data);
            if (output.Data != IntPtr.Zero)
            {
                Clear(output);
                _ = LocalFree(output.Data);
            }
        }
    }

    private static void Clear(Blob blob)
    {
        for (var i = 0; i < blob.Length; i++)
        {
            Marshal.WriteByte(blob.Data, i, 0);
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Blob
    {
        public int Length;
        public IntPtr Data;
    }

#pragma warning disable SYSLIB1054 // 极小的 DPAPI 边界，无需 unsafe 项目设置。
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("crypt32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(ref Blob input, string? description, ref Blob entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("crypt32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(ref Blob input, IntPtr description, ref Blob entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", ExactSpelling = true)]
    private static extern IntPtr LocalFree(IntPtr memory);
#pragma warning restore SYSLIB1054
}

/// <summary>仅测试使用的内存凭据；永不落盘。</summary>
public sealed class InMemoryOwnerReviewCredentialStore : IOwnerReviewCredentialStore
{
    private string? _value;
    public string? Read() => _value;
    public void Save(string credential) => _value = credential;
    public void Delete() => _value = null;
}
