using System.Buffers.Binary;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using Org.BouncyCastle.Math.EC.Rfc8032;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services.ProductionReference;

internal sealed record WorkerPublicIdentity(string PublicKeyHex, string Fingerprint, string KeyId);

/// <summary>
/// Internal-only measured signer. Not connected to shipping claim or an HTTP endpoint.
/// DPAPI protects at rest against other accounts, not malware running as this user.
/// Core local operator enrollment, authenticated challenge transport and EXE attestation
/// are still absent; no caller may interpret this signature as production authority.
/// </summary>
internal sealed class ProtectedWorkerSigningKey
{
    private readonly string _root;
    private readonly string _executor;
    internal WorkerPublicIdentity Identity { get; }
    private ProtectedWorkerSigningKey(string root, string executor, WorkerPublicIdentity identity)
    { _root = root; _executor = executor; Identity = identity; }

    internal static WorkerPublicIdentity Create(string root, string executor)
    {
        ValidateExecutor(executor);
        root = ValidatePath(root);
        using var parentPin = new WorkerKeyNamespace(Path.GetDirectoryName(root)!);
        // Explicit first-use only. Partial creation, rotation and corruption NEVER regenerate.
        if (Directory.Exists(root) || File.Exists(root)) throw new IOException("WORKER_KEY_ALREADY_INITIALIZED");
        var acl = new DirectorySecurity();
        var sid = CurrentUser();
        acl.SetOwner(sid); acl.SetAccessRuleProtection(true, false);
        acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
            InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        new DirectoryInfo(root).Create(acl);
        AssertPrivate(new DirectoryInfo(root));
        var seed = RandomNumberGenerator.GetBytes(32);
        var executorBytes = Encoding.UTF8.GetBytes(executor);
        var clear = new byte[8 + executorBytes.Length + 64];
        try
        {
            BinaryPrimitives.WriteInt32LittleEndian(clear, 1);
            BinaryPrimitives.WriteInt32LittleEndian(clear.AsSpan(4), executorBytes.Length);
            executorBytes.CopyTo(clear, 8);
            var publicKey = new byte[32];
            Ed25519.GeneratePublicKey(seed, 0, publicKey, 0);
            publicKey.CopyTo(clear, 8 + executorBytes.Length);
            seed.CopyTo(clear, 40 + executorBytes.Length);
            var encrypted = WorkerKeyProtection.Protect(clear);
            // Direct create-only, WriteThrough+Flush(true). A torn write is an unusable key,
            // never an invitation to replace it. No plaintext/temp key file is published.
            using (var file = CreatePrivateFile(Path.Combine(root, "key.dpapi")))
            { file.Write(encrypted); file.Flush(true); }
            return Open(root, executor, Fingerprint(publicKey)).Identity;
        }
        finally { CryptographicOperations.ZeroMemory(seed); CryptographicOperations.ZeroMemory(clear); }
    }

    internal static ProtectedWorkerSigningKey Open(string root, string executor, string expectedFingerprint)
    {
        ValidateExecutor(executor);
        root = ValidatePath(root);
        var identity = ReadKey(root, executor, expectedFingerprint, null);
        return new(root, executor, identity);
    }

    // Reserve before signing. A crash or failed signature burns the nonce, including
    // after process restart. Do not prune, overwrite, or retry an uncertain signature.
    internal void ReserveNonce(string nonce)
    {
        if (nonce.Length != 64 || nonce.All(c => c == '0') || nonce.Any(c => c is not (>= '0' and <= '9') and not (>= 'a' and <= 'f')))
            throw new InvalidDataException("WORKER_NONCE_INVALID");
        ValidatePath(_root);
        using var namespacePin = new WorkerKeyNamespace(_root);
        AssertPrivate(new DirectoryInfo(_root));
        using var file = CreatePrivateFile(Path.Combine(_root, "used-" + ProductionSubmissionJournal.Hash(nonce)));
        file.WriteByte(1); file.Flush(true);
    }

    internal async Task<string> SignMeasuredAsync(JsonElement witness, ProductionPlanRecord plan,
        IReadOnlyList<DurableReferenceSnapshot> snapshots, ProductionSubmissionJournal journal,
        DateTimeOffset now, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var payload = WorkerWitnessEncoding.Payload(witness);
        WorkerWitnessEncoding.RequireFresh(witness, now);
        using var gpu = journal.AcquireGpu(); // existing sole Worker lock, never a new executor
        snapshots = snapshots.ToArray();
        using var witnessPins = new SnapshotPins(snapshots);
        if (journal.Pending().Count != 0 || plan.Tasks.Any(t => journal.Read(plan.ProductionJobId, t.ProductionTaskId) is not null))
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
        ProductionExecutionService.ValidateV11FrozenReferenceIdentities(plan.ProductionJobId, plan);
        var planDigest = Hash(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!));
        Match(witness, "executor_id", _executor); Match(witness, "worker_key_id", Identity.KeyId);
        Match(witness, "production_job_id", plan.ProductionJobId); Match(witness, "plan_digest", planDigest);
        Match(witness, "journal_digest", Hash("[]"u8.ToArray()));
        if (witness.GetProperty("journal_generation").GetInt64() != 0 || snapshots.Count != plan.Tasks.Length) throw InvalidScope();
        // Hash this loaded same-EXE assembly, not a caller-supplied path. This is a local
        // software measurement, NOT a signed-process/Comfy attestation.
        Match(witness, "worker_executable_sha256", await ProductionLocalEnvironment.Sha256FileAsync(typeof(ProtectedWorkerSigningKey).Assembly.Location, ct).ConfigureAwait(false));
        var references = witness.GetProperty("references").EnumerateArray().ToArray();
        if (references.Length != snapshots.Count) throw InvalidScope();
        foreach (var task in plan.Tasks)
        {
            var lease = snapshots.SingleOrDefault(s => s.Measurement.TaskId == task.ProductionTaskId) ?? throw InvalidScope();
            await lease.RecheckForWitnessAsync(ct).ConfigureAwait(false);
            var m = lease.Measurement;
            var r = task.ReferenceAsset ?? throw InvalidScope();
            var reference = references.SingleOrDefault(item => item.GetProperty("production_task_id").GetString() == task.ProductionTaskId);
            if (reference.ValueKind != JsonValueKind.Object || m.JobId != plan.ProductionJobId || m.PlanDigest != planDigest
                || m.ShotId != task.ShotId || m.AssetId != r.AssetId || m.ApprovalId != r.ApprovalId
                || m.SourceSha256 != r.Sha256 || m.SourceBytes != r.Bytes) throw InvalidScope();
            Match(reference, "shot_id", m.ShotId); Match(reference, "asset_id", m.AssetId); Match(reference, "approval_id", m.ApprovalId);
            Match(reference, "approval_request_digest", r.ApprovalRequestDigest);
            Match(reference, "source_relative_path", r.InputRelativePath); Match(reference, "source_sha256", m.SourceSha256);
            Match(reference, "snapshot_sha256", m.SnapshotSha256); Match(reference, "snapshot_receipt_sha256", m.ReceiptSha256);
            Match(reference, "snapshot_relative_path", m.SnapshotRelativePath); Match(reference, "graph_digest", m.GraphDigest);
            if (reference.GetProperty("source_bytes").GetInt64() != m.SourceBytes || reference.GetProperty("snapshot_bytes").GetInt64() != m.SnapshotBytes) throw InvalidScope();
        }
        ct.ThrowIfCancellationRequested();
        // Use actual current UTC again after potentially slow disk/approval work.
        WorkerWitnessEncoding.RequireFresh(witness, DateTimeOffset.UtcNow);
        ReserveNonce(witness.GetProperty("nonce").GetString()!);
        byte[]? signature = null;
        ReadKey(_root, _executor, Identity.Fingerprint, seed =>
        {
            signature = new byte[64];
            Ed25519.Sign(seed, 0, payload, 0, payload.Length, signature, 0);
        });
        return Convert.ToHexStringLower(signature ?? throw new CryptographicException("WORKER_SIGNING_FAILED"));
    }

    private static WorkerPublicIdentity ReadKey(string root, string executor, string expectedFingerprint, Action<byte[]>? sign)
    {
        ValidatePath(root);
        using var namespacePin = new WorkerKeyNamespace(root);
        AssertPrivate(new DirectoryInfo(root));
        var path = Path.Combine(root, "key.dpapi");
        AssertPrivate(new FileInfo(path));
        // Exclusive file handle denies concurrent writes/deletes while decrypting/signing.
        using var file = WorkerKeyNamespace.ReadKey(path);
        if (file.Length is < 1 or > 16384) throw new CryptographicException("WORKER_KEY_CORRUPT");
        var encrypted = new byte[(int)file.Length]; file.ReadExactly(encrypted);
        var clear = WorkerKeyProtection.Unprotect(encrypted);
        byte[]? seed = null;
        try
        {
            var id = Encoding.UTF8.GetBytes(executor);
            if (clear.Length != 8 + id.Length + 64 || BinaryPrimitives.ReadInt32LittleEndian(clear) != 1
                || BinaryPrimitives.ReadInt32LittleEndian(clear.AsSpan(4)) != id.Length || !clear.AsSpan(8, id.Length).SequenceEqual(id))
                throw new CryptographicException("WORKER_KEY_SCOPE_INVALID");
            seed = clear.AsSpan(40 + id.Length, 32).ToArray();
            var publicKey = new byte[32]; Ed25519.GeneratePublicKey(seed, 0, publicKey, 0);
            var fingerprint = Fingerprint(publicKey);
            if (!clear.AsSpan(8 + id.Length, 32).SequenceEqual(publicKey) || fingerprint != expectedFingerprint)
                throw new CryptographicException("WORKER_KEY_FINGERPRINT_MISMATCH");
            sign?.Invoke(seed);
            return new(Convert.ToHexStringLower(publicKey), fingerprint, "wk-" + fingerprint[..40]);
        }
        finally { if (seed is not null) CryptographicOperations.ZeroMemory(seed); CryptographicOperations.ZeroMemory(clear); }
    }
    private static string Fingerprint(byte[] publicKey) => Hash(publicKey);
    private static string Hash(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    private static InvalidDataException InvalidScope() => new("WORKER_WITNESS_LOCAL_SCOPE_MISMATCH");
    private static void Match(JsonElement value, string name, string expected) { if (value.GetProperty(name).GetString() != expected) throw InvalidScope(); }
    private static void ValidateExecutor(string executor)
    {
        if (executor.Length is < 1 or > 120 || executor.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not ('_' or '.' or '-')))
            throw new ArgumentException("WORKER_EXECUTOR_INVALID", nameof(executor));
    }
    private sealed class SnapshotPins : IDisposable
    {
        private readonly List<IDisposable> _pins = [];
        internal SnapshotPins(IReadOnlyList<DurableReferenceSnapshot> snapshots)
        {
            try { foreach (var snapshot in snapshots) _pins.Add(snapshot.RetainForWitness()); }
            catch { Dispose(); throw; }
        }
        public void Dispose() { for (var i = _pins.Count - 1; i >= 0; i--) _pins[i].Dispose(); _pins.Clear(); }
    }
    private static SecurityIdentifier CurrentUser()
    {
        using var identity = WindowsIdentity.GetCurrent();
        return identity.User ?? throw new UnauthorizedAccessException("Windows user required");
    }
    private static string ValidatePath(string root)
    {
        if (!OperatingSystem.IsWindows() || !Path.IsPathFullyQualified(root) || root.StartsWith(@"\\", StringComparison.Ordinal))
            throw new ArgumentException("WORKER_KEY_LOCAL_ROOT_REQUIRED", nameof(root));
        root = Path.GetFullPath(root);
        for (DirectoryInfo? current = new(root); current is not null; current = current.Parent)
            if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0) throw new UnauthorizedAccessException("WORKER_KEY_REPARSE_DENIED");
        if (!Directory.Exists(Path.GetDirectoryName(root))) throw new DirectoryNotFoundException("key parent must already exist");
        return root;
    }
    private static FileStream CreatePrivateFile(string path)
    {
        var sid = CurrentUser();
        var acl = new FileSecurity(); acl.SetOwner(sid); acl.SetAccessRuleProtection(true, false);
        acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, AccessControlType.Allow));
        return new FileInfo(path).Create(FileMode.CreateNew, FileSystemRights.FullControl, FileShare.None, 4096, FileOptions.WriteThrough, acl);
    }
    private static void AssertPrivate(FileSystemInfo info)
    {
        if (!info.Exists || (info.Attributes & FileAttributes.ReparsePoint) != 0) throw new UnauthorizedAccessException("WORKER_KEY_PATH_INVALID");
        var sid = CurrentUser();
        var acl = info is DirectoryInfo directory ? (FileSystemSecurity)directory.GetAccessControl() : ((FileInfo)info).GetAccessControl();
        if ((info is DirectoryInfo && !acl.AreAccessRulesProtected) || !sid.Equals(acl.GetOwner(typeof(SecurityIdentifier)))) throw new UnauthorizedAccessException("WORKER_KEY_OWNER_INVALID");
        var allowsOwner = false;
        foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
        {
            if (!sid.Equals(rule.IdentityReference) || rule.AccessControlType != AccessControlType.Allow)
                throw new UnauthorizedAccessException("WORKER_KEY_ACL_INVALID");
            allowsOwner |= (rule.FileSystemRights & FileSystemRights.FullControl) == FileSystemRights.FullControl;
        }
        if (!allowsOwner) throw new UnauthorizedAccessException("WORKER_KEY_ACL_REQUIRED");
    }
}
