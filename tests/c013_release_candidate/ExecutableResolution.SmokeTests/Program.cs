using System.Diagnostics;
using PicotooPet.Desktop.Services;

// Native Windows SECURITY NEGATIVE: on the actual C013 production assembly,
// CreateProcessW must never resolve an attacker-writable current-directory
// shadow instead of the intended ffprobe executable.
// The shadow is only a harmless copy of Microsoft's cmd.exe, invoked to echo a
// unique marker. No untrusted code or downloaded executable is introduced.
if (!OperatingSystem.IsWindows())
{
    Console.Error.WriteLine("C013_EXEC_PROVENANCE=UNVERIFIED_NON_WINDOWS");
    return 2;
}
var runner = new FixedMasterVideoProcessRunner();
var baseline = new ProcessStartInfo
{
    FileName = FixedMasterVideoProcessRunner.Ffprobe,
    UseShellExecute = false,
    CreateNoWindow = true
};
baseline.ArgumentList.Add("-version");
var healthy = await runner.RunAsync(baseline, TimeSpan.FromSeconds(20), CancellationToken.None);
if (healthy.TimedOut || healthy.CleanupIncomplete || healthy.ExitCode != 0 ||
    !healthy.Stdout.Contains("ffprobe version", StringComparison.OrdinalIgnoreCase))
{
    Console.Error.WriteLine("C013_EXEC_PROVENANCE=BLOCKED_REAL_FFPROBE_BASELINE");
    return 2;
}
var original = Environment.CurrentDirectory;
var root = Path.Combine(Path.GetTempPath(), "c013-exec-provenance-" + Guid.NewGuid().ToString("N"));
var shadow = Path.Combine(root, "untrusted-parent-current-directory");
var safeChildDirectory = Path.Combine(root, "separate-child-working-directory");
Directory.CreateDirectory(shadow);
Directory.CreateDirectory(safeChildDirectory);
try
{
    File.Copy(Path.Combine(Environment.SystemDirectory, "cmd.exe"), Path.Combine(shadow, "ffprobe.exe"));
    Environment.CurrentDirectory = shadow;
    var start = new ProcessStartInfo
    {
        FileName = FixedMasterVideoProcessRunner.Ffprobe,
        UseShellExecute = false,
        CreateNoWindow = true,
        WorkingDirectory = safeChildDirectory
    };
    start.ArgumentList.Add("/c");
    start.ArgumentList.Add("echo");
    start.ArgumentList.Add("C013_SHADOW_EXECUTABLE_EXECUTED");
    var result = await runner.RunAsync(start, TimeSpan.FromSeconds(20), CancellationToken.None);
    var hijacked = result.Stdout.Contains("C013_SHADOW_EXECUTABLE_EXECUTED", StringComparison.Ordinal);
    Console.WriteLine($"C013_EXEC_PROVENANCE_OBSERVED_SHADOW={hijacked} exit={result.ExitCode} cleanup_incomplete={result.CleanupIncomplete}");
    if (hijacked)
    {
        Console.Error.WriteLine("C013_EXEC_PROVENANCE=FAIL_UNTRUSTED_PARENT_CWD_BINARY_EXECUTED");
        return 1;
    }
    // Secure resolution should not run the shadow binary; this test does NOT
    // substitute for content hashing/signature validation of the resolved exe.
    Console.WriteLine("C013_EXECUTABLE_PROVENANCE=PASS");
    return 0;
}
finally
{
    Environment.CurrentDirectory = original;
    try { Directory.Delete(root, true); }
    catch (IOException) { }
    catch (UnauthorizedAccessException) { }
}
