using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Security;

namespace PicotooPet.QualityObservation.Tests;

// Test-only registration, following the repository's existing ModuleInitializer
// smoke pattern. No production initializer, project edit or user-machine SDK run.
internal static class NativeVisualObservationBridge
{
    [ModuleInitializer]
    internal static void Run()
    {
        var frames = new HashSet<string>(StringComparer.Ordinal) { "frame_01.png", "frame_04.png", "frame_07.png" };
        foreach (var raw in new[]
        {
            """{"flags":[],"reviewer_disagreement":false,"status":"ACCEPT"}""",
            """{"flags":[{"shot_order":2,"category":"floating_object","severity":"high","evidence_filename":"frame_07.png","rationale":"synthetic mismatch","confidence":0.9}],"reviewer_disagreement":false}""",
        })
        {
            var denied = false;
            try { _ = ReviewPolicy.ParseAdvisory(raw, frames); } catch (InvalidOperationException) { denied = true; }
            if (!denied) throw new InvalidOperationException("model injection/frame association must be rejected");
        }
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("GITHUB_ACTIONS") != "true"
            || Environment.GetEnvironmentVariable("CI") != "true") return;
        var workspace = Environment.GetEnvironmentVariable("GITHUB_WORKSPACE") ?? throw new InvalidOperationException("native workspace missing");
        var temporary = Environment.GetEnvironmentVariable("RUNNER_TEMP") ?? throw new InvalidOperationException("native temporary root missing");
        var root = Path.Combine(temporary, "visual-observation-wpf-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        var project = SecurityElement.Escape(Path.Combine(workspace, "windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj"));
        File.WriteAllText(Path.Combine(root, "Native.csproj"), $"""
        <Project Sdk="Microsoft.NET.Sdk">
          <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0-windows10.0.19041.0</TargetFramework>
          <UseWPF>true</UseWPF><Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings><TreatWarningsAsErrors>true</TreatWarningsAsErrors></PropertyGroup>
          <ItemGroup><ProjectReference Include="{project}" /></ItemGroup>
        </Project>
        """);
        File.Copy(Path.Combine(workspace, "windows/desktop/tests/PicotooPet.QualityObservation.SmokeTests/Fixtures/NativeVisualObservation.cs.txt"), Path.Combine(root, "Program.cs"));
        var start = new ProcessStartInfo("dotnet") { UseShellExecute = false, WorkingDirectory = Path.Combine(workspace, "windows/desktop") };
        foreach (var arg in new[] { "run", "--project", Path.Combine(root, "Native.csproj"), "-c", "Release" }) start.ArgumentList.Add(arg);
        using var process = Process.Start(start) ?? throw new InvalidOperationException("native WPF harness failed to start");
        if (!process.WaitForExit(240000)) { process.Kill(true); throw new InvalidOperationException("native WPF harness timeout"); }
        if (process.ExitCode != 0) throw new InvalidOperationException("native WPF visual observation contracts failed");
        Console.WriteLine("P0_Q2_PRODUCTION_PANEL_NATIVE=PASS; SYNTHETIC_ADAPTER=PASS; REAL_VISUAL_ACCURACY=UNVERIFIED");
    }
}
