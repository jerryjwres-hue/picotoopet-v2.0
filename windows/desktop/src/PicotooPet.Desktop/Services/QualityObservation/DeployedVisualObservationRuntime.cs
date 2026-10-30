using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Resources;
using System.Text.Json;

namespace PicotooPet.Desktop.Services.QualityObservation;

internal sealed class DeployedVisualObservationRuntime : IVisualObservationRuntime
{
    // Pins must be compiled into the trusted Desktop, never read from an arbitrary
    // sidecar supplied by Core/the operator. No approved deployment resource exists
    // yet: that is honestly UNVERIFIED, not permission to build/download at runtime.
    private sealed record ToolPin(string Name, string Sha256, long Bytes);
    private sealed record Deployment(string SchemaVersion, string SourceSha256, bool SelfContainedSingleFile,
        ToolPin[] Files, string? VlmEndpoint, string? VlmModel);
    private sealed class Leases : IDisposable
    {
        public List<VisualEvidenceFileLease> Files { get; } = [];
        public void Dispose() { foreach (var file in Files) file.Dispose(); }
    }
    public string ConfiguredOutputRoot()
    {
        var config = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ComfyUI", "config.json");
        if (!File.Exists(config)) throw new VisualObservationException("OUTPUT_ROOT_UNVERIFIED");
        using var pin = new VisualEvidenceFileLease(config);
        if (new FileInfo(config).Length > 65536) throw new VisualObservationException("OUTPUT_ROOT_UNVERIFIED");
        using var json = JsonDocument.Parse(File.ReadAllBytes(config));
        var value = json.RootElement.GetProperty("basePath").GetString();
        var root = LocalPath(value ?? "");
        var output = Path.Combine(root, "output");
        ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(output)!, output);
        if (!Directory.Exists(output)) throw new VisualObservationException("OUTPUT_ROOT_UNVERIFIED");
        pin.Recheck(); return output;
    }
    internal static string LocalPath(string path)
    {
        if (!Path.IsPathFullyQualified(path) || path.Length < 4 || path[1] != ':' || path[2] != '\\'
            || path.StartsWith(@"\\", StringComparison.Ordinal) || path.Contains('/', StringComparison.Ordinal)
            || path[3..].Contains(':', StringComparison.Ordinal)
            || !string.Equals(path, Path.GetFullPath(path), StringComparison.OrdinalIgnoreCase))
            throw new VisualObservationException("OUTPUT_ROOT_UNVERIFIED");
        var drive = new DriveInfo(Path.GetPathRoot(path)!);
        if (drive.DriveType != DriveType.Fixed || drive.DriveFormat != "NTFS") throw new VisualObservationException("OUTPUT_ROOT_UNVERIFIED");
        return Path.TrimEndingDirectorySeparator(path);
    }
    public VisualObserverDeployment OpenDeployment()
    {
        var resources = new ResourceManager("PicotooPet.Desktop.Services.QualityObservation.ObserverDeployment", typeof(DeployedVisualObservationRuntime).Assembly);
        string? raw;
        try { raw = resources.GetString("Receipt", CultureInfo.InvariantCulture); }
        catch (MissingManifestResourceException) { throw new VisualObservationException("OBSERVER_NOT_DEPLOYED"); }
        if (raw is null || raw.Length > 16384) throw new VisualObservationException("OBSERVER_NOT_DEPLOYED");
        var d = JsonSerializer.Deserialize<Deployment>(raw, VisualReviewObservation.Json)
            ?? throw new VisualObservationException("OBSERVER_NOT_DEPLOYED");
        if (d.SchemaVersion != "visual_review.deployment.v1" || !d.SelfContainedSingleFile
            || !VisualReviewObservation.IsSha(d.SourceSha256) || d.Files is null || d.Files.Length != 3)
            throw new VisualObservationException("OBSERVER_NOT_DEPLOYED");
        var expected = new HashSet<string>(StringComparer.Ordinal) { "PicotooPet.VisualReview.exe", "ffmpeg.exe", "ffprobe.exe" };
        var root = LocalPath(Path.Combine(AppContext.BaseDirectory, "tools", "p0_visual_review"));
        var pins = new Leases();
        try
        {
            foreach (var file in d.Files)
            {
                if (!expected.Remove(file.Name) || !VisualReviewObservation.IsSha(file.Sha256) || file.Bytes <= 0)
                    throw new VisualObservationException("OBSERVER_NOT_DEPLOYED");
                var path = Path.Combine(root, file.Name);
                var pin = new VisualEvidenceFileLease(path); pins.Files.Add(pin);
                if (new FileInfo(path).Length != file.Bytes || ProductionLocalEnvironment.Sha256FileAsync(path, CancellationToken.None).GetAwaiter().GetResult() != file.Sha256)
                    throw new VisualObservationException("OBSERVER_NOT_DEPLOYED");
                pin.Recheck();
            }
            if (d.VlmEndpoint is not null || d.VlmModel is not null) ValidateVlm(d.VlmEndpoint, d.VlmModel);
            return new(Path.Combine(root, "PicotooPet.VisualReview.exe"), Path.Combine(root, "ffprobe.exe"),
                Path.Combine(root, "ffmpeg.exe"), d.SourceSha256, d.VlmEndpoint, d.VlmModel, pins);
        }
        catch { pins.Dispose(); throw; }
    }
    private static void ValidateVlm(string? value, string? model)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme != "http" || uri.AbsolutePath != "/"
            || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0 || string.IsNullOrWhiteSpace(model)
            || !IPAddress.TryParse(uri.Host, out var ip) || ip.AddressFamily != System.Net.Sockets.AddressFamily.InterNetwork)
            throw new VisualObservationException("VLM_NOT_CONFIGURED");
        var b = ip.GetAddressBytes();
        if (!(b[0] == 10 || b[0] == 192 && b[1] == 168 || b[0] == 172 && b[1] is >= 16 and <= 31))
            throw new VisualObservationException("VLM_NOT_CONFIGURED");
        // Full model/protocol validation and all HTTP remain in the existing CLI.
    }
    public string CreateEvidenceRun()
    {
        var local = LocalPath(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData));
        var parent = Path.Combine(local, "PicotooPetV2", "QualityObservation");
        ProductionLocalEnvironment.AssertNoLinkEscape(local, parent);
        Directory.CreateDirectory(parent);
        using var pin = new PicotooPet.Desktop.Services.ProductionReference.WorkerKeyNamespace(parent);
        var run = Path.Combine(parent, Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(run); return run;
    }
    public async Task<int> RunAsync(VisualObserverDeployment d, string input, string root, string output, bool transferFrames, CancellationToken ct)
    {
        var info = new ProcessStartInfo(d.Observer) { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = Path.GetDirectoryName(d.Observer)! };
        foreach (var arg in new[] { input, root, output, d.Ffprobe, d.Ffmpeg }) info.ArgumentList.Add(arg);
        if (transferFrames)
        {
            ValidateVlm(d.VlmEndpoint, d.VlmModel);
            foreach (var arg in new[] { "--allow-lan-vlm", d.VlmEndpoint!, d.VlmModel!, "--consent" }) info.ArgumentList.Add(arg);
        }
        foreach (var key in info.Environment.Keys.Where(k => k.StartsWith("DOTNET_", StringComparison.OrdinalIgnoreCase)
            || k.StartsWith("COMPlus_", StringComparison.OrdinalIgnoreCase) || k.StartsWith("CORECLR_", StringComparison.OrdinalIgnoreCase)
            || k.StartsWith("COR_", StringComparison.OrdinalIgnoreCase)).ToArray()) info.Environment.Remove(key);
        info.Environment["DOTNET_EnableDiagnostics"] = "0";
        ct.ThrowIfCancellationRequested();
        using var process = Process.Start(info) ?? throw new VisualObservationException("OBSERVER_FAILED");
        var stdout = DrainAsync(process.StandardOutput, ct); var stderr = DrainAsync(process.StandardError, ct);
        try
        {
            var exit = process.WaitForExitAsync(ct);
            var first = await Task.WhenAny(exit, stdout, stderr).ConfigureAwait(false);
            if (first.IsFaulted) await first.ConfigureAwait(false);
            await Task.WhenAll(exit, stdout, stderr).ConfigureAwait(false);
            return process.ExitCode;
        }
        finally
        {
            if (!process.HasExited) { process.Kill(true); await process.WaitForExitAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5), CancellationToken.None).ConfigureAwait(false); }
        }
    }
    private static async Task DrainAsync(StreamReader reader, CancellationToken ct)
    {
        var buffer = new char[4096]; var total = 0;
        int n;
        while ((n = await reader.ReadAsync(buffer, ct).ConfigureAwait(false)) != 0)
            if ((total += n) > 65536) throw new VisualObservationException("OBSERVER_OUTPUT_LIMIT");
        // Never forward raw tool/model stdout/stderr into the WPF UI or logs.
    }
}
