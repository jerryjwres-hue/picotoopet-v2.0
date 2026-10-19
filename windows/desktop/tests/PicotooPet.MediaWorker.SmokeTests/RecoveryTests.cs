using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.MediaWorker.SmokeTests;

/// <summary>实际 executor/client/journal + 假 HTTP；没有模型加载或 GPU 调用。</summary>
internal static class RecoveryTests
{
    public static async Task RunAsync()
    {
        using var f = new Fixture();
        f.Comfy.LoseSubmitResponse = true;
        await ThrowsAsync<HttpRequestException>(() => f.Executor().RunAsync("job"));
        Assert(f.Journal.Pending().Single().Phase == "Submitting", "uncertain submit durable before POST");
        await f.Executor().RunAsync("job");
        Assert(f.Comfy.Submits == 1 && f.Gateway.Reservations == 1 && f.Gateway.Commits == 1, "restart reconciles one exact prompt, never duplicate submit/reserve");
        await f.Executor().RunAsync("job");
        Assert(f.Comfy.Submits == 1, "completed output never rerendered");

        using var unknown = new Fixture();
        unknown.Comfy.LoseSubmitResponse = true;
        await ThrowsAsync<HttpRequestException>(() => unknown.Executor().RunAsync("job"));
        unknown.Comfy.ForgetPrompt = true;
        await ThrowsCodeAsync("MEDIA_SUBMISSION_UNKNOWN", () => unknown.Executor().RunAsync("job"));
        Assert(unknown.Comfy.Submits == 1, "history eviction must not trigger blind retry");

        using var binding = new Fixture();
        binding.Gateway.LoseBindResponse = true;
        await ThrowsAsync<HttpRequestException>(() => binding.Executor().RunAsync("job"));
        await binding.Executor().RunAsync("job");
        Assert(binding.Comfy.Submits == 1 && binding.Gateway.Reservations == 1, "lost Core bind response idempotent");

        using var pending = new Fixture();
        pending.Comfy.HoldOutput = true;
        using var stop = new CancellationTokenSource();
        var active = pending.Executor().RunAsync("job", stop.Token);
        await pending.Comfy.Started.Task.WaitAsync(TimeSpan.FromSeconds(5));
        await ThrowsCodeAsync("MEDIA_WORKER_BUSY", () => pending.Executor().RunAsync("other"));
        await Task.Delay(80);
        Assert(pending.Gateway.Heartbeats > 0, "lease heartbeat independent of GPU history latency");
        stop.Cancel(); await ThrowsAsync<OperationCanceledException>(() => active);
        await ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => pending.Executor().RunAsync("other"));
        Assert(pending.Journal.Pending().Single().PromptId == "prompt-1", "explicit stop preserves recoverable prompt");
        pending.Comfy.HoldOutput = false;
        await pending.Executor().RunAsync("job");
        Assert(pending.Comfy.Submits == 1, "explicit stop and worker restart resume known GPU work");
        Console.WriteLine("MEDIA_WORKER_RECOVERY_SINGLE_GPU=PASS");
    }
    internal static void Assert(bool ok, string message) { if (!ok) throw new InvalidOperationException(message); }
    internal static async Task ThrowsAsync<T>(Func<Task> action) where T : Exception
    {
        try { await action(); } catch (T) { return; }
        throw new InvalidOperationException("Expected " + typeof(T).Name);
    }
    internal static async Task ThrowsCodeAsync(string code, Func<Task> action)
    {
        try { await action(); } catch (ProductionWorkerException e) when (e.Code == code) { return; }
        throw new InvalidOperationException("Expected " + code);
    }
    internal sealed class Fixture : IDisposable
    {
        public string Root { get; } = Path.Combine(Path.GetTempPath(), "p0-worker-" + Guid.NewGuid().ToString("N"));
        public ProductionSubmissionJournal Journal { get; }
        public FakeGateway Gateway { get; } = new();
        public FakeComfy Comfy { get; } = new();
        private readonly HttpClient _http;
        public Fixture()
        {
            Directory.CreateDirectory(Root);
            File.WriteAllText(Path.Combine(Root, "clip.webm"), "fake offline media bytes");
            Journal = new(Path.Combine(Root, "journal"));
            _http = new(Comfy) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        }
        public ProductionExecutionService Executor() => new(Gateway, new ComfyProductionClient(_http), Journal,
            new ComfyPromptReconciler(_http), _ => Task.FromResult(new ProductionPreflightSnapshot(true, "fake", Root, Root, Root, Root, [])),
            TimeSpan.FromMilliseconds(5), TimeSpan.FromMilliseconds(20));
        public void Dispose() { _http.Dispose(); Directory.Delete(Root, true); }
    }
    internal sealed class FakeComfy : HttpMessageHandler
    {
        public bool LoseSubmitResponse { get; set; }
        public bool ForgetPrompt { get; set; }
        public bool HoldOutput { get; set; }
        public int Submits { get; private set; }
        public TaskCompletionSource Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private JsonNode? _graph;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var path = request.RequestUri!.AbsolutePath;
            if (path == "/prompt")
            {
                Submits++; _graph = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!["prompt"]!.DeepClone();
                Started.TrySetResult();
                if (LoseSubmitResponse) { LoseSubmitResponse = false; throw new HttpRequestException("response lost after accepted"); }
                return Json("{\"prompt_id\":\"prompt-1\"}");
            }
            if (path == "/queue") return Json(new JsonObject { ["queue_running"] = HoldOutput ? new JsonArray(Tuple()) : new JsonArray(), ["queue_pending"] = new JsonArray() }.ToJsonString());
            if (path.StartsWith("/history", StringComparison.Ordinal))
            {
                if (ForgetPrompt || HoldOutput) return Json("{}");
                return Json(new JsonObject { ["prompt-1"] = new JsonObject { ["prompt"] = Tuple(),
                    ["status"] = new JsonObject { ["status_str"] = "success", ["completed"] = true },
                    ["outputs"] = new JsonObject { ["save"] = new JsonObject { ["images"] = new JsonArray(new JsonObject { ["filename"] = "clip.webm", ["subfolder"] = "", ["type"] = "output" }) } } } }.ToJsonString());
            }
            throw new InvalidOperationException("Unexpected GPU endpoint " + path);
        }
        private JsonArray Tuple() => new(JsonValue.Create(1), JsonValue.Create("prompt-1"), _graph?.DeepClone(), new JsonObject(), new JsonArray());
        private static HttpResponseMessage Json(string json) => new(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
    }
    internal sealed class FakeGateway : IProductionExecutionGateway
    {
        public int Reservations { get; private set; }
        public int Commits { get; private set; }
        public int Heartbeats { get; private set; }
        public bool LoseBindResponse { get; set; }
        private string? _prompt;
        private bool _succeeded;
        private static ProductionTaskPlanRecord TaskPlan => new("task", "shot", 1, "GENERATIVE_VIDEO", "Executable", "comfy.wan22.ti2v5b.t2v.v1", "product demonstration", "wan22.safe-negative.v1", 1001, 832, 480, 24, 73, 3000, null);
        private static ProductionPlanRecord Plan => new("1.0", "production.comfyui.v1", "job", "creative", new string('a', 64), "project", "video.landscape.v1", 3000, [TaskPlan]);
        private ProductionTaskRecord Snapshot => new("task", "job", "shot", 1, TaskPlan.RenderIntent, "Executable", TaskPlan.WorkflowId, TaskPlan,
            _succeeded ? "Succeeded" : Reservations > 0 ? "Running" : "Pending", Reservations, _prompt,
            null, null, null, null, null, null, null, null, null, null, DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
        public Task<ProductionPlanRecord> GetProductionPlanAsync(string job, CancellationToken ct) => Task.FromResult(Plan);
        public Task<ProductionClaimRecord> ClaimProductionJobAsync(string job, string executor, CancellationToken ct) => Task.FromResult(new ProductionClaimRecord(job, executor, "lease", DateTimeOffset.UtcNow.AddMinutes(2), Plan, [Snapshot]));
        public Task<ProductionJobRecord> HeartbeatProductionJobAsync(string job, string executor, string lease, CancellationToken ct) { Heartbeats++; return Task.FromResult<ProductionJobRecord>(null!); }
        public Task<ProductionTaskRecord> MarkProductionAttemptAsync(string job, string task, ProductionTaskAttemptRequest request, CancellationToken ct)
        {
            if (request.ComfyPromptId is null) { Assert(_prompt is null, "must not reserve again after bound attempt"); Reservations = 1; }
            else { _prompt = request.ComfyPromptId; if (LoseBindResponse) { LoseBindResponse = false; throw new HttpRequestException("bind response lost"); } }
            return Task.FromResult(Snapshot);
        }
        public Task<ProductionTaskRecord> CommitProductionResultAsync(string job, string task, ProductionTaskCommitRequest request, CancellationToken ct)
        { Assert(request.ComfyPromptId == _prompt && request.OutputSha256.Length == 64 && request.OutputBytes > 0, "Core evidence"); Commits++; _succeeded = true; return Task.FromResult(Snapshot); }
        public Task<ProductionTaskRecord> FailProductionTaskAsync(string job, string task, ProductionTaskFailureRequest request, CancellationToken ct) => throw new InvalidOperationException("network uncertainty must not fabricate render failure");
        public Task<ProductionPackageRecord?> GetProductionPackageAsync(string job, CancellationToken ct) => Task.FromResult<ProductionPackageRecord?>(_succeeded ? new("package", job, "creative", new string('a',64), new string('b',64), "", default, "PASS", DateTimeOffset.UtcNow) : null);
    }
}
