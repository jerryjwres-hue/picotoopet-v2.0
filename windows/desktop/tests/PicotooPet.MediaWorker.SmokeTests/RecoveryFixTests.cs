using System.IO;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class RecoveryFixTests
{
    public static async Task RunAsync()
    {
        var errors = new List<Exception>();
        foreach (var test in new Func<Task>[] { DurableFailureAsync, LegacyUnknownAsync, SettledCapacityAsync, InvalidOutputAsync })
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
        await RecoveryTests.ThrowsCodeAsync("COMFY_RETRY_BUDGET_EXHAUSTED", () => f.Executor().RunAsync("job"));
        RecoveryTests.Assert(f.Gateway.Failure?.FailureCode == "COMFY_RETRY_BUDGET_EXHAUSTED" && f.Comfy.Submits == 1
            && f.Gateway.Commits == 0 && f.Journal.Pending().Count == 0, "definite failure actually reports legacy code to Core, never resubmits");
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
}
