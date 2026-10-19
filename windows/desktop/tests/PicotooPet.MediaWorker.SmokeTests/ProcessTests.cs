using System.Diagnostics;
using System.IO;

namespace PicotooPet.MediaWorker.SmokeTests;

/// <summary>两个真正的 Windows 子进程共享 fake Core/Comfy 外部事实和实际 journal；不是 live GPU 验收。</summary>
internal static class ProcessTests
{
    public static async Task ChildAsync(string mode, string root)
    {
        using var f = new RecoveryTests.Fixture(root) { Preserve = true };
        if (mode == "crash")
        {
            f.Comfy.LoseSubmitResponse = true;
            await RecoveryTests.ThrowsAsync<System.Net.Http.HttpRequestException>(() => f.Executor().RunAsync("job"));
            File.WriteAllText(Path.Combine(root, "submitted"), f.Comfy.Submits.ToString(System.Globalization.CultureInfo.InvariantCulture));
            return;
        }
        f.Gateway.RestoreReservation();
        f.Comfy.HoldOutput = true;
        using var stop = new CancellationTokenSource();
        var work = f.Executor().RunAsync("job", stop.Token);
        File.WriteAllText(Path.Combine(root, "restarted"), "ready");
        while (!File.Exists(Path.Combine(root, "release"))) await Task.Delay(10);
        f.Comfy.HoldOutput = false;
        await work;
        RecoveryTests.Assert(f.Comfy.Submits == 0 && f.Gateway.Commits == 1, "new process must reconcile old prompt without POST");
        File.WriteAllText(Path.Combine(root, "completed"), "one prompt, one commit, after UI closed");
    }
    public static async Task RunAsync()
    {
        using var f = new RecoveryTests.Fixture();
        await RunChildAsync("crash", f.Root);
        RecoveryTests.Assert(File.ReadAllText(Path.Combine(f.Root, "submitted")) == "1", "accepted one external prompt before process exit");
        using var child = Start("recover", f.Root);
        await WaitFileAsync(Path.Combine(f.Root, "restarted"), child);
        await using (var gui = new PicotooPet.Desktop.Services.GoalProductionAutopilotCoordinator(new ObserverOnly()))
        {
            gui.Observe(null, null);
        }
        RecoveryTests.Assert(!child.HasExited, "closing UI observer must not kill restarted worker process");
        File.WriteAllText(Path.Combine(f.Root, "release"), "finish external fake GPU");
        await child.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(20));
        RecoveryTests.Assert(child.ExitCode == 0 && File.Exists(Path.Combine(f.Root, "completed")), "independent child completed after UI close");
        Console.WriteLine("MEDIA_WORKER_REAL_PROCESS_RESTART_UI_CLOSE=PASS (offline fake API only)");
    }
    private static async Task RunChildAsync(string mode, string root)
    {
        using var process = Start(mode, root);
        await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(20));
        RecoveryTests.Assert(process.ExitCode == 0, "child failed");
    }
    private static Process Start(string mode, string root)
    {
        var start = new ProcessStartInfo(Path.Combine(AppContext.BaseDirectory, "PicotooPet.MediaWorker.SmokeTests.exe"))
        { UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in new[] { "--child", mode, root }) start.ArgumentList.Add(arg);
        return Process.Start(start) ?? throw new InvalidOperationException("child start failed");
    }
    private static async Task WaitFileAsync(string file, Process child)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        while (!File.Exists(file))
        { RecoveryTests.Assert(!child.HasExited, "child exited before recovery"); await Task.Delay(10, timeout.Token); }
    }
    private sealed class ObserverOnly : PicotooPet.Desktop.Services.IProductionJobExecutor
    {
        public Task<PicotooPet.Desktop.Core.Contracts.ProductionPackageRecord> RunAsync(string productionJobId, CancellationToken cancellationToken = default)
            => throw new InvalidOperationException("UI must not render");
    }
}
