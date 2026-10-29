using System.IO;
using System.Net.Http;
using System.Net;
using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class RecoveryFixTests
{
    public static async Task RunAsync()
    {
        var errors = new List<Exception>();
        foreach (var test in new Func<Task>[] { DurableFailureAsync, LegacyUnknownAsync, SettledCapacityAsync, InvalidOutputAsync,
            TerminalPendingAsync, PreparedReservationAsync, MissingCoreAsync, TimeoutKeepsGpuBarrierAsync,
            RebootLostHistoryNeverRepostsAsync, ExplicitAttempt2ApprovalAsync, MissingHistoryRequiresIdleQueueAsync,
            BoundSecondAttemptAsync, HistoryOfflineAsync, LostLeaseAsync, ExactTransportAsync, RejectedLegacyClaimAsync,
            SettledDoesNotReopenAsync })
        {
            try { await test(); }
            catch (Exception e) { errors.Add(e); Console.WriteLine("RECOVERY_RED: " + e.Message); }
        }
        if (errors.Count > 0) throw new AggregateException(errors);
        Console.WriteLine("MEDIA_WORKER_FAILURE_LEGACY_CAPACITY=PASS");
    }

    private static async Task DurableFailureAsync()
    {
        using var f = new RecoveryTests.Fixture();
        f.Comfy.HistoryError = true;
        f.Gateway.LoseFailureResponse = true;
        await RecoveryTests.ThrowsAsync<System.Net.Http.HttpRequestException>(() => f.Executor().RunAsync("job"));
        RecoveryTests.Assert(f.Journal.Pending().Single().Phase == "FailurePending", "terminal report intent must survive lost failure response");
        using var http = new HttpClient(f.Comfy, false) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        using var reconcile = new ComfyPromptReconciler(http);
        await new ProductionPendingRecovery(f.Journal, reconcile, (_, _) => Task.FromResult(Job("Failed"))).ReconcileAsync();
        RecoveryTests.Assert(f.Gateway.Failure?.FailureCode == "COMFY_RETRY_BUDGET_EXHAUSTED" && f.Comfy.Submits == 1
            && f.Gateway.Commits == 0 && f.Journal.Pending().Count == 0, "definite failure actually reports legacy code to Core, never resubmits");

        using var acknowledged = new RecoveryTests.Fixture();
        acknowledged.Comfy.HistoryError = true;
        await RecoveryTests.ThrowsCodeAsync("COMFY_RETRY_BUDGET_EXHAUSTED", () => acknowledged.Executor().RunAsync("job"));
        RecoveryTests.Assert(acknowledged.Gateway.Failure is not null && acknowledged.Journal.Pending().Count == 0,
            "acknowledged terminal failure settles only after GPU drains");
    }

    private static async Task LegacyUnknownAsync()
    {
        using var f = new RecoveryTests.Fixture();
        f.Gateway.RestoreReservation();
        f.Comfy.ForgetPrompt = true;
        await RecoveryTests.ThrowsCodeAsync("MEDIA_SUBMISSION_UNKNOWN", () => f.Executor().RunAsync("job"));
        RecoveryTests.Assert(f.Journal.Pending().Single().Phase == "Submitting", "legacy unbound attempt must persist unknown POST barrier before reconciliation");
        await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => f.Executor().RunAsync("other"));
        RecoveryTests.Assert(f.Comfy.Submits == 0 && f.Gateway.Failure is null, "unknown work never submits or invents failure");
    }

    private static Task SettledCapacityAsync()
    {
        using var f = new RecoveryTests.Fixture();
        var digest = new string('a', 64);
        for (var i = 0; i < 1005; i++) f.Journal.Save(new("old" + i, "task", digest, digest, "Settled", "prompt"));
        f.Journal.Save(new("pending", "task", digest, digest, "Submitting", null));
        var pending = f.Journal.Pending();
        RecoveryTests.Assert(pending.Single().JobId == "pending", "settled capacity must never evict uncertainty");
        RecoveryTests.Assert(Directory.GetFiles(Path.Combine(f.Root, "journal"), "*.submission.json").Length <= 129,
            "settled retention bounded to 128 plus pending");
        return Task.CompletedTask;
    }

    private static async Task InvalidOutputAsync()
    {
        using var f = new RecoveryTests.Fixture();
        File.WriteAllBytes(Path.Combine(f.Root, "clip.webm"), []);
        await RecoveryTests.ThrowsCodeAsync("COMFY_RETRY_BUDGET_EXHAUSTED", () => f.Executor().RunAsync("job"));
        RecoveryTests.Assert(f.Gateway.Failure?.FailureCode == "COMFY_RETRY_BUDGET_EXHAUSTED" && f.Gateway.Commits == 0,
            "invalid completed output durably fails instead of becoming Ready");
    }

    private static async Task PreparedReservationAsync()
    {
        using var f = new RecoveryTests.Fixture();
        f.Comfy.LoseSubmitResponse = true;
        await RecoveryTests.ThrowsAsync<HttpRequestException>(() => f.Executor().RunAsync("job"));
        var state = f.Journal.Pending().Single();
        f.Journal.Save(state with { Phase = "Prepared", PromptId = null });
        f.Comfy.ForgetPrompt = true;
        await RecoveryTests.ThrowsCodeAsync("MEDIA_SUBMISSION_UNKNOWN", () => f.Executor().RunAsync("job"));
        RecoveryTests.Assert(f.Comfy.Submits == 1 && f.Journal.Pending().Single().Phase == "Submitting",
            "Prepared with existing Core reservation is not permission to POST");
    }

    private static ProductionJobRecord Job(string status) => new("job", "creative", new string('a',64), "project",
        "production.comfyui.v1", new string('b',64), status, null, null, null, null, "key", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);

    private static async Task TerminalPendingAsync()
    {
        foreach (var terminal in new[] { "Cancelled", "Failed", "NeedsHuman", "production_ready" })
        {
            using var f = new RecoveryTests.Fixture();
            f.Comfy.LoseSubmitResponse = true;
            await RecoveryTests.ThrowsAsync<HttpRequestException>(() => f.Executor().RunAsync("job"));
            using var http = new HttpClient(f.Comfy, false) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
            using var reconcile = new ComfyPromptReconciler(http);
            var lookups = new List<string>();
            var recovery = new ProductionPendingRecovery(f.Journal, reconcile, (id, _) =>
            { lookups.Add(id); return Task.FromResult(Job(terminal)); });
            f.Comfy.HoldOutput = true;
            await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => recovery.ReconcileAsync());
            RecoveryTests.Assert(f.Journal.Pending().Single().PromptId == "prompt-1", "persist recovered terminal prompt before drain");
            f.Comfy.HoldOutput = false;
            var drained = await recovery.ReconcileAsync();
            var empty = await recovery.ReconcileAsync();
            RecoveryTests.Assert(drained.HasPending && drained.RecoverableJobId is null && !empty.HasPending
                && lookups.All(id => id == "job") && f.Comfy.Submits == 1 && f.Gateway.Commits == 0 && f.Gateway.Failure is null,
                "exact-ID terminal recovery drains external prompt without execute/fail/cancel or recent list");
        }
    }

    private static async Task MissingCoreAsync()
    {
        using var f = new RecoveryTests.Fixture();
        f.Journal.Save(new("job", "task", new string('a',64), new string('b',64), "Submitting", null));
        using var http = new HttpClient(f.Comfy, false) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        using var reconcile = new ComfyPromptReconciler(http);
        var recovery = new ProductionPendingRecovery(f.Journal, reconcile,
            (_, _) => throw new HttpRequestException("offline or 404"));
        await RecoveryTests.ThrowsAsync<HttpRequestException>(() => recovery.ReconcileAsync());
        RecoveryTests.Assert(f.Journal.Pending().Count == 1 && f.Comfy.Submits == 0, "missing exact Core job is not terminal proof");
    }

    private static async Task TimeoutKeepsGpuBarrierAsync()
    {
        // A prompt may still be GPU-active when history polling times out.
        // Timeout itself must never terminal-fail the whole Core job.
        using var f = new RecoveryTests.Fixture();
        f.Comfy.HoldOutput = true;
        await RecoveryTests.ThrowsCodeAsync("COMFY_HISTORY_TIMEOUT",
            () => f.Executor(TimeSpan.FromMilliseconds(60)).RunAsync("job"));
        RecoveryTests.Assert(f.Gateway.Failure is null && f.Gateway.Commits == 0
            && f.Comfy.Submits == 1 && f.Journal.Pending().Single().Phase == "Submitted",
            "history timeout preserves bound prompt and blocks other GPU jobs without inventing final failure");
        await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => f.Executor().RunAsync("other"));
    }

    private static async Task RebootLostHistoryNeverRepostsAsync()
    {
        // Models a real Windows restart: Comfy queue is empty, old /history/{id} is {},
        // original prompt is still bound in durable Core and local Journal.
        // Neither a missing history entry nor a second recovery pass is a new GPU authorization.
        using var f = new RecoveryTests.Fixture();
        f.Comfy.ForgetPrompt = true;
        await RecoveryTests.ThrowsCodeAsync("COMFY_HISTORY_TIMEOUT",
            () => f.Executor(TimeSpan.FromMilliseconds(60)).RunAsync("job"));
        var old = f.Journal.Pending().Single();
        RecoveryTests.Assert(old.Phase == "Submitted" && old.PromptId == "prompt-1"
            && f.Gateway.Failure is null && f.Gateway.Commits == 0 && f.Comfy.Submits == 1,
            "reboot-lost history retains the old durable prompt and no terminal Core failure");

        await RecoveryTests.ThrowsCodeAsync("COMFY_HISTORY_TIMEOUT",
            () => f.Executor(TimeSpan.FromMilliseconds(60)).RunAsync("job"));
        RecoveryTests.Assert(f.Comfy.Submits == 1 && f.Gateway.Failure is null
            && f.Journal.Pending().Single().PromptId == old.PromptId,
            "second restart/recovery pass must not rePOST or erase prompt identity");
        await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => f.Executor().RunAsync("other"));
    }

    private static Task ExplicitAttempt2ApprovalAsync()
    {
        // Approval is exact-ID, short-lived and *after* the Windows reboot.
        // The original Core-bound prompt updated_at must be strictly pre-boot.
        var path = Path.Combine(Path.GetTempPath(), "p0-approval-" + Guid.NewGuid().ToString("N") + ".json");
        var now = DateTimeOffset.UtcNow;
        var boot = now.AddMinutes(-10);
        var original = boot.AddMinutes(-5);
        var json = JsonSerializer.Serialize(new
        {
            schema_version = "p0.lost-prompt-attempt2.v1",
            production_job_id = "job",
            production_task_id = "shot3-task",
            previous_prompt_id = "prompt-lost-before-boot",
            plan_digest = new string('a', 64),
            authorized_at_utc = now.ToString("O"),
        });
        try
        {
            File.WriteAllText(path, json);
            RecoveryTests.Assert(P0LostPromptRetryApproval.IsApproved(
                "job", "shot3-task", "prompt-lost-before-boot", new string('a', 64),
                original, boot, now, path), "exact approved post-boot prompt");
            awaitMustReject(() => P0LostPromptRetryApproval.IsApproved(
                "other-job", "shot3-task", "prompt-lost-before-boot", new string('a', 64),
                original, boot, now, path));
            awaitMustReject(() => P0LostPromptRetryApproval.IsApproved(
                "job", "shot3-task", "other-prompt", new string('a', 64),
                original, boot, now, path));
            awaitMustReject(() => P0LostPromptRetryApproval.IsApproved(
                "job", "different-task", "prompt-lost-before-boot", new string('a', 64),
                original, boot, now, path));
            awaitMustReject(() => P0LostPromptRetryApproval.IsApproved(
                "job", "shot3-task", "prompt-lost-before-boot", new string('a', 64),
                boot.AddMinutes(1), boot, now, path));
            awaitMustReject(() => P0LostPromptRetryApproval.IsApproved(
                "job", "shot3-task", "prompt-lost-before-boot", new string('a', 64),
                original, boot, now.AddMinutes(31), path));
        }
        finally { File.Delete(path); }
        return Task.CompletedTask;

        static void awaitMustReject(Func<bool> action)
        {
            try { _ = action(); }
            catch (ProductionWorkerException e) when (e.Code == "MEDIA_RECOVERY_APPROVAL_INVALID") { return; }
            throw new InvalidOperationException("Invalid reboot witness or expired operator approval must block");
        }
    }

    private static async Task MissingHistoryRequiresIdleQueueAsync()
    {
        using var f = new RecoveryTests.Fixture();
        using var http = new HttpClient(f.Comfy) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        using var reader = new ComfyPromptReconciler(http);
        f.Comfy.ForgetPrompt = true;
        RecoveryTests.Assert(await reader.IsMissingWithIdleQueueAsync("prompt-1", default),
            "history absent AND queue idle");
        f.Comfy.HoldOutput = true;
        RecoveryTests.Assert(!await reader.IsMissingWithIdleQueueAsync("prompt-1", default),
            "active GPU forbids retry even when history is empty");
        f.Comfy.HoldOutput = false;
        f.Comfy.ForgetPrompt = false;
        RecoveryTests.Assert(!await reader.IsMissingWithIdleQueueAsync("prompt-1", default),
            "history present forbids retry");
    }

    private static async Task BoundSecondAttemptAsync()
    {
        using var f = new RecoveryTests.Fixture();
        f.Gateway.LoseBindResponse = true;
        await RecoveryTests.ThrowsAsync<HttpRequestException>(() => f.Executor().RunAsync("job"));
        f.Gateway.RestoreBoundSecondAttempt();
        await f.Executor().RunAsync("job");
        RecoveryTests.Assert(f.Comfy.Submits == 1 && f.Gateway.Reservations == 2 && f.Gateway.Commits == 1,
            "bound attempt2 recovery only reads history and commits, never allocates attempt3");
    }

    private static async Task HistoryOfflineAsync()
    {
        using var f = new RecoveryTests.Fixture();
        f.Comfy.HistoryOffline = true;
        await RecoveryTests.ThrowsAsync<HttpRequestException>(() => f.Executor().RunAsync("job"));
        RecoveryTests.Assert(f.Journal.Pending().Single().Phase == "Submitted" && f.Gateway.Failure is null,
            "history transport uncertainty is not definite render failure");
        f.Comfy.HistoryOffline = false;
        await f.Executor().RunAsync("job");
        RecoveryTests.Assert(f.Comfy.Submits == 1 && f.Gateway.Commits == 1, "history reconnect resumes exact bound prompt");
    }

    private static async Task LostLeaseAsync()
    {
        using var f = new RecoveryTests.Fixture();
        f.Comfy.HoldOutput = true;
        f.Gateway.LoseHeartbeat = true;
        await RecoveryTests.ThrowsCodeAsync("PRODUCTION_LEASE_LOST", () => f.Executor().RunAsync("job"));
        RecoveryTests.Assert(f.Journal.Pending().Count == 1 && f.Gateway.Failure is null && f.Gateway.Commits == 0,
            "heartbeat loss preserves GPU uncertainty without terminal writes");
    }

    private static async Task ExactTransportAsync()
    {
        using var handler = new ExactHandler();
        using var http = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:9999/") };
        await using var client = new MacCoreProductionClient(http, "offline-test-credential");
        var job = await client.GetJobAsync("old/job");
        RecoveryTests.Assert(job.ProductionJobId == "job" && handler.RequestPath == "/api/v1/production/jobs/old%2Fjob",
            "exact transport escapes ID and never enumerates recent jobs");
    }

    private sealed class ExactHandler : HttpMessageHandler
    {
        public string? RequestPath { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            RequestPath = request.RequestUri!.AbsolutePath;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                { Content = new StringContent(JsonSerializer.Serialize(Job("Rendering")), Encoding.UTF8, "application/json") });
        }
    }

    private static async Task RejectedLegacyClaimAsync()
    {
        using var f = new RecoveryTests.Fixture();
        f.Gateway.RestoreReservation();
        f.Gateway.RejectUnboundClaim = true;
        await RecoveryTests.ThrowsCodeAsync("MEDIA_CLAIM_CONFLICT_RECONCILIATION", () => f.Executor().RunAsync("job"));
        RecoveryTests.Assert(f.Journal.Pending().Single().Phase == "Submitting", "Core refusal cannot erase legacy uncertainty");
        await RecoveryTests.ThrowsCodeAsync("MEDIA_PENDING_RECONCILIATION", () => f.Executor().RunAsync("other"));
        RecoveryTests.Assert(f.Comfy.Submits == 0 && f.Gateway.Failure is null, "no lease bypass or second job after rejected legacy claim");
    }

    private static async Task SettledDoesNotReopenAsync()
    {
        using var f = new RecoveryTests.Fixture();
        await f.Executor().RunAsync("job");
        var settled = f.Journal.Read("job", "task")!;
        f.Comfy.HistoryOffline = true;
        using var http = new HttpClient(f.Comfy, false) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        using var reconcile = new ComfyPromptReconciler(http);
        using var gpu = f.Journal.AcquireGpu();
        await ProductionPendingRecovery.ReconcileTerminalAsync(f.Journal, reconcile, settled);
        RecoveryTests.Assert(f.Journal.Read("job", "task")!.Phase == "Settled", "settled successful shot never reopens after history eviction");
    }
}
