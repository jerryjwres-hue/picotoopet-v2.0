using System.Diagnostics;
using System.IO;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class LegacyContractTests
{
    public static async Task RunAsync()
    {
        // Execute BOTH unmodified Python contract functions, without installing pytest/SDKs.
        // Hosted Windows includes Python. This stays in the existing focused worker gate.
        const string relative = "tests/contract/test_production_final_failure_contract.py";
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, relative))) root = root.Parent;
        if (root is null) throw new InvalidOperationException("Legacy contract source unavailable");
        var start = new ProcessStartInfo("python") { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = root.FullName };
        start.ArgumentList.Add("-c");
        start.ArgumentList.Add("import runpy; n=runpy.run_path('tests/contract/test_production_final_failure_contract.py'); n['test_executor_durably_reports_final_render_failure_to_core'](); n['test_failure_transport_is_a_bounded_production_endpoint'](); print('LEGACY_PRODUCTION_FINAL_FAILURE_CONTRACT=PASS (2 original tests)')");
        using var process = Process.Start(start) ?? throw new InvalidOperationException("Python contract process unavailable");
        await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(30));
        if (process.ExitCode != 0) throw new InvalidOperationException("Legacy failure contract failed");
    }
}
