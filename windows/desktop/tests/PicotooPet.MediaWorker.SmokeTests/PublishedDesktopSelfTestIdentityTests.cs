using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace PicotooPet.MediaWorker.SmokeTests;

// Invoked only by the focused workflow's disposable test project. This is not a Worker.
internal static class PublishedDesktopSelfTestIdentityTests
{
    private static readonly string[] ExplicitFlags = ["--self-test", "--self-test-exe-identity"];
    private static readonly JsonSerializerOptions EvidenceJson = new() { WriteIndented = true };
    internal static async Task RunAsync(string[] args)
    {
        var selfTest = Assembly.Load("Picotoo Pet AI").GetType("PicotooPet.Desktop.Services.AppSelfTest", true)!;
        var flag = selfTest.GetMethod("IsExeIdentityRequested", BindingFlags.NonPublic | BindingFlags.Static);
        Require(flag is not null, "explicit self-test identity opt-in must exist");
        foreach (var input in new[] { Array.Empty<string>(), new[] { "--self-test" },
            new[] { "--self-test-exe-identity" }, new[] { "--self-test", "--self-test-exe-identity-unknown" } })
            Require(!(bool)flag!.Invoke(null, [input])!, "unknown/absent flags cannot enable diagnostic");
        Require((bool)flag!.Invoke(null, [ExplicitFlags])!, "both explicit flags enable diagnostic");
        Console.WriteLine("P0_IDENTITY_FLAG_CONTRACT=PASS");
        if (args.Length == 1 && args[0] == "--flags-only") return;
        Require(OperatingSystem.IsWindows() && Environment.GetEnvironmentVariable("CI") == "true", "native disposable Windows CI required");
        var hash = selfTest.GetMethod("HashIdentityFileAsync", BindingFlags.NonPublic | BindingFlags.Static)!;
        Require(hash is not null, "read-only PE measurement helper exists");
        var root = Path.Combine(Path.GetTempPath(), "picotoopet-identity-negatives-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var managed = Path.Combine(root, "managed-as-exe.exe");
            File.Copy(selfTest.Assembly.Location, managed);
            var malformed = Path.Combine(root, "malformed.exe"); File.WriteAllText(malformed, "MZnotPE");
            var alias = Path.Combine(root, "alias.exe"); File.CreateSymbolicLink(alias, Environment.ProcessPath!);
            foreach (var path in new[] { "", "relative.exe", Path.Combine(root, "missing.exe"),
                malformed, managed, alias, selfTest.Assembly.Location })
            {
                var denied = false;
                try { await (Task<string>)hash!.Invoke(null, [path, CancellationToken.None])!; }
                catch (TargetInvocationException e) when (e.InnerException is IOException or InvalidDataException or BadImageFormatException or UnauthorizedAccessException or ArgumentException) { denied = true; }
                catch (Exception e) when (e is IOException or InvalidDataException or BadImageFormatException or UnauthorizedAccessException or ArgumentException) { denied = true; }
                Require(denied, "missing/invalid/managed/reparse image must be rejected");
            }
            var valid = Path.Combine(root, "native.exe"); File.Copy(Environment.ProcessPath!, valid);
            var baseline = await (Task<string>)hash!.Invoke(null, [valid, CancellationToken.None])!;
            Require(baseline == Digest(valid), "pinned candidate reads exact native PE bytes");
            using (var writer = new FileStream(valid, FileMode.Open, FileAccess.Write, FileShare.Read))
            {
                var denied = false;
                try { await (Task<string>)hash.Invoke(null, [valid, CancellationToken.None])!; }
                catch (IOException) { denied = true; }
                Require(denied, "existing writer prevents a stable measurement");
            }
            using var canceled = new CancellationTokenSource(); canceled.Cancel();
            var refusedCancellation = false;
            try { await (Task<string>)hash.Invoke(null, [valid, canceled.Token])!; }
            catch (OperationCanceledException) { refusedCancellation = true; }
            Require(refusedCancellation, "canceled read cannot produce a digest");
        }
        finally { Directory.Delete(root, true); }
        Console.WriteLine("P0_IDENTITY_INVALID_FILE_NEGATIVES=PASS");
        if (args.Length == 1 && args[0] == "--helpers-only") return;
        Require(args.Length == 3, "expected published EXE, managed build DLL, report directory");
        var exe = Path.GetFullPath(args[0]); var dll = Path.GetFullPath(args[1]); var reports = Path.GetFullPath(args[2]);
        Require(Path.GetFileName(exe) == "Picotoo Pet AI.exe" && File.Exists(exe) && File.Exists(dll), "actual published Desktop inputs");
        Directory.CreateDirectory(reports);
        var beforeHash = Digest(exe); var dllHash = Digest(dll);
        Require(beforeHash != dllHash, "published native EXE differs from managed DLL");
        RequireNoDesktop();
        var identityReport = Path.Combine(reports, "published-identity.json");
        var osPath = await LaunchAsync(exe, identityReport, "--self-test-exe-identity");
        using (var document = JsonDocument.Parse(File.ReadAllText(identityReport)))
        {
            var report = document.RootElement;
            Require(report.GetProperty("status").GetString() == "pass", "published identity self-test passed");
            var image = report.GetProperty("exe_identity");
            Require(image.GetProperty("status").GetString() == "PASS", "read-only process evidence complete");
            foreach (var key in new[] { "os_process_path", "environment_process_path" })
                Require(string.Equals(image.GetProperty(key).GetString(), exe, StringComparison.OrdinalIgnoreCase), "internal OS/environment path equals published EXE");
            Require(string.Equals(osPath, exe, StringComparison.OrdinalIgnoreCase), "external OS process identity equals published EXE");
            Require(image.GetProperty("executable_sha256").GetString() == beforeHash && beforeHash == Digest(exe), "stable actual running EXE SHA256");
            Require(image.GetProperty("entry_assembly_name").GetString() == "Picotoo Pet AI", "real Desktop entry assembly");
            Require(image.GetProperty("entry_assembly_location_empty").GetBoolean(), "single-file bundled entry Location is empty");
            Require(image.GetProperty("managed_dll_sha256").ValueKind == JsonValueKind.Null, "bundled DLL not misrepresented as a measured file");
            Require(image.GetProperty("frozen_worker_measurement").GetString() == "REJECTED"
                && image.GetProperty("frozen_worker_measurement_error").GetString() == "WORKER_EXE_HOST_UNVERIFIED", "frozen single-file incompatibility retained");
            Require(image.GetProperty("signed_witness").GetString() == "NOT_INVOKED", "no witness claimed");
        }
        // Preserve v1 behavior and ensure an unknown lookalike flag cannot opt in.
        foreach (var extra in new string?[] { null, "--self-test-exe-identity-unknown" })
        {
            var path = Path.Combine(reports, extra is null ? "legacy-self-test.json" : "unknown-flag-self-test.json");
            await LaunchAsync(exe, path, extra);
            using var normal = JsonDocument.Parse(File.ReadAllText(path));
            Require(normal.RootElement.GetProperty("status").GetString() == "pass"
                && !normal.RootElement.TryGetProperty("exe_identity", out _), "normal self-test schema/behavior unchanged");
        }
        File.WriteAllText(Path.Combine(reports, "external-process-evidence.json"), JsonSerializer.Serialize(new
        {
            os_process_path = osPath, executable_sha256 = beforeHash, managed_build_dll_sha256 = dllHash,
            published_process_measurement = "PASS", frozen_single_file_worker_compatibility = "REJECTED_WORKER_EXE_HOST_UNVERIFIED",
            witness = "NOT_INVOKED", trusted_worker_attestation = "UNVERIFIED",
        }, EvidenceJson));
        Console.WriteLine("P0_PUBLISHED_DESKTOP_PROCESS_MEASUREMENT=PASS; SINGLE_FILE_WORKER_COMPATIBILITY=REJECTED; WITNESS=NOT_INVOKED");
    }

    private static async Task<string> LaunchAsync(string exe, string report, string? extra)
    {
        var start = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = Path.GetDirectoryName(exe)! };
        start.ArgumentList.Add("--self-test");
        if (extra is not null) start.ArgumentList.Add(extra);
        start.ArgumentList.Add("--self-test-output"); start.ArgumentList.Add(report);
        using var process = Process.Start(start) ?? throw new InvalidOperationException("published Desktop did not start");
        var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        try
        {
            var path = new char[32768]; var length = path.Length;
            Require(QueryFullProcessImageNameW(process.SafeHandle, 0, path, ref length), "external OS image query must succeed");
            var osPath = new string(path, 0, length);
            while (!process.HasExited)
            {
                // Legacy self-test legitimately invokes a fixed Mock Broker child.
                // The identity-only route must never create any same-EXE child.
                if (extra == "--self-test-exe-identity")
                {
                    var peers = Process.GetProcessesByName("Picotoo Pet AI");
                    try { Require(peers.All(p => p.Id == process.Id), "unexpected Desktop/Worker process"); }
                    finally { foreach (var peer in peers) peer.Dispose(); }
                }
                await Task.Delay(20, deadline.Token);
            }
            await process.WaitForExitAsync(deadline.Token);
            await Task.WhenAll(stdout, stderr).WaitAsync(deadline.Token);
            Require(process.ExitCode == 0 && File.Exists(report), "published self-test failed; inspect scoped JSON (raw stdout withheld)");
            RequireNoDesktop();
            return osPath;
        }
        finally { if (!process.HasExited) { process.Kill(true); await process.WaitForExitAsync(); } }
    }
    private static string Digest(string path) { using var file = File.OpenRead(path); return Convert.ToHexStringLower(SHA256.HashData(file)); }
    private static void RequireNoDesktop()
    {
        var peers = Process.GetProcessesByName("Picotoo Pet AI");
        try { Require(peers.Length == 0, "no existing or surviving Desktop/Worker"); }
        finally { foreach (var peer in peers) peer.Dispose(); }
    }
    private static void Require(bool condition, string message)
    {
        if (condition) return;
        // Only caller-owned fixed assertion text, never a raw exception/stdout body.
        Console.WriteLine("::error::" + message);
        throw new InvalidOperationException(message);
    }
#pragma warning disable SYSLIB1054
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryFullProcessImageNameW(SafeProcessHandle process, int flags, [Out] char[] path, ref int length);
#pragma warning restore SYSLIB1054
}
