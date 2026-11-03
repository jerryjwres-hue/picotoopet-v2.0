using System.IO;
using System.Reflection;
using System.Text.Json;
using Org.BouncyCastle.Math.EC.Rfc8032;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class OperatorTrustedHostPilotTests
{
    internal static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("CI") != "true")
            throw new InvalidOperationException("PILOT_REQUIRES_DISPOSABLE_WINDOWS_CI");
        var underLock = typeof(ProtectedWorkerSigningKey).GetMethod("SignMeasuredUnderLockAsync", BindingFlags.Instance | BindingFlags.NonPublic);
        RecoveryTests.Assert(underLock is not null, "B signer must accept the actual executor-owned GPU lease without reacquiring it");
        RecoveryTests.Assert(typeof(CoreWorkerChallengeClient).GetMethod("ClaimPreparedAsync", BindingFlags.Instance | BindingFlags.NonPublic) is not null,
            "B admission must reuse actual prepared snapshots in the existing challenge/session path");
        using var f = new DurableReferenceSnapshotTests.Fixture();
        const string executor = "windows-same-exe-worker";
        var root = Path.Combine(f.Root, "pilot-key");
        var identity = ProtectedWorkerSigningKey.Create(root, executor);
        var key = ProtectedWorkerSigningKey.Open(root, executor, identity.Fingerprint);
        using var snapshot = await f.PrepareAsync();
        var measured = typeof(WorkerSignerTests).GetMethod("MeasuredAsync", BindingFlags.Static | BindingFlags.NonPublic)!;
        var now = DateTimeOffset.UtcNow;
        var witness = await (Task<JsonElement>)measured.Invoke(null, [f, snapshot, identity, now])!;
        using var gpu = f.Journal.AcquireGpu();
        var signature = await InvokeAsync(gpu);
        var payload = WorkerWitnessEncoding.Payload(witness);
        RecoveryTests.Assert(Ed25519.Verify(Convert.FromHexString(signature), 0, Convert.FromHexString(identity.PublicKeyHex), 0,
            payload, 0, payload.Length), "same protected Ed25519 key signs under the retained exclusive GPU lock");
        await DeniedAsync(() => InvokeAsync(gpu)); // nonce remains spent under lock
        gpu.Dispose();
        await DeniedAsync(() => InvokeAsync(gpu)); // disposed ownership is never authority
        using var other = new DurableReferenceSnapshotTests.Fixture();
        using var wrongGpu = other.Journal.AcquireGpu();
        await DeniedAsync(() => InvokeAsync(wrongGpu));
        RecoveryTests.Assert(f.Journal.Pending().Count == 0, "signing allocates no attempt or GPU submission");
        await ChangedJournalStopsBeforePostAsync();
        Console.WriteLine("P0_OPERATOR_TRUSTED_HOST_OWNED_LOCK=PASS; GPU_POSTS=0");

        Task<string> InvokeAsync(object lease) => (Task<string>)underLock!.Invoke(key,
            [witness, f.Plan, new[] { snapshot }, f.Journal, lease, now, CancellationToken.None])!;
    }

    private static async Task ChangedJournalStopsBeforePostAsync()
    {
        using var f = new I2VExecutorSnapshotTests.Fixture();
        var permits = 0;
        await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => f.Executor(
            permit: (_, _) =>
            {
                if (++permits == 2)
                    f.Reference.Journal.Save(new("orphan", "old-task", new string('a', 64), new string('b', 64), "Submitting", null));
                return null;
            }).RunAsync("job"));
        RecoveryTests.Assert(f.Claims == 1 && f.Attempts == 0 && f.Transport.Posts == 0,
            "new unresolved journal state immediately before durable intent must STOP without a reservation/POST");
        await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => f.Executor().RunAsync("job"));
        RecoveryTests.Assert(f.Transport.Posts == 0, "restart cannot clear another unknown POST or duplicate submit");
    }

    private static async Task DeniedAsync(Func<Task<string>> action)
    {
        try { await action(); }
        catch (Exception e) when (e is IOException or InvalidDataException or ProductionWorkerException or ObjectDisposedException
            || e is TargetInvocationException { InnerException: ProductionWorkerException or ObjectDisposedException }) { return; }
        throw new InvalidOperationException("expected owned-lock/nonce denial");
    }
}
