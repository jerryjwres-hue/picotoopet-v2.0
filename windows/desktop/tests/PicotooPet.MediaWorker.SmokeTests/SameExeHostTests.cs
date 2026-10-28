using System.IO;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class SameExeHostTests
{
    public static void Run()
    {
        // ── Compile-time adapter must execute from the same WPF binary, not a new product. ──
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        const string exe = "windows/desktop/src/PicotooPet.Desktop/Program.cs";
        while (root is not null && !File.Exists(Path.Combine(root.FullName, exe)))
        {
            root = root.Parent;
        }
        if (root is null) throw new InvalidOperationException("P0_SAME_EXE_SOURCE_MISSING");
        var program = File.ReadAllText(Path.Combine(root.FullName, exe));
        var host = File.ReadAllText(Path.Combine(root.FullName,
            "windows/desktop/src/PicotooPet.Desktop/Services/P0MediaWorkerHost.cs"));
        var gui = File.ReadAllText(Path.Combine(root.FullName,
            "windows/desktop/src/PicotooPet.Desktop/App.xaml.cs"));
        if (!program.Contains("--p0-media-worker", StringComparison.Ordinal)
            || !program.Contains("P0MediaWorkerHost.RunAsync", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("P0_WORKER_NOT_SAME_EXE");
        }

        // ── Journal state must be checked before any fresh Goal->GPU candidate lookup. ──
        var reconcile = host.IndexOf("pendingRecovery.ReconcileAsync", StringComparison.Ordinal);
        var fresh = host.IndexOf("session.GetGoalsAsync", StringComparison.Ordinal);
        if (reconcile < 0 || fresh < 0 || reconcile >= fresh
            || !host.Contains("if (pending.HasPending)", StringComparison.Ordinal)
            || !host.Contains("pending.RecoverableJobId", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("P0_JOURNAL_NOT_FIRST");
        }
        if (!host.Contains("ProductionSubmissionJournal.DefaultRoot", StringComparison.Ordinal)
            || !host.Contains("session.GetProductionJobAsync", StringComparison.Ordinal)
            || !(host.Contains("ProductionExecutionService.Create(session)", StringComparison.Ordinal)
                || host.Contains("ProductionExecutionService.Create(session,", StringComparison.Ordinal)))
        {
            throw new InvalidOperationException("P0_DURABLE_RECOVERY_NOT_WIRED");
        }

        // ── GUI ordinary close must not revoke leases; explicit Exit cooperatively stops. ──
        if (!gui.Contains("P0MediaWorkerHost.RequestExplicitStop()", StringComparison.Ordinal)
            || !host.Contains("stopSignal.WaitOne(0)", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("P0_EXPLICIT_EXIT_BOUNDARY_MISSING");
        }
        // A localized Windows COMPUTERNAME (observed: 王小安WLA) must never be
        // submitted as a Unicode executor_id: Mac Core rejects non-ASCII with 422.
        var localized = ProductionExecutionService.NormalizeExecutorId("windows-production-王小安WLA");
        var ascii = ProductionExecutionService.NormalizeExecutorId("windows-production-ASCII_01");
        var truncated = ProductionExecutionService.NormalizeExecutorId(new string('x', 140));
        if (localized != "windows-production----WLA"
            || ascii != "windows-production-ASCII_01"
            || truncated.Length != 120
            || !System.Text.RegularExpressions.Regex.IsMatch(localized, @"\A[A-Za-z0-9_.-]{1,120}\z"))
        {
            throw new InvalidOperationException("P0_UNICODE_EXECUTOR_ID_CONTRACT_FAILED");
        }
        Console.WriteLine("P0_UNICODE_EXECUTOR_ID_ASCII_CONTRACT=PASS");
        Console.WriteLine("P0_SAME_EXE_RECONCILE_BEFORE_NEW_GPU=PASS");
    }
}
