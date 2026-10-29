using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>Disposing pins never deletes the durable copy, even after an uncertain POST.</summary>
internal sealed class DurableReferenceSnapshot(string relativePath, VerifiedReferenceAsset original,
    VerifiedReferenceAsset snapshot, VerifiedReferenceAsset receipt, ITrustedReferenceApprovalSource approvals,
    TrustedReferenceDescriptor descriptor) : IDisposable
{
    public string RelativePath { get; } = relativePath;
    public async Task ReauthorizeAsync(CancellationToken ct)
    {
        if (!await approvals.IsApprovedAsync(descriptor, ct).ConfigureAwait(false))
            throw new ProductionWorkerException("I2V_REFERENCE_APPROVAL_REQUIRED");
    }
    public void Dispose() { receipt.Dispose(); snapshot.Dispose(); original.Dispose(); }
}

/// <summary>
/// No authority registry, scheduler or GPU lock. Caller holds the existing journal GPU lock.
/// A create-only receipt binds the private LoadImage path to the full plan and graph digests.
/// Files and write/delete-denial ACLs survive process death. Never garbage-collect here:
/// unknown prompts may still read LoadImage after the worker has exited or rebooted.
/// Deployment prerequisite: NTFS and stable namespace ownership of the configured input
/// root AND all ancestors above it while Comfy has queued work. Managed subtree ACLs
/// cannot stop a privileged/ancestor owner replacing the entire configured root.
/// Shipping constructors remain disarmed pending controller Core/operator authorization.
/// </summary>
internal sealed class ProductionReferenceSnapshotStore
{
    private readonly string _inputRoot;
    private readonly Func<ProductionPlanRecord, ProductionTaskPlanRecord, string, ITrustedReferenceApprovalSource> _approvals;
    private static SecurityIdentifier Everyone => new(WellKnownSidType.WorldSid, null);
    private const FileSystemRights FileDenial = FileSystemRights.Write | FileSystemRights.Delete;
    private const FileSystemRights DirectoryDenial = FileSystemRights.Delete | FileSystemRights.DeleteSubdirectoriesAndFiles;
    public ProductionReferenceSnapshotStore(string inputRoot,
        Func<ProductionPlanRecord, ProductionTaskPlanRecord, string, ITrustedReferenceApprovalSource> approvals)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(inputRoot);
        ArgumentNullException.ThrowIfNull(approvals);
        _inputRoot = Path.GetFullPath(inputRoot);
        _approvals = approvals;
    }

    public static string RelativePathFor(ProductionTaskPlanRecord task, string planDigest)
    {
        var reference = task.ReferenceAsset ?? throw new ProductionWorkerException("I2V_V11_REFERENCE_IDENTITY_INVALID");
        var extension = Path.GetExtension(reference.InputRelativePath);
        if (extension is not (".png" or ".jpg" or ".jpeg" or ".webp"))
            throw new ProductionWorkerException("I2V_REFERENCE_FORMAT_INVALID");
        return $"PicotooPet/references/{reference.Sha256}/worker-{ProductionSubmissionJournal.Hash(planDigest + "\n" + task.ProductionTaskId)}{extension}";
    }

    public void RequireInputRoot(string? inputRoot)
    {
        if (inputRoot is null || !string.Equals(Path.GetFullPath(inputRoot), _inputRoot, StringComparison.OrdinalIgnoreCase))
            throw new ProductionWorkerException("I2V_SNAPSHOT_ROOT_INVALID");
    }

    public async Task<DurableReferenceSnapshot> PrepareAsync(ProductionPlanRecord plan,
        ProductionTaskPlanRecord task, string planDigest, string graphDigest,
        ProductionSubmissionJournal journal, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        ProductionExecutionService.ValidateV11FrozenReferenceIdentities(plan.ProductionJobId, plan);
        var digest = Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!))).ToLowerInvariant();
        if (plan.SchemaVersion != "1.1" || digest != planDigest || !plan.Tasks.Contains(task)
            || graphDigest.Length != 64 || graphDigest.Any(c => c is not (>= '0' and <= '9') and not (>= 'a' and <= 'f')))
            throw new ProductionWorkerException("MEDIA_SUBMISSION_IDENTITY_CONFLICT");
        var r = task.ReferenceAsset ?? throw new ProductionWorkerException("I2V_V11_REFERENCE_IDENTITY_INVALID");
        var descriptor = new TrustedReferenceDescriptor(r.ApprovalId, r.ShotId, r.AssetId, r.InputRelativePath, r.Sha256, r.Bytes);
        var approvals = _approvals(plan, task, planDigest);
        var verifier = CreateVerifier(approvals);
        var original = await verifier.VerifyAsync(descriptor, task.ShotId, r.AssetId, ct).ConfigureAwait(false);
        VerifiedReferenceAsset? snapshot = null;
        VerifiedReferenceAsset? receiptPin = null;
        try
        {
            var relative = RelativePathFor(task, planDigest);
            var destination = ProductionLocalEnvironment.ResolveUnderRoot(_inputRoot, relative, false);
            var receiptPath = destination + ".snapshot.json";
            var receipt = new SnapshotReceipt("loadimage_snapshot.v1", plan.ProductionJobId,
                task.ProductionTaskId, planDigest, graphDigest, relative, r);
            var receiptBytes = JsonSerializer.SerializeToUtf8Bytes(receipt);
            var prior = journal.Read(plan.ProductionJobId, task.ProductionTaskId);
            if (prior is not null && (prior.PlanDigest != planDigest || prior.GraphDigest != graphDigest))
                throw new ProductionWorkerException("MEDIA_SUBMISSION_IDENTITY_CONFLICT");
            // Even Prepared may mean that Core reserved an attempt before a crash.
            // Missing copies/receipts after ANY journal intent must never be recreated.
            var mayPublish = prior is null;
            ProductionLocalEnvironment.AssertNoLinkEscape(_inputRoot, destination);
            if (File.Exists(receiptPath))
            {
                if (!mayPublish) AssertProtected(new FileInfo(receiptPath), FileDenial);
            }
            else
            {
                if (!mayPublish || File.Exists(destination))
                    throw new ProductionWorkerException("I2V_SNAPSHOT_OWNERSHIP_REQUIRED");
                await PublishAsync(receiptPath, receiptBytes, ct).ConfigureAwait(false);
            }
            // Pin and hash the exact expected receipt with the SAME native verifier, rather
            // than following a path-based metadata read that could race a symlink/writer.
            var receiptDescriptor = descriptor with
            {
                RelativePath = relative + ".snapshot.json",
                Sha256 = Convert.ToHexString(SHA256.HashData(receiptBytes)).ToLowerInvariant(),
                ByteLength = receiptBytes.Length,
            };
            receiptPin = await CreateVerifier(new PrivateCopyApproval(approvals, descriptor, receiptDescriptor))
                .VerifyAsync(receiptDescriptor, task.ShotId, r.AssetId, ct).ConfigureAwait(false);
            if (!File.Exists(destination))
            {
                if (!mayPublish) throw new ProductionWorkerException("I2V_DURABLE_SNAPSHOT_MISSING");
                // Original is pinned by the existing verifier before copying, including all ancestors.
                var bytes = await File.ReadAllBytesAsync(original.FullPath, ct).ConfigureAwait(false);
                if (bytes.LongLength != r.Bytes || !SHA256.HashData(bytes).AsSpan().SequenceEqual(Convert.FromHexString(r.Sha256)))
                    throw new ProductionWorkerException("I2V_REFERENCE_BYTES_CHANGED");
                await PublishAsync(destination, bytes, ct).ConfigureAwait(false);
            }
            // Do not manufacture a second approval for the private path. Reuse the exact
            // authenticated original authorization, only after the receipt/byte binding above.
            var privateDescriptor = descriptor with { RelativePath = relative };
            snapshot = await CreateVerifier(new PrivateCopyApproval(approvals, descriptor, privateDescriptor))
                .VerifyAsync(privateDescriptor, task.ShotId, r.AssetId, ct).ConfigureAwait(false);
            foreach (var directory in ManagedDirectories(destination))
            {
                if (mayPublish) Protect(new DirectoryInfo(directory), DirectoryDenial);
                AssertProtected(new DirectoryInfo(directory), DirectoryDenial);
            }
            foreach (var file in new[] { destination, receiptPath })
            {
                if (mayPublish) Protect(new FileInfo(file), FileDenial);
                AssertProtected(new FileInfo(file), FileDenial);
            }
            ct.ThrowIfCancellationRequested();
            return new(relative, original, snapshot, receiptPin, approvals, descriptor);
        }
        catch { receiptPin?.Dispose(); snapshot?.Dispose(); original.Dispose(); throw; }
    }

    private TrustedReferenceAssetVerifier CreateVerifier(ITrustedReferenceApprovalSource approvals) =>
        new(_inputRoot, new(ProductionLocalEnvironment.ResolveUnderRoot,
            ProductionLocalEnvironment.AssertNoLinkEscape, ProductionLocalEnvironment.IsOrdinaryFile,
            ProductionLocalEnvironment.Sha256FileAsync), approvals);

    private IEnumerable<string> ManagedDirectories(string file)
    {
        for (var directory = Directory.GetParent(file); directory is not null; directory = directory.Parent)
        {
            ProductionLocalEnvironment.AssertNoLinkEscape(_inputRoot, directory.FullName);
            yield return directory.FullName;
            if (string.Equals(directory.FullName, _inputRoot.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
                yield break;
        }
        throw new ProductionWorkerException("I2V_SNAPSHOT_ROOT_INVALID");
    }

    private static FileSystemSecurity AccessControl(FileSystemInfo info) => info is DirectoryInfo directory
        ? directory.GetAccessControl() : ((FileInfo)info).GetAccessControl();

    private static void Protect(FileSystemInfo info, FileSystemRights denial)
    {
        var acl = AccessControl(info);
        acl.AddAccessRule(new FileSystemAccessRule(Everyone, denial, AccessControlType.Deny));
        if (info is DirectoryInfo directory) directory.SetAccessControl((DirectorySecurity)acl);
        else ((FileInfo)info).SetAccessControl((FileSecurity)acl);
    }

    private static void AssertProtected(FileSystemInfo info, FileSystemRights denial)
    {
        ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(info.FullName)!, info.FullName);
        var denied = (FileSystemRights)0;
        foreach (FileSystemAccessRule rule in AccessControl(info).GetAccessRules(true, false, typeof(SecurityIdentifier)))
            if (rule.AccessControlType == AccessControlType.Deny && rule.IdentityReference.Equals(Everyone))
                denied |= rule.FileSystemRights;
        if ((denied & denial) != denial)
            throw new ProductionWorkerException("I2V_SNAPSHOT_WRITE_DENIAL_REQUIRED");
    }

    private static async Task PublishAsync(string destination, byte[] bytes, CancellationToken ct)
    {
        var temp = destination + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            await using (var file = new FileStream(temp, FileMode.CreateNew, FileAccess.Write,
                FileShare.None, 65536, FileOptions.Asynchronous | FileOptions.WriteThrough))
            {
                await file.WriteAsync(bytes, ct).ConfigureAwait(false);
                await file.FlushAsync(ct).ConfigureAwait(false);
                file.Flush(flushToDisk: true);
            }
            ct.ThrowIfCancellationRequested();
            // NTFS same-directory, no replacement; WRITE_THROUGH makes publication durable.
            if (!MoveFileEx(temp, destination, 0x8))
                throw new IOException("I2V_SNAPSHOT_PUBLISH_FAILED", new Win32Exception(Marshal.GetLastWin32Error()));
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }

    private sealed record SnapshotReceipt(string SchemaVersion, string JobId, string TaskId,
        string PlanDigest, string GraphDigest, string RelativePath, ProductionReferenceAssetV11Record Reference);

    private sealed class PrivateCopyApproval(ITrustedReferenceApprovalSource authority,
        TrustedReferenceDescriptor original, TrustedReferenceDescriptor expected) : ITrustedReferenceApprovalSource
    {
        public Task<bool> IsApprovedAsync(TrustedReferenceDescriptor candidate, CancellationToken ct) =>
            candidate == expected ? authority.IsApprovedAsync(original, ct) : Task.FromResult(false);
    }

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", EntryPoint = "MoveFileExW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool MoveFileEx(string source, string destination, uint flags);
}
