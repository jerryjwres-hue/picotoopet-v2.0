using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Services;

/// <summary>Local FLUX installation resolved from the verified historical runner.</summary>
internal sealed record FluxRunnerInstallation(string RunnerPath, string ComfyRoot, string Python, string Lora);

/// <summary>
/// P0-A: the ComfyUI root and its Python are read ONLY from the SHA-pinned
/// historical runner (its own <c>COMFY</c> / <c>PY</c> constants). The desktop
/// keeps no second hard-coded machine path that could disagree with the runner
/// it launches. The same digests are pinned in scripts/prepare_existing_flux_board_shot.py.
/// </summary>
internal static class FluxRunnerLocalPaths
{
    internal const string PinnedRunnerSha256 = "fba9b6f004871664c92c75f1c36170a17ceef89b47f3a2c71032df472405d2bd";
    internal const string LoraV2Sha256 = "5972e7f782e3e4ed16b764441fdb66d638cb6a8ba85fb8226d95feeb98e8eb70";
    internal const string LoraFileName = "maotai_lora_v2.safetensors";

    private static readonly Regex PathLine = new(@"^(COMFY|PY) = Path\(r""([^""\r\n]+)""\)\s*$",
        RegexOptions.Multiline | RegexOptions.CultureInvariant, TimeSpan.FromSeconds(1));

    internal static FluxRunnerInstallation Resolve(string runnerPath)
    {
        var info = new FileInfo(runnerPath);
        if (!info.Exists || info.Length is <= 0 or > 128_000)
            throw new InvalidDataException("FLUX_DRAFT_RUNNER_CHANGED");
        var raw = File.ReadAllBytes(runnerPath);
        if (Convert.ToHexStringLower(SHA256.HashData(raw)) != PinnedRunnerSha256)
            throw new InvalidDataException("FLUX_DRAFT_RUNNER_CHANGED");
        var (comfy, python) = ParseRunnerPaths(Encoding.UTF8.GetString(raw));
        return new(runnerPath, comfy, python, Path.Combine(comfy, "models", "loras", LoraFileName));
    }

    internal static (string ComfyRoot, string Python) ParseRunnerPaths(string source)
    {
        var comfy = new List<string>();
        var python = new List<string>();
        foreach (Match match in PathLine.Matches(source))
            (match.Groups[1].Value == "COMFY" ? comfy : python).Add(match.Groups[2].Value);
        if (comfy.Count != 1 || python.Count != 1
            || !IsWindowsFullyQualified(comfy[0]) || !IsWindowsFullyQualified(python[0]))
            throw new InvalidDataException("FLUX_DRAFT_RUNNER_PATHS_INVALID");
        return (comfy[0], python[0]);
    }

    private static bool IsWindowsFullyQualified(string path) =>
        path.Length >= 3 && char.IsAsciiLetter(path[0]) && path[1] == ':' && path[2] == '\\';
}
