using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;

namespace PicotooPet.Desktop.Services;

public sealed record FluxDraftResult(string OutputRoot, IReadOnlyList<string> ManifestPaths);

public interface IFluxDraftGateway
{
    Task<FluxDraftResult> GenerateFluxDraftAsync(string creativeJobId, string packageId,
        string packageDigest, string? shotId, CancellationToken cancellationToken);
}

/// <summary>Explicit local creative draft execution using the deployed FLUX bridge.</summary>
internal static class FluxDraftExecution
{
    private const string Python = @"D:\opc in D\AI\ComfyUI\standalone-env\python.exe";
    private const string Lora = @"D:\opc in D\AI\ComfyUI\ComfyUI\models\loras\maotai_lora_v2.safetensors";

    internal static async Task<FluxDraftResult> GenerateAsync(ControlCenterSession session,
        string creativeJobId, string packageId, string packageDigest, string? shotId, CancellationToken ct)
    {
        if (!Guid.TryParseExact(creativeJobId, "D", out var jobId) || jobId == Guid.Empty
            || !Guid.TryParseExact(packageId, "D", out var id) || id == Guid.Empty
            || packageDigest.Length != 64 || packageDigest.Any(ch => ch is not (>= 'a' and <= 'f') and not (>= '0' and <= '9'))
            || (shotId is not null && (shotId.Length is < 1 or > 80
                || shotId.Any(ch => !char.IsAsciiLetterOrDigit(ch) && ch is not ('_' or '-' or '.')))))
            throw new InvalidDataException("FLUX_DRAFT_CONTEXT_INVALID");

        // 01. One-time machine-local config. No executable, model or endpoint
        //     can be supplied by the UI, a creative package or the Core API.
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(local)) throw new InvalidDataException("FLUX_DRAFT_LOCAL_STATE_REQUIRED");
        var state = Path.Combine(local, "PicotooPetV2", "MediaWorker", "v1");
        var config = Path.Combine(state, "flux-draft.json");
        RequireFile(config);
        if (new FileInfo(config).Length is <= 0 or > 8192)
            throw new InvalidDataException("FLUX_DRAFT_CONFIG_INVALID");
        using var parsed = JsonDocument.Parse(await File.ReadAllTextAsync(config, ct).ConfigureAwait(false));
        var settings = parsed.RootElement;
        FinalVideoQaMediaProbe.RejectDuplicates(settings);
        if (settings.ValueKind != JsonValueKind.Object || settings.EnumerateObject().Count() != 2)
            throw new InvalidDataException("FLUX_DRAFT_CONFIG_INVALID");
        var runner = settings.GetProperty("runner_path").GetString() ?? "";
        var maps = settings.GetProperty("reference_map_root").GetString() ?? "";
        if (!MasterVideoPathPolicy.IsSafeLocalFullyQualified(maps))
            throw new InvalidDataException("FLUX_DRAFT_CONFIG_INVALID");
        var map = Path.Combine(maps, packageDigest + ".json");
        var script = Path.Combine(AppContext.BaseDirectory, "flux-tools", "scripts", "run_existing_flux_board_batch.py");
        foreach (var file in new[] { runner, map, Python, Lora, script }) RequireFile(file);

        // 02. Download exact existing Core package, not a local StoryPack or
        //     an edited prompt. Immutable package bytes are rechecked in Python.
        var package = await session.GetCreativePackageAsync(creativeJobId, ct).ConfigureAwait(false);
        if (package is null || package.CreativePackageId != packageId || package.PackageDigest != packageDigest
            || package.QualityOutcome != "PASS")
            throw new InvalidDataException("FLUX_DRAFT_CREATIVE_PACKAGE_CHANGED");
        var payload = await session.DownloadCreativePackageAsync(creativeJobId, ct).ConfigureAwait(false);
        if (Convert.ToHexStringLower(SHA256.HashData(payload)) != packageDigest)
            throw new InvalidDataException("FLUX_DRAFT_CREATIVE_BYTES_CHANGED");

        var root = Path.Combine(local, "PicotooPetV2", "FluxDrafts", packageDigest);
        var runs = Path.Combine(root, "runs");
        ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(runs)!, runs);
        Directory.CreateDirectory(runs);
        ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(runs)!, runs);
        var zip = Path.Combine(root, "creative-package.zip");
        if (!File.Exists(zip))
        {
            var temporary = zip + "." + Guid.NewGuid().ToString("N") + ".partial";
            try
            {
                await File.WriteAllBytesAsync(temporary, payload, ct).ConfigureAwait(false);
                File.Move(temporary, zip, false);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        RequireFile(zip);
        if (await ProductionLocalEnvironment.Sha256FileAsync(zip, ct).ConfigureAwait(false) != packageDigest)
            throw new InvalidDataException("FLUX_DRAFT_PACKAGE_CONFLICT");

        // 03. Keep a per-package monotonically increasing variant. The
        //     original script rejects existing destinations and holds the
        //     shared GPU lock; concurrent invocations fail rather than overwrite.
        var variant = Enumerable.Range(0, 10001).FirstOrDefault(number =>
            !Directory.Exists(Path.Combine(runs, $"v{number:D5}"))
            && !File.Exists(Path.Combine(runs, $"v{number:D5}")), -1);
        if (variant < 0) throw new InvalidDataException("FLUX_DRAFT_VARIANT_LIMIT");
        var destination = Path.Combine(runs, $"v{variant:D5}");
        var start = new ProcessStartInfo(Python)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(script)!
        };
        foreach (var arg in new[] { "-B", "-E", "-s", script, "--package", zip,
            "--package-sha256", packageDigest, "--reference-map", map, "--runner", runner,
            "--lora", Lora, "--run-dir", destination, "--variant",
            variant.ToString(System.Globalization.CultureInfo.InvariantCulture), "--execute" })
            start.ArgumentList.Add(arg);
        if (shotId is not null) { start.ArgumentList.Add("--shot"); start.ArgumentList.Add(shotId); }

        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(TimeSpan.FromMinutes(45));
        using var process = Process.Start(start) ?? throw new InvalidOperationException("FLUX_DRAFT_START_FAILED");
        try { await process.WaitForExitAsync(deadline.Token).ConfigureAwait(false); }
        catch (OperationCanceledException)
        {
            // 04. The Python marker deliberately survives uncertain cleanup;
            //     no follow-up GPU claim or automatic retry is authorized.
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
            throw;
        }
        if (process.ExitCode != 0)
            throw new InvalidOperationException("FLUX_DRAFT_EXECUTION_FAILED");
        var report = Path.Combine(destination, "keyframe-candidates.json");
        RequireFile(report);

        // 05. Preserve earlier alternatives. Load at most eight explicitly
        //     named complete reports into the existing image verification UI.
        var manifests = Enumerable.Range(0, variant + 1).Reverse()
            .Select(number => Path.Combine(runs, $"v{number:D5}", "keyframe-candidates.json"))
            .Where(File.Exists).Take(8).Reverse().ToArray();
        foreach (var manifest in manifests) RequireFile(manifest);
        return new(runs, Array.AsReadOnly(manifests));
    }

    private static void RequireFile(string path)
    {
        if (!MasterVideoPathPolicy.IsSafeLocalFullyQualified(path)
            || !ProductionLocalEnvironment.IsOrdinaryFile(path))
            throw new InvalidDataException("FLUX_DRAFT_LOCAL_FILE_REQUIRED");
        ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(path)!, path);
    }
}
