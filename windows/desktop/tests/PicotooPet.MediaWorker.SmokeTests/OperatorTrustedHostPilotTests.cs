using System.IO;
using System.Reflection;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using Org.BouncyCastle.Math.EC.Rfc8032;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services.ProductionReference;
using PicotooPet.Desktop.Services;

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
        await PilotCreateWireAsync();
        await RevokedAfterReservationStopsBeforePostAsync();
        Console.WriteLine("P0_OPERATOR_TRUSTED_HOST_OWNED_LOCK=PASS; GPU_POSTS=0");

        Task<string> InvokeAsync(object lease) => (Task<string>)underLock!.Invoke(key,
            [witness, f.Plan, new[] { snapshot }, f.Journal, lease, now, CancellationToken.None])!;
    }

    internal static async Task RevokedAfterReservationStopsBeforePostAsync()
    {
        foreach (var code in new[] { "PILOT_KEY_REVOKED", "PILOT_JOB_CANCELLED" })
        {
        using var f = new I2VExecutorSnapshotTests.Fixture();
        using var http = new HttpClient(f.Transport) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        var gateway = new RevokingGateway(f, code);
        await using var executor = new ProductionExecutionService(gateway, new ComfyProductionClient(http), f.Reference.Journal,
            new ComfyPromptReconciler(http), _ => Task.FromResult(new ProductionPreflightSnapshot(true, "fake", f.Reference.Root,
                f.Reference.Root, f.Reference.Root, f.Reference.Root, []))) { ReferenceSnapshots = f.Reference.Store() };
        await RecoveryTests.ThrowsCodeAsync(code, () => executor.RunAsync("job"));
        RecoveryTests.Assert(f.Attempts == 1 && gateway.NullReservations == 2 && f.Transport.Posts == 0,
            "key revocation or cancellation after reservation must synchronously deny final guarded recheck before Comfy POST");
        await RecoveryTests.ThrowsCodeAsync("MEDIA_SUBMISSION_UNKNOWN", () => executor.RunAsync("job"));
        RecoveryTests.Assert(f.Transport.Posts == 0, "reserved-but-revoked attempt never becomes a duplicate POST on restart");
        }
    }

    private sealed class RevokingGateway(I2VExecutorSnapshotTests.Fixture inner, string denialCode) : IProductionExecutionGateway
    {
        internal int NullReservations { get; private set; }
        public Task<ProductionPlanRecord> GetProductionPlanAsync(string j, CancellationToken ct) => inner.GetProductionPlanAsync(j, ct);
        public Task<ProductionClaimRecord> ClaimProductionJobAsync(string j, string e, CancellationToken ct) => inner.ClaimProductionJobAsync(j, e, ct);
        public Task<ProductionJobRecord> HeartbeatProductionJobAsync(string j, string e, string l, CancellationToken ct) => inner.HeartbeatProductionJobAsync(j, e, l, ct);
        public Task<ProductionTaskRecord> MarkProductionAttemptAsync(string j, string t, ProductionTaskAttemptRequest request, CancellationToken ct)
        {
            if (request.ComfyPromptId is null && ++NullReservations > 1) throw new ProductionWorkerException(denialCode);
            return inner.MarkProductionAttemptAsync(j, t, request, ct);
        }
        public Task<ProductionTaskRecord> CommitProductionResultAsync(string j, string t, ProductionTaskCommitRequest r, CancellationToken ct) => inner.CommitProductionResultAsync(j, t, r, ct);
        public Task<ProductionTaskRecord> FailProductionTaskAsync(string j, string t, ProductionTaskFailureRequest r, CancellationToken ct) => inner.FailProductionTaskAsync(j, t, r, ct);
        public Task<ProductionPackageRecord?> GetProductionPackageAsync(string j, CancellationToken ct) => inner.GetProductionPackageAsync(j, ct);
    }

    private static async Task PilotCreateWireAsync()
    {
        var create = typeof(MacCoreProductionClient).GetMethod("CreateFirstShotPilotV11Async");
        RecoveryTests.Assert(create is not null, "same session client must expose explicit first-shot request without changing v1.0 serialization");
        using var handler = new CreateTransport();
        using var http = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:1/") };
        await using var client = new MacCoreProductionClient(http, "test");
        await client.CreateJobAsync(new("creative", "production.comfyui.v1", "legacy"));
        using (var legacy = JsonDocument.Parse(handler.Body!))
            RecoveryTests.Assert(!legacy.RootElement.TryGetProperty("pilot_first_shot", out _)
                && !legacy.RootElement.TryGetProperty("schema_version", out _), "legacy creation wire remains unchanged");
        await (Task<ProductionJobRecord>)create!.Invoke(client,
            [new ProductionJobCreateRequest("creative", "production.comfyui.v1", "pilot"), "approval", CancellationToken.None])!;
        using var pilot = JsonDocument.Parse(handler.Body!);
        RecoveryTests.Assert(handler.Route == "/api/v1/production/jobs/v1.1" && pilot.RootElement.GetProperty("pilot_first_shot").GetBoolean()
            && pilot.RootElement.GetProperty("schema_version").GetString() == "1.1"
            && pilot.RootElement.GetProperty("approved_reference_ids")[0].GetString() == "approval", "explicit bounded pilot creation wire");
    }

    private sealed class CreateTransport : HttpMessageHandler
    {
        internal string? Body { get; private set; }
        internal string? Route { get; private set; }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Body = await request.Content!.ReadAsStringAsync(ct); Route = request.RequestUri!.AbsolutePath;
            var job = new ProductionJobRecord("job", "creative", new string('a', 64), "goal", "production.comfyui.v1",
                new string('b', 64), "Ready", null, null, null, null, "ci", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
            return new(HttpStatusCode.OK) { Content = new StringContent(JsonSerializer.Serialize(job), System.Text.Encoding.UTF8, "application/json") };
        }
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
