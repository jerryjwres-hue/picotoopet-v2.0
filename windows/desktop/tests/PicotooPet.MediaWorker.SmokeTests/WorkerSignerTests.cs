using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using System.Text.Json.Nodes;
using Org.BouncyCastle.Math.EC.Rfc8032;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class WorkerSignerTests
{
    internal static void Vectors()
    {
        using var vectors = JsonDocument.Parse(File.ReadAllText(VectorPath()));
        var pub = Convert.FromHexString(vectors.RootElement.GetProperty("public_key_hex").GetString()!);
        var seed = Convert.FromHexString("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60");
        try
        {
            foreach (var item in vectors.RootElement.GetProperty("cases").EnumerateArray())
            {
                var witness = item.GetProperty("witness");
                var bytes = WorkerWitnessEncoding.Payload(witness);
                Assert(Convert.ToHexString(bytes).Equals(item.GetProperty("signed_payload_utf8_hex").GetString(), StringComparison.OrdinalIgnoreCase), "Core canonical bytes");
                var sig = new byte[64];
                Ed25519.Sign(seed, 0, bytes, 0, bytes.Length, sig, 0);
                Assert(Convert.ToHexString(sig).Equals(witness.GetProperty("signature").GetString(), StringComparison.OrdinalIgnoreCase), "Core exact Ed25519 signature");
                Assert(Ed25519.Verify(sig, 0, pub, 0, bytes, 0, bytes.Length), "valid signature");
                bytes[^1] ^= 1;
                Assert(!Ed25519.Verify(sig, 0, pub, 0, bytes, 0, bytes.Length), "tamper rejected");
                Throws(() => WorkerWitnessEncoding.RequireFresh(witness, DateTimeOffset.Parse("2026-10-29T12:01:00Z", System.Globalization.CultureInfo.InvariantCulture)));
                var changed = JsonNode.Parse(witness.GetRawText())!;
                changed["nonce"] = new string('0', 64);
                Throws(() => WorkerWitnessEncoding.Payload(JsonSerializer.SerializeToElement(changed)));
                changed["nonce"] = new string('2', 64);
                changed["journal_state"] = "UNCERTAIN";
                Throws(() => WorkerWitnessEncoding.Payload(JsonSerializer.SerializeToElement(changed)));
            }
        }
        finally { CryptographicOperations.ZeroMemory(seed); }
        Console.WriteLine("P0_WORKER_ED25519_CORE_BYTES=PASS");
    }

    internal static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("CI") != "true")
            throw new InvalidOperationException("WORKER_KEY_REQUIRES_DISPOSABLE_NATIVE_CI");
        Vectors();
        await PublishDependencyAsync();
        using var f = new DurableReferenceSnapshotTests.Fixture();
        var root = Path.Combine(f.Root, "signing-key");
        const string executor = "windows-same-exe-worker";
        var identity = ProtectedWorkerSigningKey.Create(root, executor);
        var fingerprint = identity.Fingerprint;
        Assert(identity.KeyId == "wk-" + fingerprint[..40], "Core key id");
        Throws(() => ProtectedWorkerSigningKey.Create(root, executor));
        Throws(() => ProtectedWorkerSigningKey.Open(root, executor, new string('a', 64)));
        Throws(() => ProtectedWorkerSigningKey.Open(root, "other-worker", fingerprint));
        using var lease = await f.PrepareAsync();
        var now = DateTimeOffset.UtcNow;
        var witness = Measured(f, lease, identity, now);
        var key = ProtectedWorkerSigningKey.Open(root, executor, fingerprint);
        var signature = await key.SignMeasuredAsync(witness, f.Plan, [lease], f.Journal, now, CancellationToken.None);
        var payload = WorkerWitnessEncoding.Payload(witness);
        Assert(Ed25519.Verify(Convert.FromHexString(signature), 0, Convert.FromHexString(identity.PublicKeyHex), 0, payload, 0, payload.Length), "real protected key signature");
        await DeniedAsync(() => key.SignMeasuredAsync(witness, f.Plan, [lease], f.Journal, now, CancellationToken.None));
        await ChildAsync(root, fingerprint, false); // Reopen actual DPAPI key and deny nonce reuse in another process.
        var changed = JsonNode.Parse(witness.GetRawText())!;
        changed["nonce"] = new string('c', 64);
        changed["plan_digest"] = new string('b', 64);
        await DeniedAsync(() => key.SignMeasuredAsync(JsonSerializer.SerializeToElement(changed), f.Plan, [lease], f.Journal, now, CancellationToken.None));
        f.Approved = false;
        changed["plan_digest"] = f.Digest;
        await DeniedAsync(() => key.SignMeasuredAsync(JsonSerializer.SerializeToElement(changed), f.Plan, [lease], f.Journal, now, CancellationToken.None));
        f.Approved = true;
        var journalRecord = new ProductionSubmission(f.Plan.ProductionJobId, f.Task.ProductionTaskId, f.Digest,
            new string('e', 64), "Submitting", null);
        f.Journal.Save(journalRecord);
        await DeniedAsync(() => key.SignMeasuredAsync(JsonSerializer.SerializeToElement(changed), f.Plan, [lease], f.Journal, now, CancellationToken.None));
        Assert(f.Journal.Read(f.Plan.ProductionJobId, f.Task.ProductionTaskId) == journalRecord, "unknown POST untouched");
        using (var other = new DurableReferenceSnapshotTests.Fixture())
        {
            using var disposed = await other.PrepareAsync();
            var measured = Measured(other, disposed, identity, DateTimeOffset.UtcNow);
            disposed.Dispose();
            await DeniedAsync(() => key.SignMeasuredAsync(measured, other.Plan, [disposed], other.Journal, DateTimeOffset.UtcNow, CancellationToken.None));
        }
        using (var concurrent = new DurableReferenceSnapshotTests.Fixture())
        {
            using var retained = await concurrent.PrepareAsync();
            var measured = Measured(concurrent, retained, identity, DateTimeOffset.UtcNow);
            concurrent.ApprovalProbe = _ =>
            {
                retained.Dispose();
                Throws(() => File.WriteAllBytes(concurrent.Full(concurrent.Reference.InputRelativePath), [0]));
                return Task.CompletedTask;
            };
            await DeniedAsync(() => key.SignMeasuredAsync(measured, concurrent.Plan, [retained], concurrent.Journal, DateTimeOffset.UtcNow, CancellationToken.None));
        }
        var rotatedRoot = Path.Combine(f.Root, "rotated-key");
        var rotated = ProtectedWorkerSigningKey.Create(rotatedRoot, executor);
        Assert(rotated.Fingerprint != fingerprint, "rotation is a new manual identity");
        Throws(() => ProtectedWorkerSigningKey.Open(rotatedRoot, executor, fingerprint));
        var partialRoot = Path.Combine(f.Root, "partial-key");
        Directory.CreateDirectory(partialRoot);
        Throws(() => ProtectedWorkerSigningKey.Create(partialRoot, executor));
        Throws(() => ProtectedWorkerSigningKey.Open(partialRoot, executor, fingerprint));
        var blob = Path.Combine(root, "key.dpapi");
        var original = File.ReadAllBytes(blob);
        var tamper = (byte[])original.Clone(); tamper[^1] ^= 1;
        File.WriteAllBytes(blob, tamper);
        await ChildAsync(root, fingerprint, true);
        File.WriteAllBytes(blob, original);
        var acl = new DirectoryInfo(root).GetAccessControl();
        acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(WellKnownSidType.WorldSid, null), FileSystemRights.Read, AccessControlType.Allow));
        new DirectoryInfo(root).SetAccessControl(acl);
        Throws(() => ProtectedWorkerSigningKey.Open(root, executor, fingerprint));
        acl.RemoveAccessRuleAll(new FileSystemAccessRule(new SecurityIdentifier(WellKnownSidType.WorldSid, null), FileSystemRights.Read, AccessControlType.Allow));
        new DirectoryInfo(root).SetAccessControl(acl);
        File.Delete(blob);
        Throws(() => ProtectedWorkerSigningKey.Open(root, executor, fingerprint));
        Throws(() => ProtectedWorkerSigningKey.Create(root, executor));
        Console.WriteLine("P0_WORKER_DPAPI_RESTART_TAMPER_REPLAY=PASS; GPU_POSTS=0; I2V=BLOCKED");
    }

    internal static void Probe(string root, string fingerprint, bool corrupt)
    {
        if (Environment.GetEnvironmentVariable("CI") != "true") throw new InvalidOperationException("CI only");
        if (corrupt) Throws(() => ProtectedWorkerSigningKey.Open(root, "windows-same-exe-worker", fingerprint));
        else
        {
            var key = ProtectedWorkerSigningKey.Open(root, "windows-same-exe-worker", fingerprint);
            Assert(key.Identity.Fingerprint == fingerprint, "restart preserves public identity");
            Throws(() => key.ReserveNonce(new string('2', 64)));
        }
    }

    private static async Task PublishDependencyAsync()
    {
        var library = typeof(Ed25519).Assembly.Location;
        const string expected = "ef92fc661e8d7ba8ec4d39a7cdfcdba41f14cb327f0d24fe79d0b5bb428899b5";
        Assert(Hash(File.ReadAllBytes(library)) == expected, "exact approved net6.0 BouncyCastle artifact");
        var root = new DirectoryInfo(Path.GetDirectoryName(VectorPath())!);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "AGENTS.md"))) root = root.Parent;
        if (root is null) throw new DirectoryNotFoundException("repository");
        var output = Path.Combine(Path.GetTempPath(), "p0-witness-publish-" + Guid.NewGuid().ToString("N"));
        try
        {
            var info = new ProcessStartInfo("dotnet") { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
            foreach (var arg in new[] { "publish", Path.Combine(root.FullName, "windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj"),
                "--no-build", "--no-restore", "-c", "Release", "-o", output }) info.ArgumentList.Add(arg);
            using var process = Process.Start(info)!;
            var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
            try { await process.WaitForExitAsync(timeout.Token); }
            catch { process.Kill(entireProcessTree: true); throw; }
            Assert(process.ExitCode == 0, "native portable publish: " + await stdout + await stderr);
            Assert(Hash(File.ReadAllBytes(Path.Combine(output, "BouncyCastle.Cryptography.dll"))) == expected, "portable publish includes exact managed signing primitive");
            Assert(File.Exists(Path.Combine(output, "Picotoo Pet AI.exe")), "existing same EXE portable payload");
            Assert(typeof(ProtectedWorkerSigningKey).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>().Any(a =>
                a.Key == "ThirdParty.BouncyCastle.Cryptography.2.7.0" && a.Value!.Contains("MIT License", StringComparison.Ordinal)), "shipping license notice");
        }
        finally { if (Directory.Exists(output)) Directory.Delete(output, true); }
        Console.WriteLine("P0_WORKER_ED25519_NATIVE_PORTABLE_PUBLISH=PASS");
    }

    private static async Task ChildAsync(string root, string fingerprint, bool corrupt)
    {
        var info = new ProcessStartInfo("dotnet") { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
        info.ArgumentList.Add(Assembly.GetExecutingAssembly().Location);
        foreach (var arg in new[] { "--worker-key-probe", root, fingerprint, corrupt.ToString(System.Globalization.CultureInfo.InvariantCulture) }) info.ArgumentList.Add(arg);
        using var process = Process.Start(info)!;
        var output = process.StandardOutput.ReadToEndAsync(); var errors = process.StandardError.ReadToEndAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        try { await process.WaitForExitAsync(timeout.Token); }
        catch { process.Kill(entireProcessTree: true); throw; }
        Assert(process.ExitCode == 0, "restart child: " + await output + await errors);
    }

    private static JsonElement Measured(DurableReferenceSnapshotTests.Fixture f, DurableReferenceSnapshot lease, WorkerPublicIdentity id, DateTimeOffset now)
    {
        var m = lease.Measurement;
        return JsonSerializer.SerializeToElement(new
        {
            schema_version = "production.worker_witness.v1", algorithm = "ed25519", worker_key_id = id.KeyId,
            executor_id = "windows-same-exe-worker", production_job_id = m.JobId, plan_digest = m.PlanDigest,
            issued_at = now.ToString("yyyy-MM-ddTHH:mm:ss.ffffff'Z'", System.Globalization.CultureInfo.InvariantCulture),
            expires_at = now.AddSeconds(25).ToString("yyyy-MM-ddTHH:mm:ss.ffffff'Z'", System.Globalization.CultureInfo.InvariantCulture),
            nonce = new string('2', 64), worker_executable_sha256 = Hash(File.ReadAllBytes(typeof(ProtectedWorkerSigningKey).Assembly.Location)),
            journal_digest = Hash("[]"u8.ToArray()), journal_generation = 0, journal_state = "NO_PRIOR_POST",
            references = new[] { new { production_task_id = m.TaskId, shot_id = m.ShotId, asset_id = m.AssetId, approval_id = m.ApprovalId,
                approval_request_digest = f.Reference.ApprovalRequestDigest, source_sha256 = m.SourceSha256, source_bytes = m.SourceBytes,
                source_relative_path = f.Reference.InputRelativePath, snapshot_sha256 = m.SnapshotSha256, snapshot_bytes = m.SnapshotBytes,
                snapshot_receipt_sha256 = m.ReceiptSha256, graph_digest = m.GraphDigest, snapshot_relative_path = m.SnapshotRelativePath } },
            signature = new string('a', 128),
        });
    }
    private static string VectorPath()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null)
        {
            var path = Path.Combine(root.FullName, "windows/desktop/tests/PicotooPet.MediaWorker.SmokeTests/WorkerWitnessV11Vectors/vectors.json");
            if (File.Exists(path)) return path;
            root = root.Parent;
        }
        throw new FileNotFoundException("Core vectors");
    }
    private static string Hash(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    private static void Assert(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
    private static void Throws(Action action) { try { action(); } catch (Exception e) when (e is IOException or CryptographicException or InvalidDataException or UnauthorizedAccessException or ArgumentException or ProductionWorkerException or ObjectDisposedException) { return; } throw new InvalidOperationException("expected denial"); }
    private static async Task DeniedAsync(Func<Task<string>> action) { try { await action(); } catch (Exception e) when (e is IOException or CryptographicException or InvalidDataException or UnauthorizedAccessException or ArgumentException or ProductionWorkerException or ObjectDisposedException) { return; } throw new InvalidOperationException("expected signing denial"); }
}
