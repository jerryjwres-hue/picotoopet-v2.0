using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using Microsoft.Win32.SafeHandles;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>Untrusted candidate; not a permission receipt. Every field must match authenticated Core approval.</summary>
public sealed record TrustedReferenceDescriptor(
    string ApprovalId, string ShotId, string AssetId, string RelativePath, string Sha256, long ByteLength);

/// <summary>
/// Consumer-owned authenticated Core boundary. Check current user approval and exact equality of ALL
/// descriptor fields against trusted registration (including original image-file SHA, not manifest SHA).
/// Fail closed on revoked/missing/forged approval. No local-disk or manifest-only implementation is valid.
/// No implementation is supplied until G006 freezes that authenticated approval contract.
/// </summary>
public interface ITrustedReferenceApprovalSource
{
    Task<bool> IsApprovedAsync(TrustedReferenceDescriptor descriptor, CancellationToken cancellationToken);
}

/// <summary>
/// Bind directly to ProductionLocalEnvironment.ResolveUnderRoot / AssertNoLinkEscape /
/// IsOrdinaryFile / Sha256FileAsync in Desktop. Core cannot depend on Desktop; do not copy its policy here.
/// </summary>
public sealed record TrustedReferenceFilePolicy(
    Func<string, string, bool, string> ResolveUnderRoot,
    Action<string, string> AssertNoLinkEscape,
    Func<string, bool> IsOrdinaryFile,
    Func<string, CancellationToken, Task<string>> Sha256FileAsync);

/// <summary>
/// Process-bound retained snapshot, not a new permission receipt or asset store. Keep this object alive
/// until the exact Comfy prompt has finished reading LoadImage (conservatively, terminal history).
/// Dispose does not cancel Comfy. A process crash releases locks: restart MUST re-authorize and rehash;
/// a queued prompt spanning downtime additionally needs owner-controlled immutable staging/ACL lifetime.
/// This component does not claim to enforce that cross-process/crash integration contract.
/// </summary>
public sealed class VerifiedReferenceAsset : IDisposable
{
    private readonly FileStream _file;
    private readonly IReadOnlyList<SafeFileHandle> _directories;

    internal VerifiedReferenceAsset(string fullPath, string relativePath, FileStream file, IReadOnlyList<SafeFileHandle> directories)
    {
        FullPath = fullPath;
        RelativePath = relativePath;
        _file = file;
        _directories = directories;
    }
    /// <summary>Only valid while this lease is retained. Not a durable authorization token.</summary>
    public string FullPath { get; }
    /// <summary>Bind to the existing I2V LoadImage slot only after the Core/host integration gates pass.</summary>
    public string RelativePath { get; }
    public void Dispose()
    {
        _file.Dispose();
        for (var index = _directories.Count - 1; index >= 0; index--) _directories[index].Dispose();
    }
}

/// <summary>
/// Independent integrity boundary. The managed root is fixed host configuration, NEVER descriptor input.
/// Compose with the existing Desktop file policy via delegates; no copied resolver/hash policy, database,
/// scheduler, Comfy POST, T2V/I2V selection or approval implementation. Every call revalidates from scratch.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class TrustedReferenceAssetVerifier
{
    private readonly string _managedRoot;
    private readonly TrustedReferenceFilePolicy _policy;
    private readonly ITrustedReferenceApprovalSource _approvals;

    public TrustedReferenceAssetVerifier(string managedRoot, TrustedReferenceFilePolicy policy, ITrustedReferenceApprovalSource approvals)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(managedRoot);
        ArgumentNullException.ThrowIfNull(policy);
        ArgumentNullException.ThrowIfNull(approvals);
        ArgumentNullException.ThrowIfNull(policy.ResolveUnderRoot);
        ArgumentNullException.ThrowIfNull(policy.AssertNoLinkEscape);
        ArgumentNullException.ThrowIfNull(policy.IsOrdinaryFile);
        ArgumentNullException.ThrowIfNull(policy.Sha256FileAsync);
        _managedRoot = Path.GetFullPath(managedRoot);
        _policy = policy;
        _approvals = approvals;
    }

    public async Task<VerifiedReferenceAsset> VerifyAsync(TrustedReferenceDescriptor descriptor, string expectedShotId,
        string expectedAssetId, CancellationToken cancellationToken = default)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("TRUSTED_REFERENCE_WINDOWS_REQUIRED");
        ArgumentNullException.ThrowIfNull(descriptor);
        cancellationToken.ThrowIfCancellationRequested();
        ValidateDescriptor(descriptor, expectedShotId, expectedAssetId);
        await RequireApprovalAsync(descriptor, cancellationToken).ConfigureAwait(false);

        var fullPath = _policy.ResolveUnderRoot(_managedRoot, descriptor.RelativePath, true);
        _policy.AssertNoLinkEscape(_managedRoot, fullPath);
        var directories = new List<SafeFileHandle>();
        FileStream? file = null;
        SafeFileHandle? pendingHandle = null;
        var transferred = false;
        try
        {
            // Pin top-down, including ancestors above managedRoot, so a directory rename cannot
            // redirect LoadImage to different bytes. Handle attributes reject raced-in reparse points.
            var ancestors = new Stack<string>();
            for (var directory = Directory.GetParent(fullPath); directory is not null; directory = directory.Parent)
                ancestors.Push(directory.FullName);
            foreach (var directory in ancestors)
            {
                cancellationToken.ThrowIfCancellationRequested();
                directories.Add(NativeFiles.OpenPinned(directory, directory: true));
            }
            _policy.AssertNoLinkEscape(_managedRoot, fullPath);
            if (!_policy.IsOrdinaryFile(fullPath)) throw new InvalidDataException("TRUSTED_REFERENCE_NOT_REGULAR");

            // OPEN_REPARSE_POINT avoids following a symlink swapped in between the policy check
            // and open. Deny write/delete sharing BEFORE invoking the existing path-based hasher.
            pendingHandle = NativeFiles.OpenPinned(fullPath, directory: false);
            {
                file = new FileStream(pendingHandle, FileAccess.Read);
                pendingHandle = null; // FileStream owns the handle; the returned lease owns FileStream.
                if (file.Length == 0 || file.Length != descriptor.ByteLength)
                    throw new InvalidDataException("TRUSTED_REFERENCE_LENGTH_MISMATCH");
                var hash = await _policy.Sha256FileAsync(fullPath, cancellationToken).ConfigureAwait(false);
                if (!string.Equals(hash, descriptor.Sha256, StringComparison.Ordinal))
                    throw new InvalidDataException("TRUSTED_REFERENCE_SHA256_MISMATCH");
                _policy.AssertNoLinkEscape(_managedRoot, fullPath);
                await RequireApprovalAsync(descriptor, cancellationToken).ConfigureAwait(false);
                cancellationToken.ThrowIfCancellationRequested();
                var lease = new VerifiedReferenceAsset(fullPath, descriptor.RelativePath.Replace('\\', '/'), file, directories);
                transferred = true;
                return lease;
            }
        }
        finally
        {
            pendingHandle?.Dispose();
            if (!transferred)
            {
                file?.Dispose();
                for (var index = directories.Count - 1; index >= 0; index--) directories[index].Dispose();
            }
        }
    }

    private async Task RequireApprovalAsync(TrustedReferenceDescriptor descriptor, CancellationToken cancellationToken)
    {
        if (!await _approvals.IsApprovedAsync(descriptor, cancellationToken).ConfigureAwait(false))
            throw new UnauthorizedAccessException("TRUSTED_REFERENCE_APPROVAL_REQUIRED");
    }

    private static void ValidateDescriptor(TrustedReferenceDescriptor item, string shotId, string assetId)
    {
        if (string.IsNullOrWhiteSpace(item.ApprovalId) || item.ApprovalId.Length > 200
            || string.IsNullOrWhiteSpace(item.ShotId) || item.ShotId.Length > 200
            || string.IsNullOrWhiteSpace(item.AssetId) || item.AssetId.Length > 200
            || !string.Equals(item.ShotId, shotId, StringComparison.Ordinal)
            || !string.Equals(item.AssetId, assetId, StringComparison.Ordinal)
            || item.ByteLength <= 0 || item.Sha256 is null || item.Sha256.Length != 64
            || item.Sha256.Any(character => !((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))))
            throw new InvalidDataException("TRUSTED_REFERENCE_DESCRIPTOR_INVALID");
        // Descriptor canonicality supplements, never substitutes for, the existing bounded-root policy.
        // Reject traversal/Win32 trailing-dot/space aliases even if a resolver could normalize them.
        if (string.IsNullOrWhiteSpace(item.RelativePath)
            || item.RelativePath.Split('/', '\\').Any(segment => segment.Length == 0 || segment is "." or ".."
                || segment.EndsWith('.') || segment.EndsWith(' ')))
            throw new InvalidDataException("TRUSTED_REFERENCE_PATH_NOT_CANONICAL");
    }

    private static class NativeFiles
    {
        public static SafeFileHandle OpenPinned(string path, bool directory)
        {
            // Share READ|WRITE (not DELETE) for directories; READ only for the reference file.
            // Existing writer/delete handles also cause this open to fail closed.
            var handle = CreateFile(path, directory ? 0u : 0x80000000u, directory ? 3u : 1u,
                nint.Zero, 3u, 0x00200000u | (directory ? 0x02000000u : 0u), nint.Zero);
            try
            {
                if (handle.IsInvalid || !GetFileInformationByHandleEx(handle, 9, out var info, 8))
                    throw new IOException("TRUSTED_REFERENCE_PIN_FAILED", new Win32Exception(Marshal.GetLastWin32Error()));
                if ((info.Attributes & FileAttributes.ReparsePoint) != 0
                    || ((info.Attributes & FileAttributes.Directory) != 0) != directory)
                    throw new InvalidDataException("TRUSTED_REFERENCE_PIN_NOT_REGULAR");
                return handle;
            }
            catch { handle.Dispose(); throw; }
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct AttributeTagInfo
        {
            public FileAttributes Attributes;
            public uint ReparseTag;
        }

        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFile(string path, uint access, uint share, nint security, uint creation, uint flags, nint template);

        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetFileInformationByHandleEx(SafeFileHandle handle, int informationClass, out AttributeTagInfo info, uint bufferSize);
    }
}
