using System.IO;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Org.BouncyCastle.Math.EC.Rfc8032;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class WorkerExecutableIdentityTests
{
    internal static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("CI") != "true")
            throw new InvalidOperationException("EXE_IDENTITY_REQUIRES_NATIVE_DISPOSABLE_CI");
        using var image = await CoreWorkerChallengeClient.MeasureProcessImageAsync(CancellationToken.None);
        var processPath = Environment.ProcessPath ?? throw new InvalidOperationException("missing smoke apphost");
        RecoveryTests.Assert(string.Equals(image.Path, processPath, StringComparison.OrdinalIgnoreCase) && image.Sha256 == await ProductionLocalEnvironment.Sha256FileAsync(processPath, CancellationToken.None), "actual Windows smoke-host EXE bytes");
        RecoveryTests.Assert(System.IO.Path.GetFileName(processPath) == "PicotooPet.MediaWorker.SmokeTests.exe"
            && image.Sha256 != await ProductionLocalEnvironment.Sha256FileAsync(typeof(ProtectedWorkerSigningKey).Assembly.Location, CancellationToken.None), "apphost EXE differs from Desktop DLL");
        await image.RequireCurrentAsync(CancellationToken.None);
        using var f = new DurableReferenceSnapshotTests.Fixture();
        using var snapshot = await f.PrepareAsync();
        var keyRoot = System.IO.Path.Combine(f.Root, "exe-identity-key");
        var identity = ProtectedWorkerSigningKey.Create(keyRoot, "windows-same-exe-worker");
        var now = DateTimeOffset.UtcNow;
        using var challenge = JsonDocument.Parse(JsonSerializer.Serialize(new { nonce = new string('2', 64),
            issued_at = Stamp(now), expires_at = Stamp(now.AddSeconds(28)) }));
        var build = typeof(CoreWorkerChallengeClient).GetMethod("BuildWitnessAsync", BindingFlags.NonPublic | BindingFlags.Static)!;
        var witness = await (Task<JsonObject>)build.Invoke(null, [f.Plan, f.Digest, "windows-same-exe-worker", identity.KeyId,
            challenge.RootElement, new[] { snapshot }, image, CancellationToken.None])!;
        var unsigned = JsonSerializer.SerializeToElement(witness);
        var payload = WorkerWitnessEncoding.Payload(unsigned);
        RecoveryTests.Assert(unsigned.GetProperty("worker_executable_sha256").GetString() == image.Sha256
            && Encoding.UTF8.GetString(payload).Contains("\"worker_executable_sha256\":\"" + image.Sha256 + "\"", StringComparison.Ordinal), "exact EXE digest in canonical signed bytes");
        var key = ProtectedWorkerSigningKey.Open(keyRoot, "windows-same-exe-worker", identity.Fingerprint);
        var changed = JsonNode.Parse(witness.ToJsonString())!;
        changed["worker_executable_sha256"] = await ProductionLocalEnvironment.Sha256FileAsync(typeof(ProtectedWorkerSigningKey).Assembly.Location, CancellationToken.None);
        var substituted = JsonSerializer.SerializeToElement(changed);
        await DeniedAsync(async () => { await key.SignMeasuredAsync(substituted, f.Plan, [snapshot], f.Journal, DateTimeOffset.UtcNow, CancellationToken.None); });
        RecoveryTests.Assert(!Directory.EnumerateFiles(keyRoot, "used-*").Any(), "DLL substitution denied before nonce marker");
        var signature = Convert.FromHexString(await key.SignMeasuredAsync(unsigned, f.Plan, [snapshot], f.Journal, DateTimeOffset.UtcNow, CancellationToken.None));
        var pub = Convert.FromHexString(identity.PublicKeyHex);
        RecoveryTests.Assert(Ed25519.Verify(signature, 0, pub, 0, payload, 0, payload.Length), "real DPAPI Ed25519 signature binds actual EXE canonical bytes");
        witness["signature"] = Convert.ToHexStringLower(signature);
        RecoveryTests.Assert(payload.SequenceEqual(WorkerWitnessEncoding.Payload(JsonSerializer.SerializeToElement(witness))), "signature field does not alter canonical signed EXE bytes");
        var altered = WorkerWitnessEncoding.Payload(substituted);
        RecoveryTests.Assert(!Ed25519.Verify(signature, 0, pub, 0, altered, 0, altered.Length), "DLL substitution changes signed bytes");
        var markers = Directory.GetFiles(keyRoot, "used-*");
        RecoveryTests.Assert(markers.Length == 1 && f.Journal.Pending().Count == 0, "one nonce reservation, no attempt");
        await DeniedAsync(async () => { await key.SignMeasuredAsync(unsigned, f.Plan, [snapshot], f.Journal, DateTimeOffset.UtcNow, CancellationToken.None); });
        RecoveryTests.Assert(Directory.GetFiles(keyRoot, "used-*").Length == 1, "replay never creates another reservation");
        var root = System.IO.Path.Combine(f.Root, "image-inputs"); Directory.CreateDirectory(root);
        foreach (var file in new[] { "missing.exe", "not-pe.exe", "fake-mz.exe", "dotnet.exe", "managed-as-exe.exe", "library.dll", "alias.exe" })
        {
            var path = System.IO.Path.Combine(root, file);
            if (file == "not-pe.exe") File.WriteAllText(path, "not an executable");
            if (file == "fake-mz.exe") File.WriteAllBytes(path, "MZnot-a-PE"u8.ToArray());
            if (file is "library.dll" or "managed-as-exe.exe") File.Copy(typeof(ProtectedWorkerSigningKey).Assembly.Location, path);
            if (file == "dotnet.exe") File.Copy(processPath, path);
            if (file == "alias.exe") File.CreateSymbolicLink(path, processPath);
            await DeniedAsync(async () => { using var unused = await OpenCandidateAsync(path); });
        }
        // Renaming a muxer must not turn it into a paired apphost. This is a
        // negative file-source test, not a claim that metadata proves authenticity.
        var runtime = new DirectoryInfo(System.Runtime.InteropServices.RuntimeEnvironment.GetRuntimeDirectory());
        var dotnet = System.IO.Path.Combine(runtime.Parent!.Parent!.Parent!.FullName, "dotnet.exe");
        var renamedHost = System.IO.Path.Combine(root, "PicotooPet.MediaWorker.SmokeTests.exe");
        File.Copy(dotnet, renamedHost);
        await DeniedAsync(async () => { using var unused = await OpenCandidateAsync(renamedHost); });
        var copy = System.IO.Path.Combine(root, "copy.exe"); File.Copy(processPath, copy);
        using (var pinned = await OpenCandidateAsync(copy))
        {
            await DeniedAsync(() => { File.WriteAllBytes(copy, [0]); return Task.CompletedTask; });
            await DeniedAsync(() => { File.Delete(copy); return Task.CompletedTask; });
            await pinned.VerifyFileAsync(CancellationToken.None);
            await DeniedAsync(() => pinned.RequireCurrentAsync(CancellationToken.None));
        }
        File.WriteAllBytes(copy, [0]);
        await DeniedAsync(async () => { using var unused = await OpenCandidateAsync(copy); });
        RecoveryTests.Assert(Directory.GetFiles(keyRoot, "used-*").Length == 1 && f.Journal.Pending().Count == 0, "all executable-source refusals add no nonce reservation or attempt");
        Console.WriteLine("P0_ACTUAL_SMOKE_EXE_DIGEST=PASS; CANONICAL_PAYLOAD=PASS; CORRECTED_SIGNER_INTEGRATION=PASS; NONCE=1; CLAIM=0; COMFY_POST=0");
        Console.WriteLine("P0_PUBLISHED_DESKTOP_RUNNING_IMAGE=UNVERIFIED (no shipping EXE test entrypoint; no release attestation)");
    }
    private static async Task<CoreWorkerChallengeClient.ProcessImageMeasurement> OpenCandidateAsync(string path)
    {
        var method = typeof(CoreWorkerChallengeClient).GetMethod("OpenExecutableFileAsync", BindingFlags.Static | BindingFlags.NonPublic)!;
        return await (Task<CoreWorkerChallengeClient.ProcessImageMeasurement>)method.Invoke(null, [path, CancellationToken.None])!;
    }
    private static async Task<Exception> DeniedAsync(Func<Task> action)
    {
        try { await action(); }
        catch (Exception e) when (e is IOException or InvalidDataException or UnauthorizedAccessException or BadImageFormatException or System.ComponentModel.Win32Exception) { return e; }
        throw new InvalidOperationException("unverifiable executable must be denied");
    }
    private static string Stamp(DateTimeOffset value) => value.ToString("yyyy-MM-ddTHH:mm:ss.ffffff'Z'", System.Globalization.CultureInfo.InvariantCulture);
}
