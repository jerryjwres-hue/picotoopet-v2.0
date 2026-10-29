using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class I2VExecutorSnapshotTests
{
    public static async Task RunAsync()
    {
        await ShippingAndOperatorGatesAsync();
        await RestartAtSubmissionStagesAsync();
        await UncertainQueueAndBudgetAsync();
        await RevokedBetweenClaimAndPostAsync();
        await TamperAndConcurrentWorkerAsync();
        using var f = new Fixture();
        await f.Executor().RunAsync("job");
        RecoveryTests.Assert(f.Transport.Posts == 1 && f.Attempts == 1 && f.Committed,
            "approved frozen v1.1 must reach exactly one FAKE Comfy POST and Core commit");
        RecoveryTests.Assert(f.Reference.Journal.Pending().Count == 0,
            "terminal fake history + Core commit must settle existing journal");
        Console.WriteLine("P0_Q2_APPROVED_I2V_FAKE_POST=PASS (real I2V remains disarmed)");
    }

    private static async Task ShippingAndOperatorGatesAsync()
    {
        using (var f = new Fixture())
        {
            await RecoveryTests.ThrowsCodeAsync("I2V_V11_CRASH_DURABLE_SNAPSHOT_REQUIRED",
                () => f.Executor(armed: false).RunAsync("job"));
            RecoveryTests.Assert(f.Claims == 0 && f.Attempts == 0 && f.Transport.Posts == 0,
                "shipping constructors cannot arm real I2V");
        }
        using (var f = new Fixture())
        {
            await RecoveryTests.ThrowsCodeAsync("P0_THREE_SHOT_ACCEPTANCE_HELD",
                () => f.Executor(admission: (_, _) => Task.FromResult(false)).RunAsync("job"));
            RecoveryTests.Assert(f.Claims == 0 && f.Attempts == 0 && f.Transport.Posts == 0,
                "HOLD must stop I2V before lease or POST");
        }
        using (var f = new Fixture())
        {
            var permits = 0;
            await RecoveryTests.ThrowsCodeAsync("P0_THREE_SHOT_ACCEPTANCE_HELD",
                () => f.Executor(permit: (_, _) => ++permits == 1 ? null
                    : throw new ProductionWorkerException("P0_THREE_SHOT_ACCEPTANCE_HELD")).RunAsync("job"));
            RecoveryTests.Assert(f.Claims == 1 && f.Attempts == 0 && f.Transport.Posts == 0,
                "HOLD after claim must stop I2V reservation and POST");
        }
    }

    private static async Task RestartAtSubmissionStagesAsync()
    {
        foreach (var stage in new[] { "reservation", "post", "binding" })
        {
            using var f = new Fixture
            {
                LoseReservation = stage == "reservation", LoseBind = stage == "binding",
            };
            f.Transport.LosePostAck = stage == "post";
            try { await f.Executor().RunAsync("job"); throw new InvalidOperationException("loss was not injected"); }
            catch (HttpRequestException) { }
            var relative = ProductionReferenceSnapshotStore.RelativePathFor(f.Reference.Task, f.Reference.Digest);
            RecoveryTests.Assert(File.Exists(f.Reference.Full(relative)), "snapshot must outlive interrupted invocation");
            if (stage == "reservation")
            {
                await RecoveryTests.ThrowsCodeAsync("MEDIA_SUBMISSION_UNKNOWN", () => f.Executor().RunAsync("job"));
                RecoveryTests.Assert(f.Transport.Posts == 0 && f.Attempts == 1,
                    "lost reservation cannot authorize a blind GPU POST or second attempt");
            }
            else
            {
                await f.Executor().RunAsync("job");
                RecoveryTests.Assert(f.Transport.Posts == 1 && f.Attempts == 1 && f.Committed,
                    "lost POST/binding ack must reconcile exact journal graph, never duplicate GPU");
            }
        }
    }

    private static async Task UncertainQueueAndBudgetAsync()
    {
        using (var f = new Fixture())
        {
            f.Transport.Pending = true;
            await RecoveryTests.ThrowsCodeAsync("COMFY_HISTORY_TIMEOUT", () => f.Executor().RunAsync("job"));
            await RecoveryTests.ThrowsCodeAsync("COMFY_HISTORY_TIMEOUT", () => f.Executor().RunAsync("job"));
            RecoveryTests.Assert(f.Transport.Posts == 1 && f.Attempts == 1 && !f.Committed,
                "pending LoadImage must retain snapshot and prompt, never POST twice");
            f.Transport.Pending = false;
            await f.Executor().RunAsync("job");
            RecoveryTests.Assert(f.Transport.Posts == 1 && f.Committed, "terminal history must reuse pending prompt");
        }
        using (var f = new Fixture())
        {
            f.Transport.LosePostAck = true;
            try { await f.Executor().RunAsync("job"); }
            catch (HttpRequestException) { }
            f.Transport.Unknown = true;
            await RecoveryTests.ThrowsCodeAsync("MEDIA_SUBMISSION_UNKNOWN", () => f.Executor().RunAsync("job"));
            RecoveryTests.Assert(f.Transport.Posts == 1 && f.Reference.Journal.Pending().Count == 1,
                "lost old prompt/history must not erase snapshot or GPU uncertainty");
        }
        using (var f = new Fixture())
        {
            f.SetAttemptCount(2);
            await RecoveryTests.ThrowsCodeAsync("MEDIA_SUBMISSION_UNKNOWN", () => f.Executor().RunAsync("job"));
            RecoveryTests.Assert(f.Transport.Posts == 0 && f.Attempts == 2,
                "attempt ceiling cannot be bypassed by a fresh snapshot");
        }
    }

    private static async Task RevokedBetweenClaimAndPostAsync()
    {
        using var f = new Fixture();
        var permits = 0;
        await RecoveryTests.ThrowsCodeAsync("I2V_REFERENCE_APPROVAL_REQUIRED", () => f.Executor(
            permit: (_, _) => { if (++permits == 2) f.Reference.Approved = false; return null; }).RunAsync("job"));
        RecoveryTests.Assert(f.Claims == 1 && f.Attempts == 0 && f.Transport.Posts == 0,
            "current rights must be rechecked at exact POST boundary");
    }

    private static async Task TamperAndConcurrentWorkerAsync()
    {
        using (var f = new Fixture())
        {
            using var otherWorker = f.Reference.Journal.AcquireGpu();
            await RecoveryTests.ThrowsCodeAsync("MEDIA_WORKER_BUSY", () => f.Executor().RunAsync("job"));
            RecoveryTests.Assert(f.Claims == 0 && f.Transport.Posts == 0,
                "GUI/Worker must use existing single GPU exclusion");
        }
        using (var f = new Fixture())
        {
            f.Reference.Journal.Save(new("other-job", "other-task", new string('a', 64), new string('b', 64), "Submitting", null));
            await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => f.Executor().RunAsync("job"));
            RecoveryTests.Assert(f.Claims == 0 && f.Transport.Posts == 0,
                "new I2V cannot displace another unknown old prompt");
        }
        using (var f = new Fixture())
        {
            f.Transport.LosePostAck = true;
            try { await f.Executor().RunAsync("job"); }
            catch (HttpRequestException) { }
            var relative = ProductionReferenceSnapshotStore.RelativePathFor(f.Reference.Task, f.Reference.Digest);
            var path = f.Reference.Full(relative);
            DurableReferenceSnapshotTests.RemoveDenial(new FileInfo(path));
            File.WriteAllText(path, "tampered private snapshot");
            await DurableReferenceSnapshotTests.DeniedAsync(() => f.Executor().RunAsync("job"));
            RecoveryTests.Assert(f.Transport.Posts == 1 && f.Attempts == 1 && !f.Committed
                && f.Reference.Journal.Pending().Single().Phase == "Submitting",
                "tampered queued snapshot cannot be repaired, committed or blindly resubmitted");
        }
    }

    internal sealed class Fixture : IProductionExecutionGateway, IDisposable
    {
        public DurableReferenceSnapshotTests.Fixture Reference { get; } = new();
        public Transport Transport { get; }
        private readonly HttpClient _http;
        public int Attempts { get; private set; }
        public int Claims { get; private set; }
        public bool Committed { get; private set; }
        public string? PromptId { get; private set; }
        public bool LoseBind { get; set; }
        public bool LoseReservation { get; set; }
        public void SetAttemptCount(int count) => Attempts = count;
        public Fixture()
        {
            Transport = new(Reference);
            _http = new(Transport) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        }
        public ProductionExecutionService Executor(bool armed = true,
            Func<string, string, IDisposable?>? permit = null,
            Func<string, CancellationToken, Task<bool>>? admission = null) =>
            new(this, new ComfyProductionClient(_http), Reference.Journal, new ComfyPromptReconciler(_http),
                _ => Task.FromResult(new ProductionPreflightSnapshot(true, "fake", Reference.Root,
                    Reference.Root, Reference.Root, Reference.Root, [])),
                TimeSpan.FromMilliseconds(1), TimeSpan.FromSeconds(1), TimeSpan.FromMilliseconds(30),
                submissionPermit: permit, acceptanceAdmission: admission)
            { ReferenceSnapshots = armed ? Reference.Store() : null };
        public Task<ProductionPlanRecord> GetProductionPlanAsync(string j, CancellationToken ct) => Task.FromResult(Reference.Plan);
        public Task<ProductionPackageRecord?> GetProductionPackageAsync(string j, CancellationToken ct) =>
            Task.FromResult<ProductionPackageRecord?>(Committed ? new("package", "job", "creative", Reference.Digest,
                new string('b', 64), "test.zip", JsonSerializer.SerializeToElement(new { }), "PASS", DateTimeOffset.UtcNow) : null);
        public Task<ProductionClaimRecord> ClaimProductionJobAsync(string j, string e, CancellationToken ct)
        {
            Claims++;
            return Task.FromResult(new ProductionClaimRecord("job", e, "lease", DateTimeOffset.UtcNow.AddMinutes(2),
                Reference.Plan, [Snapshot()]));
        }
        private ProductionTaskRecord Snapshot() => new("task", "job", "shot", 1, "IMAGE_TO_VIDEO", "Executable",
            Reference.Task.WorkflowId, Reference.Task, Committed ? "Succeeded" : Attempts > 0 ? "Running" : "Pending",
            Attempts, PromptId, null, null, null, null, null, null, null, null, null, null,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
        public Task<ProductionJobRecord> HeartbeatProductionJobAsync(string j, string e, string l, CancellationToken ct) =>
            Task.FromResult<ProductionJobRecord>(null!);
        public Task<ProductionTaskRecord> MarkProductionAttemptAsync(string j, string t, ProductionTaskAttemptRequest r, CancellationToken ct)
        {
            if (r.ComfyPromptId is null)
            {
                Attempts++;
                if (LoseReservation) { LoseReservation = false; throw new HttpRequestException("lost reservation ack"); }
            }
            else
            {
                PromptId = r.ComfyPromptId;
                if (LoseBind) { LoseBind = false; throw new HttpRequestException("lost binding ack"); }
            }
            return Task.FromResult(Snapshot());
        }
        public Task<ProductionTaskRecord> CommitProductionResultAsync(string j, string t, ProductionTaskCommitRequest r, CancellationToken ct)
        {
            RecoveryTests.Assert(r.ComfyPromptId == PromptId, "Core commit must bind exact fake prompt");
            Committed = true;
            return Task.FromResult(Snapshot());
        }
        public Task<ProductionTaskRecord> FailProductionTaskAsync(string j, string t, ProductionTaskFailureRequest r, CancellationToken ct) =>
            throw new InvalidOperationException("uncertainty must not invent terminal Core failure");
        public void Dispose() { _http.Dispose(); Reference.Dispose(); }
    }

    internal sealed class Transport(DurableReferenceSnapshotTests.Fixture f) : HttpMessageHandler
    {
        public int Posts { get; private set; }
        public bool LosePostAck { get; set; }
        public bool Pending { get; set; }
        public bool Unknown { get; set; }
        public string? PrivatePath { get; private set; }
        private JsonNode? _graph;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            var path = request.RequestUri!.AbsolutePath;
            if (path == "/prompt")
            {
                RecoveryTests.Assert(request.Method == HttpMethod.Post, "only fake Comfy can receive POST");
                Posts++;
                _graph = JsonNode.Parse(await request.Content!.ReadAsStringAsync(ct))!["prompt"]!.DeepClone();
                PrivatePath = _graph.AsObject().Single(n => n.Value?["class_type"]?.GetValue<string>() == "LoadImage")
                    .Value!["inputs"]!["image"]!.GetValue<string>();
                RecoveryTests.Assert(PrivatePath != f.Reference.InputRelativePath
                    && File.ReadAllBytes(f.Full(PrivatePath)).SequenceEqual(f.Bytes), "POST must read private exact approved bytes");
                File.WriteAllText(Path.Combine(f.Root, "result.webm"), "offline-webm");
                if (LosePostAck) { LosePostAck = false; throw new HttpRequestException("lost Comfy POST ack"); }
                return Json(new JsonObject { ["prompt_id"] = "prompt" });
            }
            var tuple = new JsonArray(JsonValue.Create(1), JsonValue.Create("prompt"), _graph?.DeepClone(), new JsonObject(), new JsonArray());
            if (path == "/queue") return Json(new JsonObject
            {
                ["queue_running"] = new JsonArray(),
                ["queue_pending"] = Pending && _graph is not null ? new JsonArray(tuple) : new JsonArray(),
            });
            if (path.StartsWith("/history", StringComparison.Ordinal))
            {
                if (_graph is null || Unknown || Pending) return Json(new JsonObject());
                return Json(new JsonObject { ["prompt"] = new JsonObject
                {
                    ["prompt"] = tuple,
                    ["status"] = new JsonObject { ["completed"] = true, ["status_str"] = "success" },
                    ["outputs"] = new JsonObject { ["save"] = new JsonObject { ["images"] = new JsonArray(
                        new JsonObject { ["filename"] = "result.webm", ["subfolder"] = "", ["type"] = "output" }) } },
                } });
            }
            throw new InvalidOperationException("unexpected fake endpoint: " + path);
        }
        private static HttpResponseMessage Json(JsonObject data) => new(HttpStatusCode.OK)
        { Content = new StringContent(data.ToJsonString(), Encoding.UTF8, "application/json") };
    }
}
