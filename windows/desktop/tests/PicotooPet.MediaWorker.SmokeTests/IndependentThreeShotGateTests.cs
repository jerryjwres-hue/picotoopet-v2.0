using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
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

// Independent acceptance tests, NOT a second scheduler/executor. All external GPU transport is fake.
// Plan: characterize the untouched default, couple real gate+executor, then exercise durable recovery.
internal static class IndependentThreeShotGateTests
{
    private const string JobId = "eaad8d1e-4f83-48bd-88f5-3a1d7fa6b352";
    private const string OtherJob = "41dd22a4-b738-4931-9c62-55a2a4789690";
    private const string HeldCode = "P0_THREE_SHOT_ACCEPTANCE_HELD";
    private const string Hold = "{\"schema_version\":\"1.0\",\"mode\":\"hold\"}";
    private static string GatePath => P0ThreeShotAcceptanceGate.DefaultPath;
    private static readonly List<string> Failures = new();

    public static async Task RunAsync()
    {
        RequireDisposableRunner();
        // Never overwrite a pre-existing acceptance config or marker, even on CI.
        if (File.Exists(GatePath) || File.Exists(GatePath + ".armed"))
            throw new InvalidOperationException("INDEPENDENT_GATE_REQUIRES_EMPTY_DISPOSABLE_RUNNER");
        Directory.CreateDirectory(Path.GetDirectoryName(GatePath)!);
        try
        {
            await CaseAsync("default_unattended_unchanged", DefaultAsync);
            await CaseAsync("hold_real_admission_zero_side_effects", HoldAsync);
            await CaseAsync("allow_exact_frozen_three_t2v", AllowAsync);
            await CaseAsync("config_corruption_replacement_restart", ConfigurationAsync);
            await CaseAsync("hold_after_preflight_zero_claim", ChangedBeforeClaimAsync);
            await CaseAsync("hold_after_shot_one_no_new_attempt", ChangedBetweenShotsAsync);
            await CaseAsync("journal_unknown_post_precedes_new_job", RecoveryAsync);
            await PlanCasesAsync();
            await CoreIdentityCasesAsync();
            if (Failures.Count != 0)
                throw new InvalidOperationException("INDEPENDENT_THREE_SHOT_GATE=FAIL: " + string.Join("; ", Failures));
            Console.WriteLine("INDEPENDENT_THREE_SHOT_GATE=PASS; REAL_COMFY_GPU=UNVERIFIED; GPU_NETWORK=0");
        }
        finally
        {
            File.Delete(GatePath);
            File.Delete(GatePath + ".armed");
        }
    }

    private static void RequireDisposableRunner()
    {
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("GITHUB_ACTIONS") != "true")
            throw new InvalidOperationException("CI_ONLY_NO_USER_DEVICE_ACTIONS");
    }

    private static async Task CaseAsync(string name, Func<Task> test)
    {
        try { await test(); Console.WriteLine("GATE_CASE " + name + "=PASS"); }
        catch (Exception error)
        {
            Failures.Add(name);
            Console.Error.WriteLine("GATE_CASE " + name + "=FAIL " + error);
        }
    }

    private static async Task DefaultAsync()
    {
        await using var f = await Fixture.CreateAsync();
        await using var executor = f.Executor();
        await executor.RunAsync(JobId);
        RecoveryTests.Assert(f.Work.Gateway.Claims == 1 && f.Work.Comfy.Submits == 3
            && f.Work.Gateway.Attempts.All(x => x == 1), "never-armed default must retain three-shot unattended execution");
        RecoveryTests.Assert(!File.Exists(GatePath + ".armed") && f.Api.Requests.Count == 0,
            "default must not arm or add Core admission calls");
    }

    private static async Task HoldAsync()
    {
        Write(Hold);
        await using var f = await Fixture.CreateAsync();
        await RecoveryTests.ThrowsCodeAsync(HeldCode, () => f.Executor().RunAsync(JobId));
        f.AssertZero();
        RecoveryTests.Assert(f.Api.Requests.Count == 0 && f.Preflights == 0,
            "HOLD must reject before Core reads, preflight, claim, attempt and POST");
    }

    private static async Task AllowAsync()
    {
        await using var f = await Fixture.CreateAsync();
        Write(Allow(JobId, Digest(f.Work.Gateway.Plan)));
        f.Work.Gateway.OnClaim = () =>
        {
            AssertLocked(() => File.WriteAllText(GatePath, Hold));
            AssertLocked(() => File.Move(GatePath, GatePath + ".moved"));
            AssertLocked(() => File.Delete(GatePath));
        };
        await using var executor = f.Executor();
        await executor.RunAsync(JobId);
        await executor.RunAsync(JobId);
        RecoveryTests.Assert(f.Work.Gateway.Claims == 1 && f.Work.Comfy.Submits == 3
            && f.Work.Gateway.Attempts.All(x => x == 1) && f.Work.Gateway.Completed == 3,
            "exact ALLOW must complete precisely three tasks and reuse the package on repeated run");
        RecoveryTests.Assert(f.Api.Requests.All(x => x is "GET /api/v1/production/jobs/" + JobId
            or "GET /api/v1/production/jobs/" + JobId + "/plan"), "admission must only read the exact frozen job/plan");
    }

    private static async Task ConfigurationAsync()
    {
        await using var f = await Fixture.CreateAsync();
        var digest = Digest(f.Work.Gateway.Plan);
        foreach (var invalid in new[] { "", "{broken", "[]", "null", Hold,
            Allow(OtherJob, digest), Allow(JobId, new string('b', 64)),
            Allow(JobId, digest).Replace("\"1.0\"", "\"2.0\"", StringComparison.Ordinal),
            Allow(JobId, digest)[..^1] + ",\"unexpected\":true}", new string('x', 513) })
        {
            Write(invalid);
            await RecoveryTests.ThrowsCodeAsync(HeldCode, () => f.Executor().RunAsync(JobId));
            f.AssertZero();
        }
        Write(Allow(JobId, digest));
        using (var permit = P0ThreeShotAcceptanceGate.AcquireSubmissionPermit(JobId, digest))
            RecoveryTests.Assert(permit is not null, "valid config must be observed and armed");
        File.Delete(GatePath);
        await ProbeChildAsync("held", digest);
        await RecoveryTests.ThrowsCodeAsync(HeldCode, () => f.Executor().RunAsync(JobId));
        Write(Allow(OtherJob, digest));
        await ProbeChildAsync("held", digest);
        Write(Allow(JobId, digest));
        await ProbeChildAsync("allowed", digest);
        Write(Hold);
        await ProbeChildAsync("held", digest);
        f.AssertZero();
    }

    private static async Task ChangedBeforeClaimAsync()
    {
        await using var f = await Fixture.CreateAsync();
        Write(Allow(JobId, Digest(f.Work.Gateway.Plan)));
        f.DuringPreflight = () => Write(Hold);
        await RecoveryTests.ThrowsCodeAsync(HeldCode, () => f.Executor().RunAsync(JobId));
        RecoveryTests.Assert(f.Preflights == 1, "test must cross the slow preflight boundary");
        f.AssertZero();
    }

    private static async Task ChangedBetweenShotsAsync()
    {
        await using var f = await Fixture.CreateAsync();
        Write(Allow(JobId, Digest(f.Work.Gateway.Plan)));
        await RecoveryTests.ThrowsCodeAsync(HeldCode, () => f.Executor(observe: shot =>
        {
            if (shot.TaskId == "task-1" && shot.ResultCode == "CORE_COMMITTED") Write(Hold);
        }).RunAsync(JobId));
        RecoveryTests.Assert(f.Work.Gateway.Claims == 1 && f.Work.Gateway.Attempts.SequenceEqual([1, 0, 0])
            && f.Work.Comfy.Submits == 1 && f.Work.Gateway.Completed == 1,
            "revoked config may not allocate or POST shots two and three");
    }

    private static async Task PlanCasesAsync()
    {
        var cases = new (string Name, Func<ProductionPlanRecord, ProductionPlanRecord> Change)[]
        {
            ("wrong_plan_job", p => p with { ProductionJobId = OtherJob }),
            ("wrong_profile", p => p with { ProductionProfile = "untrusted.v1" }),
            ("wrong_schema", p => p with { SchemaVersion = "1.1" }),
            ("two_tasks", p => p with { Tasks = p.Tasks[..2] }),
            ("four_tasks", p => p with { Tasks = [..p.Tasks, p.Tasks[0] with { Order = 4 }] }),
            ("wrong_shot_frozen_digest", p => ChangeFirst(p, t => t with { ShotId = "wrong-shot" })),
            ("wrong_prompt_frozen_digest", p => ChangeFirst(p, t => t with { PositivePrompt = "changed-after-freeze" })),
            ("duplicate_shot", p => ChangeFirst(p, t => t with { ShotId = p.Tasks[1].ShotId })),
            ("duplicate_task", p => ChangeFirst(p, t => t with { ProductionTaskId = p.Tasks[1].ProductionTaskId })),
            ("bad_order", p => ChangeFirst(p, t => t with { Order = 3 })),
            ("needs_human", p => ChangeFirst(p, t => t with { ExecutionDisposition = "NeedsHuman" })),
            ("i2v_workflow", p => ChangeFirst(p, t => t with { WorkflowId = ComfyWorkflowTemplateValidator.I2VWorkflowId })),
            ("i2v_intent", p => ChangeFirst(p, t => t with { RenderIntent = "IMAGE_TO_VIDEO" })),
            ("unapproved_asset", p => ChangeFirst(p, t => t with { TrustedInputAssetRef = "reference/local.png" })),
        };
        foreach (var item in cases)
            await CaseAsync(item.Name, async () =>
            {
                await using var f = await Fixture.CreateAsync();
                var frozen = Digest(f.Work.Gateway.Plan);
                f.Work.Gateway.TransformPlan = item.Change;
                // Structural cases must reject even with a matching checksum; checksum cases keep the original freeze.
                var pinned = item.Name.EndsWith("_frozen_digest", StringComparison.Ordinal) ? frozen : Digest(f.Work.Gateway.Plan);
                Write(Allow(JobId, pinned));
                f.Api.DeclaredDigest = pinned;
                await RecoveryTests.ThrowsCodeAsync(HeldCode, () => f.Executor().RunAsync(JobId));
                f.AssertZero();
            });
        foreach (var identity in new[] { "empty_shot", "empty_task" })
            await CaseAsync(identity, async () =>
            {
                await using var f = await Fixture.CreateAsync();
                f.Work.Gateway.TransformPlan = p => ChangeFirst(p, t => identity == "empty_shot"
                    ? t with { ShotId = "" } : t with { ProductionTaskId = "" });
                // A matching digest cannot make a structurally illegal task identity valid.
                Write(Allow(JobId, Digest(f.Work.Gateway.Plan)));
                var admitted = await P0ThreeShotAcceptanceGate.AllowsJobAsync(f.Session, JobId, CancellationToken.None);
                RecoveryTests.Assert(!admitted,
                    "P0ThreeShotAcceptanceGate.AllowsJobAsync accepted illegal " + identity);
                f.AssertZero();
            });
    }

    private static async Task CoreIdentityCasesAsync()
    {
        var changes = new (string Name, Func<ProductionJobRecord, ProductionJobRecord> Change)[]
        {
            ("core_wrong_job", j => j with { ProductionJobId = OtherJob }),
            ("core_wrong_digest", j => j with { PlanDigest = new string('f', 64) }),
            ("core_wrong_creative", j => j with { CreativePackageId = "different-creative" }),
            ("core_wrong_creative_digest", j => j with { CreativePackageDigest = new string('f', 64) }),
            ("core_wrong_project", j => j with { ProjectKey = "different-project" }),
        };
        foreach (var item in changes)
            await CaseAsync(item.Name, async () =>
            {
                await using var f = await Fixture.CreateAsync();
                Write(Allow(JobId, Digest(f.Work.Gateway.Plan)));
                f.Api.TransformJob = item.Change;
                await RecoveryTests.ThrowsCodeAsync(HeldCode, () => f.Executor().RunAsync(JobId));
                f.AssertZero();
            });
    }

    private static ProductionPlanRecord ChangeFirst(ProductionPlanRecord plan,
        Func<ProductionTaskPlanRecord, ProductionTaskPlanRecord> change) =>
        plan with { Tasks = [change(plan.Tasks[0]), ..plan.Tasks.Skip(1)] };

    private static async Task RecoveryAsync()
    {
        using var old = new RecoveryTests.Fixture();
        old.Comfy.LoseSubmitResponse = true;
        await RecoveryTests.ThrowsAsync<HttpRequestException>(() => old.Executor().RunAsync("job"));
        var journal = new ProductionSubmissionJournal(Path.Combine(old.Root, "journal")); // fresh instance, durable prior POST
        using var http = new HttpClient(old.Comfy, false) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        using var reconciler = new ComfyPromptReconciler(http);
        var lookups = new List<string>();
        var recovery = new ProductionPendingRecovery(journal, reconciler, (id, _) =>
        {
            lookups.Add(id);
            return Task.FromResult(new ProductionJobRecord("job", "creative", new string('a', 64), "project",
                "production.comfyui.v1", new string('b', 64), "Cancelled", null, null, null, null,
                "legacy", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null));
        });
        Write(Hold);
        old.Comfy.ForgetPrompt = true;
        old.Comfy.Requests.Clear();
        await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => recovery.ReconcileAsync());
        RecoveryTests.Assert(old.Comfy.Requests[0] == "GET /history" && old.Comfy.Submits == 1
            && journal.Pending().Single().PromptId is null, "unknown historical POST must remain protected, history-first");
        await using var fresh = await Fixture.CreateAsync();
        await RecoveryTests.ThrowsCodeAsync(HeldCode, () => fresh.Executor(journal: journal).RunAsync(JobId));
        Write(Allow(JobId, Digest(fresh.Work.Gateway.Plan)));
        await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => fresh.Executor(journal: journal).RunAsync(JobId));
        fresh.AssertZero();
        Write(Hold);
        old.Comfy.ForgetPrompt = false;
        old.Comfy.HoldOutput = true;
        await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => recovery.ReconcileAsync());
        RecoveryTests.Assert(journal.Pending().Single().PromptId == "prompt-1",
            "HOLD must not suppress exact read-only reconciliation of an old prompt");
        old.Comfy.HoldOutput = false;
        var drained = await recovery.ReconcileAsync();
        var empty = await recovery.ReconcileAsync();
        RecoveryTests.Assert(drained.HasPending && !empty.HasPending && lookups.All(id => id == "job")
            && old.Comfy.Submits == 1 && old.Gateway.Commits == 0 && old.Gateway.Failure is null,
            "terminal recovery settles only after observed drain and never submits, commits or fails again");
        await RecoveryTests.ThrowsCodeAsync(HeldCode, () => fresh.Executor(journal: journal).RunAsync(JobId));
        fresh.AssertZero();
    }

    private static void Write(string json) => File.WriteAllText(GatePath, json);
    private static string Allow(string job, string digest) => JsonSerializer.Serialize(new
        { schema_version = "1.0", mode = "allow", production_job_id = job, plan_digest = digest });
    private static string Digest(ProductionPlanRecord plan) => Convert.ToHexStringLower(SHA256.HashData(
        CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!)));
    private static void AssertLocked(Action write)
    {
        try { write(); }
        catch (IOException) { return; }
        catch (UnauthorizedAccessException) { return; }
        throw new InvalidOperationException("claim permit failed to lock config replacement");
    }

    public static void Probe(string[] args)
    {
        RequireDisposableRunner();
        var actual = "allowed";
        try { using var permit = P0ThreeShotAcceptanceGate.AcquireSubmissionPermit(JobId, args[2]); }
        catch (ProductionWorkerException error) when (error.Code == HeldCode) { actual = "held"; }
        RecoveryTests.Assert(actual == args[1], "fresh process did not preserve armed gate: " + actual);
        Console.WriteLine("GATE_CHILD=" + actual);
    }

    private static async Task ProbeChildAsync(string expected, string digest)
    {
        var start = new ProcessStartInfo("dotnet") { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true };
        start.ArgumentList.Add(Assembly.GetExecutingAssembly().Location);
        start.ArgumentList.Add("--three-shot-gate-probe"); start.ArgumentList.Add(expected); start.ArgumentList.Add(digest);
        using var child = Process.Start(start) ?? throw new InvalidOperationException("child process unavailable");
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var output = child.StandardOutput.ReadToEndAsync(deadline.Token);
        var errors = child.StandardError.ReadToEndAsync(deadline.Token);
        await child.WaitForExitAsync(deadline.Token);
        RecoveryTests.Assert(child.ExitCode == 0 && (await output).Contains("GATE_CHILD=" + expected, StringComparison.Ordinal),
            "native restart probe failed: " + await errors);
    }

    private sealed class Fixture : IAsyncDisposable
    {
        public MultiShotProductionTests.Fixture Work { get; } = new(false, jobId: JobId);
        public CoreServer Api { get; }
        public ControlCenterSession Session { get; }
        private readonly CredentialManagerTokenStore _tokens = new("PicotooPet.CI.ThreeShot/" + Guid.NewGuid().ToString("N"));
        private readonly SafeFileLogger _logger;
        public int Preflights { get; private set; }
        public Action? DuringPreflight { get; set; }
        private Fixture()
        {
            Api = new(() => Work.Gateway.Plan);
            _logger = new(Path.Combine(Work.Root, "ci.log"));
            Session = new(_tokens, new(Path.Combine(Work.Root, "settings.json")), _logger,
                new ConnectionStateStore(), new CapabilityStateStore(), new TaskStateStore());
        }
        public static async Task<Fixture> CreateAsync()
        {
            var fixture = new Fixture();
            try
            {
                await new DesktopSettingsStore(Path.Combine(fixture.Work.Root, "settings.json"))
                    .SaveAsync(new(fixture.Api.Url), CancellationToken.None);
                // No default credentials, pairing, websocket or external Core. CI-only random credential target.
                await fixture.Session.InitializeAsync(CancellationToken.None);
                fixture._tokens.Save("offline-three-shot-test-only");
                return fixture;
            }
            catch { await fixture.DisposeAsync(); throw; }
        }
        public ProductionExecutionService Executor(Action<ProductionShotObservation>? observe = null,
            ProductionSubmissionJournal? journal = null) => Work.Executor(_ =>
            {
                Preflights++; DuringPreflight?.Invoke();
                return Task.FromResult(new ProductionPreflightSnapshot(true, "offline", Work.Root, Work.Root, Work.Root, Work.Root, []));
            }, observe, P0ThreeShotAcceptanceGate.AcquireSubmissionPermit,
            (job, ct) => P0ThreeShotAcceptanceGate.AllowsJobAsync(Session, job, ct), journal);
        public void AssertZero() => RecoveryTests.Assert(Work.Gateway.Claims == 0
            && Work.Gateway.Attempts.All(x => x == 0) && Work.Comfy.Submits == 0,
            "unauthorized work reached Core claim, attempt reservation or Comfy POST");
        public async ValueTask DisposeAsync()
        {
            await Session.DisposeAsync();
            _tokens.Delete();
            await _logger.DisposeAsync();
            await Api.DisposeAsync();
            Work.Dispose();
        }
    }

    private sealed class CoreServer : IAsyncDisposable
    {
        private readonly HttpListener _listener = new();
        private readonly Task _loop;
        private readonly Func<ProductionPlanRecord> _plan;
        private volatile bool _stopping;
        public string Url { get; }
        public string? DeclaredDigest { get; set; }
        public Func<ProductionJobRecord, ProductionJobRecord>? TransformJob { get; set; }
        public List<string> Requests { get; } = new();
        public CoreServer(Func<ProductionPlanRecord> plan)
        {
            _plan = plan;
            var reservation = new TcpListener(IPAddress.Loopback, 0);
            reservation.Start();
            var port = ((IPEndPoint)reservation.LocalEndpoint).Port;
            reservation.Stop();
            Url = "http://127.0.0.1:" + port.ToString(System.Globalization.CultureInfo.InvariantCulture) + "/";
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
                    Requests.Add(request.HttpMethod + " " + request.Url!.AbsolutePath);
                    var plan = _plan();
                    var job = new ProductionJobRecord(JobId, plan.CreativePackageId, plan.CreativePackageDigest,
                        plan.ProjectKey, plan.ProductionProfile, DeclaredDigest ?? Digest(plan), "Ready", null,
                        null, null, null, "ci", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
                    job = TransformJob?.Invoke(job) ?? job;
                    object? body = request.HttpMethod != "GET" || request.Headers["Authorization"] != "Bearer offline-three-shot-test-only"
                        ? null : request.Url.AbsolutePath switch
                        {
                            "/api/v1/production/jobs/" + JobId => job,
                            "/api/v1/production/jobs/" + JobId + "/plan" => plan,
                            _ => null,
                        };
                    context.Response.StatusCode = body is null ? 400 : 200;
                    context.Response.ContentType = "application/json";
                    var bytes = JsonSerializer.SerializeToUtf8Bytes(body);
                    context.Response.ContentLength64 = bytes.Length;
                    await context.Response.OutputStream.WriteAsync(bytes);
                    context.Response.Close();
                }
            }
            catch (HttpListenerException error) when (_stopping && error.ErrorCode == 995) { }
            catch (ObjectDisposedException) when (_stopping) { }
        }
        public async ValueTask DisposeAsync() { _stopping = true; _listener.Stop(); await _loop; _listener.Close(); }
    }
}
