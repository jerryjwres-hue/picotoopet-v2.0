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

internal static class OperatorTrustedPilotGateTests
{
    internal static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("CI") != "true") throw new InvalidOperationException("CI only");
        var path = P0ThreeShotAcceptanceGate.DefaultPath;
        if (File.Exists(path) || File.Exists(path + ".armed")) throw new InvalidOperationException("requires empty disposable gate");
        using var source = new DurableReferenceSnapshotTests.Fixture();
        const string jobId = "eaad8d1e-4f83-48bd-88f5-3a1d7fa6b352";
        var reference = source.Reference with { ProductionJobId = jobId };
        var task = source.Task with { TargetDurationMs = 4000, FrameCount = 97, ReferenceAsset = reference };
        var plan = source.Plan with { ProductionJobId = jobId, TargetRuntimeMs = 4000, Tasks = [task] };
        await using var server = new CoreServer(() => plan);
        var tokens = new CredentialManagerTokenStore("PicotooPet.CI.PilotGate/" + Guid.NewGuid().ToString("N"));
        await using var logger = new SafeFileLogger(Path.Combine(source.Root, "gate.log"));
        await using var session = new ControlCenterSession(tokens, new(Path.Combine(source.Root, "settings.json")), logger,
            new ConnectionStateStore(), new CapabilityStateStore(), new TaskStateStore());
        await new DesktopSettingsStore(Path.Combine(source.Root, "settings.json")).SaveAsync(new(server.Url), CancellationToken.None);
        await session.InitializeAsync(CancellationToken.None);
        tokens.Save("offline-pilot-gate");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        try
        {
            File.WriteAllText(path, Allow(Digest(plan)));
            RecoveryTests.Assert(await P0ThreeShotAcceptanceGate.AllowsJobAsync(session, jobId, CancellationToken.None),
                "existing exact ALLOW must admit the frozen single four-second v1.1 I2V pilot");
            using (var permit = P0ThreeShotAcceptanceGate.AcquireSubmissionPermit(jobId, Digest(plan)))
                RecoveryTests.Assert(permit is not null, "B requires the real existing permit");
            // A historical v1.0 Goal continuation must not hide the exact new
            // B Job from the existing sole host's already-present job poll.
            var find = typeof(P0MediaWorkerHost).GetMethod("FindExplicitPilotJobAsync", BindingFlags.Static | BindingFlags.NonPublic);
            RecoveryTests.Assert(find is not null, "same EXE host must discover the exact allowed pilot independently of a stale Goal continuation");
            var pilotJob = await session.GetProductionJobAsync(jobId, CancellationToken.None);
            var oldJob = pilotJob with { ProductionJobId = "bbad8d1e-4f83-48bd-88f5-3a1d7fa6b352" };
            var found = await (Task<string?>)find!.Invoke(null, [session, new[] { oldJob, pilotJob }, CancellationToken.None])!;
            RecoveryTests.Assert(found == jobId, "sole host finds only explicitly allowed B Job, not historical row");
            File.WriteAllText(path, Allow(new string('b', 64)));
            RecoveryTests.Assert(!await P0ThreeShotAcceptanceGate.AllowsJobAsync(session, jobId, CancellationToken.None), "wrong digest denies");
            plan = plan with { Tasks = [task with { ReferenceAsset = reference with { ShotId = "wrong" } }] };
            File.WriteAllText(path, Allow(Digest(plan)));
            RecoveryTests.Assert(!await P0ThreeShotAcceptanceGate.AllowsJobAsync(session, jobId, CancellationToken.None), "wrong reference identity denies even with matching digest");
            File.WriteAllText(path, "{\"schema_version\":\"1.0\",\"mode\":\"hold\"}");
            RecoveryTests.Assert(!await P0ThreeShotAcceptanceGate.AllowsJobAsync(session, jobId, CancellationToken.None), "HOLD denies");
            found = await (Task<string?>)find!.Invoke(null, [session, new[] { oldJob, pilotJob }, CancellationToken.None])!;
            RecoveryTests.Assert(found is null, "HOLD blocks host candidate discovery too");
            Console.WriteLine("P0_OPERATOR_TRUSTED_PILOT_EXISTING_GATE=PASS; GPU_POSTS=0");
        }
        finally { tokens.Delete(); File.Delete(path); File.Delete(path + ".armed"); }
        static string Allow(string digest) => JsonSerializer.Serialize(new { schema_version = "1.0", mode = "allow", production_job_id = jobId, plan_digest = digest });
    }
    private static string Digest(ProductionPlanRecord plan) => Convert.ToHexStringLower(SHA256.HashData(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!)));

    private sealed class CoreServer : IAsyncDisposable
    {
        private readonly HttpListener _listener = new();
        private readonly Task _loop;
        private bool _stopping;
        internal string Url { get; }
        internal CoreServer(Func<ProductionPlanRecord> current)
        {
            var socket = new TcpListener(IPAddress.Loopback, 0); socket.Start();
            var port = ((IPEndPoint)socket.LocalEndpoint).Port; socket.Stop();
            Url = "http://127.0.0.1:" + port.ToString(System.Globalization.CultureInfo.InvariantCulture) + "/";
            _listener.Prefixes.Add(Url); _listener.Start();
            _loop = ServeAsync();
            async Task ServeAsync()
            {
                try
                {
                    while (_listener.IsListening)
                    {
                        var context = await _listener.GetContextAsync();
                        var plan = current();
                        var job = new ProductionJobRecord(plan.ProductionJobId, plan.CreativePackageId, plan.CreativePackageDigest,
                            plan.ProjectKey, plan.ProductionProfile, Digest(plan), "Ready", null, null, null, null, "ci", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
                        object body = context.Request.Url!.AbsolutePath.EndsWith("/plan", StringComparison.Ordinal) ? plan : job;
                        context.Response.ContentType = "application/json";
                        var bytes = JsonSerializer.SerializeToUtf8Bytes(body); context.Response.ContentLength64 = bytes.Length;
                        await context.Response.OutputStream.WriteAsync(bytes); context.Response.Close();
                    }
                }
                catch (HttpListenerException) when (_stopping) { }
                catch (ObjectDisposedException) when (_stopping) { }
            }
        }
        public async ValueTask DisposeAsync() { _stopping = true; _listener.Stop(); await _loop; _listener.Close(); }
    }
}
