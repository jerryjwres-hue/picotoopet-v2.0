using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class ShippingReferenceProofTests
{
    private const string Blocked = "I2V_CROSS_ENDPOINT_WORKER_PROOF_REQUIRED";

    public static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("CI") != "true")
            throw new InvalidOperationException("SHIPPING_PROOF_REQUIRES_DISPOSABLE_WINDOWS_CI");
        await using var f = await Fixture.CreateAsync();
        await using var worker = ProductionExecutionService.Create(f.Session);
        var composition = worker.ShippingReferences
            ?? throw new InvalidOperationException("shipping factory must compose the paired reference boundary");
        // This is the real factory's authenticated HTTP/file composition, not an injected gateway.
        // Measurement preparation is diagnostic only; it never claims a lease or issues proof.
        var store = composition.CreateSnapshotStore(f.Work.Root);
        var journal = new ProductionSubmissionJournal(ProductionSubmissionJournal.DefaultRoot);
        using (journal.AcquireGpu())
        using (var snapshot = await store.PrepareAsync(f.Work.Plan, f.Work.Task, f.Work.Digest,
            new string('e', 64), journal, CancellationToken.None))
        {
            var measured = snapshot.Measurement;
            RecoveryTests.Assert(measured.SourceSha256 == Hash(f.Work.Bytes)
                && measured.SnapshotSha256 == Hash(File.ReadAllBytes(f.Work.Full(snapshot.RelativePath)))
                && measured.ReceiptSha256 == Hash(File.ReadAllBytes(f.Work.Full(snapshot.RelativePath) + ".snapshot.json"))
                && measured.SourceBytes == f.Work.Bytes.Length && measured.SnapshotBytes == f.Work.Bytes.Length
                && measured.ReceiptBytes > 0 && measured.PlanDigest == f.Work.Digest
                && measured.GraphDigest == new string('e', 64) && measured.JobId == "job"
                && measured.TaskId == "task" && measured.ShotId == "shot"
                && measured.AssetId == f.Work.Reference.AssetId && measured.ApprovalId == f.Work.Reference.ApprovalId,
                "local facts must describe real pinned bytes and exact frozen context, never a claimed SHA");
        }
        await RecoveryTests.ThrowsCodeAsync(Blocked, () => worker.RunAsync("job"));
        // Even forcing the old internal test seam on a real factory object cannot
        // turn local measurements/DI into separately authenticated Worker proof.
        (typeof(ProductionExecutionService).GetProperty("ReferenceSnapshots", BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("snapshot seam missing")).SetValue(worker, store);
        await RecoveryTests.ThrowsCodeAsync(Blocked, () => worker.RunAsync("job"));
        await using (var restarted = ProductionExecutionService.Create(f.Session))
            await RecoveryTests.ThrowsCodeAsync(Blocked, () => restarted.RunAsync("job"));
        RecoveryTests.Assert(journal.Pending().Count == 0, "correct hashes/public bearer cannot create GPU intent");

        f.Api.Approved = false;
        await DurableReferenceSnapshotTests.DeniedAsync(async () =>
        {
            using var gpu = journal.AcquireGpu();
            using var denied = await store.PrepareAsync(f.Work.Plan, f.Work.Task, f.Work.Digest,
                new string('e', 64), journal, CancellationToken.None);
        });
        await RecoveryTests.ThrowsCodeAsync(Blocked, () => worker.RunAsync("job"));
        f.Api.Approved = true;
        File.WriteAllText(f.Work.Full(f.Work.Reference.InputRelativePath), "changed original");
        await DurableReferenceSnapshotTests.DeniedAsync(async () =>
        {
            using var gpu = journal.AcquireGpu();
            using var denied = await store.PrepareAsync(f.Work.Plan, f.Work.Task, f.Work.Digest,
                new string('e', 64), journal, CancellationToken.None);
        });

        journal.Save(new("job", "task", f.Work.Digest, new string('e', 64), "Submitting", null));
        try
        {
            await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => worker.RunAsync("job"));
            RecoveryTests.Assert(journal.Pending().Single().Phase == "Submitting",
                "shipping factory cannot erase/recreate an unknown old POST after restart");
        }
        finally { File.Delete(f.JournalRecord); }
        RecoveryTests.Assert(f.Api.Requests.All(r => r.StartsWith("GET ", StringComparison.Ordinal))
            && f.Comfy.Requests.IsEmpty, "no Core mutation or Comfy preflight/POST is allowed without independent proof");
        Console.WriteLine("P0_SHIPPING_REFERENCE_MEASURED_BUT_NO_PROOF=PASS; CLAIM=0; ATTEMPT=0; COMFY_REQUESTS=0; I2V=BLOCKED");
    }

    private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private sealed class Fixture : IAsyncDisposable
    {
        public DurableReferenceSnapshotTests.Fixture Work { get; } = new();
        public CoreServer Api { get; }
        public CoreServer Comfy { get; }
        public ControlCenterSession Session { get; }
        public string JournalRecord => Path.Combine(ProductionSubmissionJournal.DefaultRoot,
            ProductionSubmissionJournal.Hash(Work.Plan.ProductionJobId + "\n" + Work.Task.ProductionTaskId) + ".submission.json");
        private readonly CredentialManagerTokenStore _tokens = new("PicotooPet.CI.ShippingReference/" + Guid.NewGuid().ToString("N"));
        private Fixture()
        {
            if (File.Exists(JournalRecord) || new ProductionSubmissionJournal(ProductionSubmissionJournal.DefaultRoot).Pending().Count != 0)
                throw new InvalidOperationException("SHIPPING_PROOF_REQUIRES_EMPTY_DISPOSABLE_JOURNAL");
            Api = new(Work);
            Comfy = new(Work, port: 8188);
            Session = new(_tokens, new(Path.Combine(Work.Root, "settings.json")),
                new SafeFileLogger(Path.Combine(Work.Root, "test.log")),
                new ConnectionStateStore(), new CapabilityStateStore(), new TaskStateStore());
        }
        public static async Task<Fixture> CreateAsync()
        {
            var f = new Fixture();
            try
            {
                await new DesktopSettingsStore(Path.Combine(f.Work.Root, "settings.json"))
                    .SaveAsync(new(f.Api.Url), CancellationToken.None);
                await f.Session.InitializeAsync(CancellationToken.None); // no token: no background connection
                f._tokens.Save("offline-shipping-reference-test-only");
                return f;
            }
            catch { await f.DisposeAsync(); throw; }
        }
        public async ValueTask DisposeAsync()
        {
            await Session.DisposeAsync(); _tokens.Delete();
            await Api.DisposeAsync(); await Comfy.DisposeAsync(); Work.Dispose();
        }
    }

    private sealed class CoreServer : IAsyncDisposable
    {
        private readonly HttpListener _listener = new();
        private readonly Task _loop;
        private readonly DurableReferenceSnapshotTests.Fixture _work;
        private volatile bool _stopping;
        public bool Approved { get; set; } = true;
        public ConcurrentQueue<string> Requests { get; } = new();
        public string Url { get; }
        public CoreServer(DurableReferenceSnapshotTests.Fixture work, int? port = null)
        {
            _work = work;
            var reservation = new TcpListener(IPAddress.Loopback, port ?? 0);
            reservation.Start(); var bound = ((IPEndPoint)reservation.LocalEndpoint).Port; reservation.Stop();
            Url = "http://127.0.0.1:" + bound.ToString(System.Globalization.CultureInfo.InvariantCulture) + "/";
            _listener.Prefixes.Add(Url); _listener.Start(); _loop = ServeAsync();
        }
        private async Task ServeAsync()
        {
            try
            {
                while (_listener.IsListening)
                {
                    var context = await _listener.GetContextAsync();
                    var request = context.Request;
                    var path = request.Url!.AbsolutePath;
                    Requests.Enqueue(request.HttpMethod + " " + path);
                    var reference = _work.Reference;
                    object? body = null;
                    var status = 200;
                    if (request.HttpMethod != "GET" || request.Headers["Authorization"] != "Bearer offline-shipping-reference-test-only") status = 403;
                    else if (path == "/api/v1/production/jobs/job/plan") body = _work.Plan;
                    else if (path == "/api/v1/production/jobs/job") body = new ProductionJobRecord("job", "creative",
                        _work.Plan.CreativePackageDigest, _work.Plan.ProjectKey, _work.Plan.ProductionProfile,
                        _work.Digest, "Ready", null, null, null, null, "fixture",
                        DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
                    else if (path == "/api/v1/production/jobs/job/tasks/task/reference-authorization" && Approved)
                        body = new ProductionReferenceAuthorizationV11Record("reference_authorization.v1", "job", "task", _work.Digest,
                            new(reference.ApprovalId, "shot", reference.AssetId, reference.InputRelativePath, reference.Sha256, reference.Bytes), reference);
                    else if (path != "/api/v1/production/jobs/job/package") status = 409;
                    context.Response.StatusCode = status;
                    context.Response.ContentType = "application/json";
                    var bytes = JsonSerializer.SerializeToUtf8Bytes(body);
                    context.Response.ContentLength64 = bytes.Length;
                    await context.Response.OutputStream.WriteAsync(bytes); context.Response.Close();
                }
            }
            catch (HttpListenerException e) when (_stopping && e.ErrorCode == 995) { }
            catch (ObjectDisposedException) when (_stopping) { }
        }
        public async ValueTask DisposeAsync() { _stopping = true; _listener.Stop(); await _loop; _listener.Close(); }
    }
}
