using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.MediaWorker.SmokeTests;

/// <summary>Three real executor task transitions, offline Comfy transport and C004 facade; no real GPU.</summary>
internal static class MultiShotProductionTests
{
    public static async Task RunAsync()
    {
        await RejectNonExecutableBeforePreflightOrLeaseAsync();
        await RejectLegacyUnapprovedI2VBeforeGpuAsync();
        await RejectV11UntilProtectedSnapshotAndKnownPostReadyAsync();
        await RecoverMiddleShotAndAssembleThreeSourcesAsync();
        Console.WriteLine("P0_MULTISHOT_3_SHOTS_REUSE_C004_MP4=PASS (offline fake Comfy/FFmpeg)");
    }

    private static async Task RejectNonExecutableBeforePreflightOrLeaseAsync()
    {
        using var fixture = new Fixture(rejectLateShot: true);
        var preflights = 0;
        await RecoveryTests.ThrowsCodeAsync("PRODUCTION_PLAN_NOT_FULLY_EXECUTABLE",
            () => fixture.Executor(_ => { preflights++; return Ready(fixture.Root); }).RunAsync("job"));
        RecoveryTests.Assert(preflights == 0 && fixture.Gateway.Claims == 0 && fixture.Comfy.Submits == 0,
            "a late NeedsHuman shot must stop the entire multi-shot job before model hash, lease or GPU");
    }

    private static async Task RejectLegacyUnapprovedI2VBeforeGpuAsync()
    {
        using var fixture = new Fixture(rejectLateShot: false, unapprovedReference: true);
        var preflights = 0;
        await RecoveryTests.ThrowsCodeAsync("I2V_REFERENCE_APPROVAL_CONTRACT_REQUIRED",
            () => fixture.Executor(_ => { preflights++; return Ready(fixture.Root); }).RunAsync("job"));
        RecoveryTests.Assert(preflights == 0 && fixture.Gateway.Claims == 0 && fixture.Comfy.Submits == 0,
            "unapproved I2V reference must never reserve a lease or spend GPU");
    }

    private static async Task RejectV11UntilProtectedSnapshotAndKnownPostReadyAsync()
    {
        using (var fixture = new Fixture(rejectLateShot: false, v11: true))
        {
            var preflights = 0;
            await RecoveryTests.ThrowsCodeAsync("I2V_V11_CRASH_DURABLE_SNAPSHOT_REQUIRED",
                () => fixture.Executor(_ => { preflights++; return Ready(fixture.Root); }).RunAsync("job"));
            RecoveryTests.Assert(preflights == 0 && fixture.Gateway.Claims == 0
                && fixture.Gateway.Attempts.All(n => n == 0) && fixture.Comfy.Submits == 0,
                "even exact Core v1.1 identity must not bypass crash-durable LoadImage protection");
        }
        using (var fixture = new Fixture(rejectLateShot: false, v11: true, tamperV11: true))
        {
            var preflights = 0;
            await RecoveryTests.ThrowsCodeAsync("I2V_V11_REFERENCE_IDENTITY_INVALID",
                () => fixture.Executor(_ => { preflights++; return Ready(fixture.Root); }).RunAsync("job"));
            RecoveryTests.Assert(preflights == 0 && fixture.Gateway.Claims == 0 && fixture.Comfy.Submits == 0,
                "wrong v1.1 shot identity must be rejected before GPU POST");
        }
        using (var fixture = new Fixture(rejectLateShot: false, v11: true, wrongCasPath: true))
        {
            await RecoveryTests.ThrowsCodeAsync("I2V_V11_SNAPSHOT_NOT_CONTENT_ADDRESSED",
                () => fixture.Executor(_ => Ready(fixture.Root)).RunAsync("job"));
            RecoveryTests.Assert(fixture.Gateway.Claims == 0 && fixture.Comfy.Submits == 0,
                "unprotected non-CAS reference snapshot must be rejected");
        }
        using (var fixture = new Fixture(rejectLateShot: false, v11: true))
        {
            fixture.Journal.Save(new ProductionSubmission("other-job", "task-other",
                new string('a', 64), new string('b', 64), "Submitting", null));
            await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION",
                () => fixture.Executor(_ => Ready(fixture.Root)).RunAsync("job"));
            RecoveryTests.Assert(fixture.Gateway.Claims == 0 && fixture.Comfy.Submits == 0,
                "unknown other-job POST journal must take precedence over v1.1 GPU admission");
        }
        Console.WriteLine("P0_V11_GPU_POST_ZERO=PASS (offline protected snapshot pending)");
    }

    private static async Task RecoverMiddleShotAndAssembleThreeSourcesAsync()
    {
        using var f = new Fixture(rejectLateShot: false);
        var metrics = new List<ProductionShotObservation>();
        f.Gateway.LoseSecondBindOnce = true;
        try
        {
            await f.Executor(_ => Ready(f.Root), metrics.Add).RunAsync("job");
            throw new InvalidOperationException("Expected Core bind response loss");
        }
        catch (HttpRequestException) { }

        RecoveryTests.Assert(f.Comfy.Submits == 2 && f.Gateway.Completed == 1,
            "first shot must persist, second accepted prompt must be journaled on lost Core ack");
        RecoveryTests.Assert(f.Journal.Pending().Single().PromptId == "prompt-2",
            "lost response must preserve exact second prompt for recovery");
        var package = await f.Executor(_ => Ready(f.Root), metrics.Add).RunAsync("job");
        RecoveryTests.Assert(f.Comfy.Submits == 3 && f.Gateway.Completed == 3 && f.Gateway.Attempts.All(x => x == 1),
            "recovery must reuse two prior prompt outcomes and render only missing shot");
        RecoveryTests.Assert(package.Manifest.GetProperty("outputs").GetArrayLength() == 3
            && metrics.Count(x => x.ResultCode == "CORE_COMMITTED") == 3
            && metrics.Any(x => x.ResultCode == "REUSED_CORE_SUCCEEDED")
            && metrics.Any(x => x.KnownPromptAtClaim && x.ResultCode == "CORE_COMMITTED")
            && metrics.Any(x => x.ResultCode == "TRANSPORT_UNCERTAIN"),
            "three-shot Core result and per-shot time/reuse observations must survive restart");
        RecoveryTests.Assert(metrics.All(x => x.WallElapsedMs >= 0), "negative wall-clock metric");

        var ffmpeg = new OfflineAssembler();
        var c004 = new FinalVideoAssemblyService(new PackageGateway(package), ffmpeg,
            f.Root, Path.Combine(f.Root, "final"), TimeProvider.System);
        var completed = await c004.AssembleAsync("job");
        RecoveryTests.Assert(ffmpeg.Inputs?.Select(Path.GetFileName)
            .SequenceEqual(["shot-1.webm", "shot-2.webm", "shot-3.webm"]) == true,
            "C004 must preserve actual Core package 3-shot order");
        RecoveryTests.Assert(File.Exists(completed.FilePath) && completed.FilePath.EndsWith(".mp4", StringComparison.OrdinalIgnoreCase)
            && completed.Sha256.Length == 64 && ffmpeg.Calls == 1,
            "C004 must produce managed content-addressed MP4");
        var reused = await c004.AssembleAsync("job");
        RecoveryTests.Assert(reused.Reused && ffmpeg.Calls == 1 && reused.Sha256 == completed.Sha256,
            "repeated delivery must reuse verified MP4, not repeat source work");
        RecoveryTests.Assert(f.Journal.Pending().Count == 0, "recovered prompts must all be settled");
    }

    private static Task<ProductionPreflightSnapshot> Ready(string root) =>
        Task.FromResult(new ProductionPreflightSnapshot(true, "fake", root, root, root, root, []));

    private sealed class Fixture : IDisposable
    {
        private readonly HttpClient _http;
        public string Root { get; } = Path.Combine(Path.GetTempPath(), "p0-multishot-" + Guid.NewGuid().ToString("N"));
        public ProductionSubmissionJournal Journal { get; }
        public Gateway Gateway { get; }
        public Comfy Comfy { get; }
        public Fixture(bool rejectLateShot, bool unapprovedReference = false,
            bool v11 = false, bool tamperV11 = false, bool wrongCasPath = false)
        {
            Directory.CreateDirectory(Root);
            Journal = new(Path.Combine(Root, "journal"));
            Gateway = new(rejectLateShot, unapprovedReference, v11, tamperV11, wrongCasPath);
            Comfy = new(Root);
            _http = new(Comfy) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        }
        public ProductionExecutionService Executor(
            Func<CancellationToken, Task<ProductionPreflightSnapshot>> preflight,
            Action<ProductionShotObservation>? observe = null) =>
            new(Gateway, new ComfyProductionClient(_http), Journal, new ComfyPromptReconciler(_http),
                preflight, TimeSpan.FromMilliseconds(5), TimeSpan.FromMilliseconds(30),
                TimeSpan.FromSeconds(3), observe);
        public void Dispose()
        {
            _http.Dispose();
            if (Directory.Exists(Root)) Directory.Delete(Root, recursive: true);
        }
    }

    private sealed class Gateway : IProductionExecutionGateway
    {
        private readonly ProductionTaskPlanRecord[] _tasks;
        private readonly int[] _attempts = new int[3];
        private readonly string?[] _prompt = new string?[3];
        private readonly ProductionTaskCommitRequest?[] _results = new ProductionTaskCommitRequest?[3];
        public int[] Attempts => _attempts;
        public int Claims { get; private set; }
        public int Completed => _results.Count(x => x is not null);
        public bool LoseSecondBindOnce { get; set; }

        private readonly bool _v11;
        public Gateway(bool rejectLateShot, bool unapprovedReference,
            bool v11, bool tamperV11, bool wrongCasPath)
        {
            _v11 = v11;
            var sha = new string('a', 64);
            var refPath = wrongCasPath ? "PicotooPet/references/legacy/shot-2.png"
                : "PicotooPet/references/" + sha + "/shot-2.png";
            var reference = new ProductionReferenceAssetV11Record(
                "reference_asset.v1", "core-asset-1", "goal-1", "creative-job-1",
                "creative", "job", "task-2", tamperV11 ? "wrong-shot" : "shot-2",
                sha, refPath, sha, 128, "USER_SUPPLIED", new string('c', 64),
                "wan22.i2v.production.v1", "core-approval-1", new string('d', 64));
            _tasks = Enumerable.Range(1, 3).Select(i => new ProductionTaskPlanRecord(
                "task-" + i, "shot-" + i, i,
                (unapprovedReference || v11) && i == 2 ? "IMAGE_TO_VIDEO" : "GENERATIVE_VIDEO",
                rejectLateShot && i == 3 ? "NeedsHuman" : "Executable",
                rejectLateShot && i == 3 ? null
                    : (unapprovedReference || v11) && i == 2
                        ? "comfy.wan22.ti2v5b.i2v.v1" : "comfy.wan22.ti2v5b.t2v.v1",
                "pet product story scene " + i, "wan22.safe-negative.v1",
                9000 + i, 832, 480, 24, 73, 3000,
                v11 && i == 2 ? refPath : unapprovedReference && i == 2 ? "reference/pet.png" : null,
                v11 && i == 2 ? reference : null)).ToArray();
        }

        private ProductionPlanRecord Plan => new(_v11 ? "1.1" : "1.0", "production.comfyui.v1", "job",
            "creative", new string('a', 64), _v11 ? "goal-goal-1" : "project",
            "video.landscape.v1", 9000, _tasks);
        private ProductionTaskRecord Snapshot(int index) => new(
            _tasks[index].ProductionTaskId, "job", _tasks[index].ShotId, index + 1,
            _tasks[index].RenderIntent, _tasks[index].ExecutionDisposition, _tasks[index].WorkflowId,
            _tasks[index], _results[index] is not null ? "Succeeded" : _attempts[index] > 0 ? "Running" : "Pending",
            _attempts[index], _prompt[index], _results[index]?.OutputRelpath, _results[index]?.OutputSha256,
            _results[index]?.OutputBytes, _results[index]?.MimeType, _results[index]?.Width,
            _results[index]?.Height, _results[index]?.FrameCount, _results[index]?.Fps,
            null, null, DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
        public Task<ProductionPlanRecord> GetProductionPlanAsync(string job, CancellationToken ct) =>
            Task.FromResult(Plan);
        public Task<ProductionClaimRecord> ClaimProductionJobAsync(string job, string executor, CancellationToken ct)
        {
            Claims++;
            return Task.FromResult(new ProductionClaimRecord(job, executor, "lease",
                DateTimeOffset.UtcNow.AddMinutes(2), Plan,
                Enumerable.Range(0, 3).Select(Snapshot).ToArray()));
        }
        public Task<ProductionJobRecord> HeartbeatProductionJobAsync(string j, string e, string l, CancellationToken ct) =>
            Task.FromResult<ProductionJobRecord>(null!);
        public Task<ProductionTaskRecord> MarkProductionAttemptAsync(string job, string task,
            ProductionTaskAttemptRequest request, CancellationToken ct)
        {
            var i = Array.FindIndex(_tasks, t => t.ProductionTaskId == task);
            RecoveryTests.Assert(i >= 0 && request.LeaseToken == "lease", "unknown task/lease");
            if (request.ComfyPromptId is null) _attempts[i]++;
            else
            {
                _prompt[i] = request.ComfyPromptId;
                if (i == 1 && LoseSecondBindOnce)
                {
                    LoseSecondBindOnce = false;
                    throw new HttpRequestException("Core returned no binding acknowledgement");
                }
            }
            return Task.FromResult(Snapshot(i));
        }
        public Task<ProductionTaskRecord> CommitProductionResultAsync(string job, string task,
            ProductionTaskCommitRequest request, CancellationToken ct)
        {
            var i = Array.FindIndex(_tasks, t => t.ProductionTaskId == task);
            RecoveryTests.Assert(i >= 0 && request.ComfyPromptId == _prompt[i], "wrong committed prompt");
            _results[i] = request;
            return Task.FromResult(Snapshot(i));
        }
        public Task<ProductionTaskRecord> FailProductionTaskAsync(string j, string t,
            ProductionTaskFailureRequest req, CancellationToken ct) =>
            throw new InvalidOperationException("no fake Comfy failure expected");
        public Task<ProductionPackageRecord?> GetProductionPackageAsync(string job, CancellationToken ct)
        {
            if (Completed != 3) return Task.FromResult<ProductionPackageRecord?>(null);
            var manifest = JsonSerializer.SerializeToElement(new
            {
                schema_version = "1.0",
                production_package_id = "package",
                production_job_id = "job",
                outputs = _results.Select(result => new
                {
                    output_relpath = result!.OutputRelpath,
                    output_sha256 = result.OutputSha256,
                    output_bytes = result.OutputBytes,
                    mime_type = result.MimeType,
                    width = result.Width, height = result.Height,
                    frame_count = result.FrameCount, fps = result.Fps,
                }).ToArray()
            });
            return Task.FromResult<ProductionPackageRecord?>(new("package", job, "creative",
                new string('a', 64), new string('b', 64), "package.zip", manifest,
                "PASS", DateTimeOffset.UtcNow));
        }
    }

    private sealed class Comfy(string root) : HttpMessageHandler
    {
        private readonly Dictionary<string, JsonNode> _graphs = new(StringComparer.Ordinal);
        public int Submits { get; private set; }
        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var path = request.RequestUri!.AbsolutePath;
            if (path == "/prompt")
            {
                var graph = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!["prompt"]!.DeepClone();
                var number = ++Submits;
                var id = "prompt-" + number;
                _graphs.Add(id, graph);
                File.WriteAllText(Path.Combine(root, "shot-" + number + ".webm"), "offline-fake-webm-" + number);
                return Json(new JsonObject { ["prompt_id"] = id });
            }
            if (path == "/queue")
                return Json(new JsonObject { ["queue_running"] = new JsonArray(), ["queue_pending"] = new JsonArray() });
            if (path.StartsWith("/history", StringComparison.Ordinal))
            {
                var id = path == "/history" ? null : Uri.UnescapeDataString(path["/history/".Length..]);
                var selected = id is null ? _graphs.Keys : _graphs.Keys.Where(key => key == id);
                var output = new JsonObject();
                foreach (var key in selected)
                {
                    var number = int.Parse(key["prompt-".Length..], System.Globalization.CultureInfo.InvariantCulture);
                    var tuple = new JsonArray(JsonValue.Create(1), JsonValue.Create(key), _graphs[key].DeepClone(),
                        new JsonObject(), new JsonArray());
                    output[key] = new JsonObject
                    {
                        ["prompt"] = tuple,
                        ["status"] = new JsonObject { ["completed"] = true, ["status_str"] = "success" },
                        ["outputs"] = new JsonObject
                        {
                            ["save"] = new JsonObject { ["images"] = new JsonArray(new JsonObject
                                { ["filename"] = "shot-" + number + ".webm",
                                  ["subfolder"] = "", ["type"] = "output" }) }
                        }
                    };
                }
                return Json(output);
            }
            throw new InvalidOperationException("Unexpected fake endpoint " + path);
        }
        private static HttpResponseMessage Json(JsonObject body) =>
            new(HttpStatusCode.OK) { Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json") };
    }

    private sealed class PackageGateway(ProductionPackageRecord package) : IProductionPackageGateway
    {
        public Task<ProductionPackageRecord?> GetProductionPackageAsync(string job, CancellationToken ct) =>
            Task.FromResult<ProductionPackageRecord?>(package);
    }

    private sealed class OfflineAssembler : IFinalVideoFfmpeg
    {
        public IReadOnlyList<string>? Inputs { get; private set; }
        public int Calls { get; private set; }
        public Task AssembleAsync(IReadOnlyList<string> sources, string output, int width,
            int height, int fps, CancellationToken ct)
        {
            Calls++;
            Inputs = sources.ToArray();
            File.WriteAllText(output, "OFFLINE_FAKE_MP4");
            return Task.CompletedTask;
        }
    }
}
