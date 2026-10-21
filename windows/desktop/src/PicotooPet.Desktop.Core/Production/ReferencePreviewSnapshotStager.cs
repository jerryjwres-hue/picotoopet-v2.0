using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using Microsoft.Win32.SafeHandles;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>Preview observation only; neither this DTO nor local bytes grant production permission.</summary>
public sealed record ReferencePreviewSnapshot(string InputRelativePath, string Sha256, long Bytes, string Format);

/// <summary>Consumer binds the four existing ProductionLocalEnvironment methods without copying policy.</summary>
public sealed record ReferencePreviewFilePolicy(
    Func<string, string, bool, string> ResolveUnderRoot,
    Action<string, string> AssertNoLinkEscape,
    Func<string, bool> IsOrdinaryFile,
    Func<string, CancellationToken, Task<string>> Sha256FileAsync);

/// <summary>
/// Durable content-addressed UI staging, NOT an authorization store or GPU path. Read-only attributes
/// protect against accidental edits across restart; a same-user/admin attacker can remove them.
/// Every submit/retry rehashes. The production owner must independently re-authorize/reverify and retain
/// the exact snapshot through LoadImage/terminal history, including unknown POST and crash recovery.
/// UI process handles alone do not provide cross-crash immutability or production admission.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class ReferencePreviewSnapshotStager
{
    public const int MaxBytes = 32 * 1024 * 1024;
    private readonly string _inputRoot;
    private readonly ReferencePreviewFilePolicy _policy;
    private readonly Func<byte[], string, CancellationToken, Task> _validateImage;

    public ReferencePreviewSnapshotStager(string inputRoot, ReferencePreviewFilePolicy policy,
        Func<byte[], string, CancellationToken, Task> validateImage)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(inputRoot);
        ArgumentNullException.ThrowIfNull(policy);
        ArgumentNullException.ThrowIfNull(validateImage);
        _inputRoot = LocalCanonicalPath(inputRoot);
        _policy = policy;
        _validateImage = validateImage;
        ArgumentNullException.ThrowIfNull(policy.ResolveUnderRoot);
        ArgumentNullException.ThrowIfNull(policy.AssertNoLinkEscape);
        ArgumentNullException.ThrowIfNull(policy.IsOrdinaryFile);
        ArgumentNullException.ThrowIfNull(policy.Sha256FileAsync);
    }

    public async Task<ReferencePreviewSnapshot> StageAsync(string sourcePath, string shotId, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ValidateShot(shotId);
        var source = LocalCanonicalPath(sourcePath);
        var format = Format(Path.GetExtension(source));
        using var sourcePins = PinAncestors(source);
        _policy.AssertNoLinkEscape(Path.GetPathRoot(source)!, source);
        if (!_policy.IsOrdinaryFile(source)) throw new InvalidDataException("REFERENCE_SOURCE_NOT_REGULAR");
        using var sourceFile = OpenFile(source);
        var data = await ReadBoundedAsync(sourceFile, cancellationToken).ConfigureAwait(false);
        await _validateImage(data, format, cancellationToken).ConfigureAwait(false);
        var sha = await _policy.Sha256FileAsync(source, cancellationToken).ConfigureAwait(false);
        if (!IsSha(sha)) throw new InvalidDataException("REFERENCE_HASH_INVALID");

        using var managedPins = PinAncestors(Path.Combine(_inputRoot, "unused"));
        var relativeDirectory = "PicotooPet/references/" + sha;
        var current = "";
        foreach (var segment in relativeDirectory.Split('/'))
        {
            current = current.Length == 0 ? segment : current + "/" + segment;
            var directory = _policy.ResolveUnderRoot(_inputRoot, current, false);
            _policy.AssertNoLinkEscape(_inputRoot, directory);
            Directory.CreateDirectory(directory);
            managedPins.Add(OpenPinned(directory, directory: true));
            _policy.AssertNoLinkEscape(_inputRoot, directory);
        }
        var relative = relativeDirectory + "/" + shotId + format;
        var destination = _policy.ResolveUnderRoot(_inputRoot, relative, false);
        var snapshot = new ReferencePreviewSnapshot(relative, sha, data.LongLength, format);
        var temp = _policy.ResolveUnderRoot(_inputRoot, relativeDirectory + "/.staging-" + Guid.NewGuid().ToString("N") + ".tmp", false);
        try
        {
            await using (var output = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                64 * 1024, FileOptions.Asynchronous))
            {
                await output.WriteAsync(data, cancellationToken).ConfigureAwait(false);
                await output.FlushAsync(cancellationToken).ConfigureAwait(false);
                output.Flush(flushToDisk: true);
            }
            _policy.AssertNoLinkEscape(_inputRoot, temp);
            if (await _policy.Sha256FileAsync(temp, cancellationToken).ConfigureAwait(false) != sha
                || new FileInfo(temp).Length != data.LongLength)
                throw new InvalidDataException("REFERENCE_STAGE_WRITE_MISMATCH");
            File.SetAttributes(temp, FileAttributes.ReadOnly);
            try { File.Move(temp, destination, overwrite: false); }
            catch (IOException) when (File.Exists(destination))
            {
                // Another caller may have published the same CAS identity; never overwrite it.
            }
            _ = await ReadVerifiedAsync(snapshot, cancellationToken).ConfigureAwait(false);
            return snapshot;
        }
        finally
        {
            if (File.Exists(temp))
            {
                _policy.AssertNoLinkEscape(_inputRoot, temp);
                File.SetAttributes(temp, FileAttributes.Normal);
                File.Delete(temp); // only this operation's validated, random temp file
            }
        }
    }

    public async Task<byte[]> ReadVerifiedAsync(ReferencePreviewSnapshot snapshot, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        cancellationToken.ThrowIfCancellationRequested();
        var parts = snapshot.InputRelativePath?.Split('/');
        if (!IsSha(snapshot.Sha256) || snapshot.Bytes is <= 0 or > MaxBytes || parts is not { Length: 4 }
            || parts[0] != "PicotooPet" || parts[1] != "references" || parts[2] != snapshot.Sha256
            || Path.GetExtension(parts[3]) != snapshot.Format || Format(snapshot.Format) != snapshot.Format)
            throw new InvalidDataException("REFERENCE_SNAPSHOT_IDENTITY_INVALID");
        ValidateShot(Path.GetFileNameWithoutExtension(parts[3]));
        var path = _policy.ResolveUnderRoot(_inputRoot, snapshot.InputRelativePath!, true);
        using var pins = PinAncestors(path);
        _policy.AssertNoLinkEscape(_inputRoot, path);
        if (!_policy.IsOrdinaryFile(path)) throw new InvalidDataException("REFERENCE_SNAPSHOT_NOT_REGULAR");
        using var file = OpenFile(path);
        if (file.Length != snapshot.Bytes) throw new InvalidDataException("REFERENCE_SNAPSHOT_LENGTH_MISMATCH");
        var data = await ReadBoundedAsync(file, cancellationToken).ConfigureAwait(false);
        if (await _policy.Sha256FileAsync(path, cancellationToken).ConfigureAwait(false) != snapshot.Sha256)
            throw new InvalidDataException("REFERENCE_SNAPSHOT_SHA_MISMATCH");
        await _validateImage(data, snapshot.Format, cancellationToken).ConfigureAwait(false);
        return data;
    }

    private static async Task<byte[]> ReadBoundedAsync(FileStream stream, CancellationToken ct)
    {
        if (stream.Length is <= 0 or > MaxBytes) throw new InvalidDataException("REFERENCE_IMAGE_SIZE_INVALID");
        var data = new byte[checked((int)stream.Length)];
        await stream.ReadExactlyAsync(data, ct).ConfigureAwait(false);
        return data;
    }

    private static string LocalCanonicalPath(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || path.Length > 500 || !Path.IsPathFullyQualified(path)
            || path.StartsWith("\\\\", StringComparison.Ordinal)
            || path.Replace('\\', '/').Split('/').Skip(1).Any(segment => segment is "." or ".."
                || segment.EndsWith('.') || segment.EndsWith(' ') || segment.Contains(':', StringComparison.Ordinal)))
            throw new InvalidDataException("REFERENCE_LOCAL_PATH_INVALID");
        return Path.GetFullPath(path);
    }

    private static void ValidateShot(string shot)
    {
        if (string.IsNullOrWhiteSpace(shot) || shot.Length > 80 || shot is "." or ".."
            || shot.Any(character => !char.IsAsciiLetterOrDigit(character) && character is not ('_' or '-' or '.')))
            throw new InvalidDataException("REFERENCE_SHOT_INVALID");
    }

    private static string Format(string extension) => extension.ToLowerInvariant() switch
    {
        ".png" => ".png", ".jpg" or ".jpeg" => ".jpg", ".webp" => ".webp",
        _ => throw new InvalidDataException("REFERENCE_IMAGE_TYPE_UNSUPPORTED"),
    };

    private static bool IsSha(string? sha) => sha is { Length: 64 }
        && sha.All(character => (character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'));

    // Handle leasing complements the existing path policy, rather than becoming another resolver.
    // Pins prevent a parent rename from redirecting the path-based existing hasher while it is in use.
    private static DirectoryPins PinAncestors(string path)
    {
        var pins = new DirectoryPins();
        try
        {
            var parents = new Stack<string>();
            for (var item = Directory.GetParent(path); item is not null; item = item.Parent) parents.Push(item.FullName);
            foreach (var parent in parents) pins.Add(OpenPinned(parent, directory: true));
            return pins;
        }
        catch { pins.Dispose(); throw; }
    }

    private static FileStream OpenFile(string path)
    {
        var handle = OpenPinned(path, directory: false);
        try { return new FileStream(handle, FileAccess.Read); }
        catch { handle.Dispose(); throw; }
    }

    private sealed class DirectoryPins : IDisposable
    {
        private readonly List<SafeFileHandle> _handles = new();
        public void Add(SafeFileHandle handle) => _handles.Add(handle);
        public void Dispose()
        {
            for (var index = _handles.Count - 1; index >= 0; index--) _handles[index].Dispose();
        }
    }

    private static SafeFileHandle OpenPinned(string path, bool directory)
    {
        var handle = CreateFile(path, directory ? 0u : 0x80000000u, directory ? 3u : 1u, nint.Zero,
            3u, 0x00200000u | (directory ? 0x02000000u : 0u), nint.Zero);
        try
        {
            if (handle.IsInvalid || !GetFileInformationByHandleEx(handle, 9, out var info, 8))
                throw new IOException("REFERENCE_FILE_PIN_FAILED", new Win32Exception(Marshal.GetLastWin32Error()));
            if ((info.Attributes & FileAttributes.ReparsePoint) != 0
                || ((info.Attributes & FileAttributes.Directory) != 0) != directory)
                throw new InvalidDataException("REFERENCE_REPARSE_OR_TYPE_FORBIDDEN");
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
