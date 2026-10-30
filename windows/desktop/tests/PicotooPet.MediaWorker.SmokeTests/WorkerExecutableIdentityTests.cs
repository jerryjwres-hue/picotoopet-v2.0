using System.IO;
using System.Diagnostics;
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
    internal static async Task<bool> RunAsync(string[] args)
    {
        var probe = args.Length == 1 && args[0] == "--exe-identity-process-probe";
        if (args.Length != 0 && !probe) return false;
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("CI") != "true")
            throw new InvalidOperationException("EXE_IDENTITY_REQUIRES_NATIVE_DISPOSABLE_CI");
        if (probe)
        {
            try { using var accepted = await CoreWorkerChallengeClient.MeasureProcessImageAsync(CancellationToken.None); }
            catch (InvalidDataException e) when (e.Message.StartsWith("WORKER_EXE_", StringComparison.Ordinal))
            {
                Console.WriteLine("P0_GENERIC_PROCESS_MEASUREMENT_DENIED=" + e.Message);
                return true;
            }
            throw new InvalidOperationException("generic or renamed muxer was accepted as a current apphost");
        }
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
        // A file-only helper cannot establish running-process role. Test the
        // actual process entrypoint in children, including a colocated renamed
        // muxer (same filename/directory as entry DLL, not a cosmetic path test).
        var runtime = new DirectoryInfo(System.Runtime.InteropServices.RuntimeEnvironment.GetRuntimeDirectory());
        var dotnetRoot = runtime.Parent!.Parent!.Parent!.FullName;
        await ProbeProcessAsync(System.IO.Path.Combine(dotnetRoot, "dotnet.exe"), Assembly.GetExecutingAssembly().Location, false);
        var probeRoot = System.IO.Path.Combine(root, "muxer-process"); Directory.CreateDirectory(probeRoot);
        try
        {
            foreach (var input in Directory.EnumerateFiles(AppContext.BaseDirectory))
                if (System.IO.Path.GetExtension(input) is ".dll" or ".json")
                    File.Copy(input, System.IO.Path.Combine(probeRoot, System.IO.Path.GetFileName(input)));
            Directory.CreateSymbolicLink(System.IO.Path.Combine(probeRoot, "host"), System.IO.Path.Combine(dotnetRoot, "host"));
            Directory.CreateSymbolicLink(System.IO.Path.Combine(probeRoot, "shared"), System.IO.Path.Combine(dotnetRoot, "shared"));
            var renamedHost = System.IO.Path.Combine(probeRoot, "PicotooPet.MediaWorker.SmokeTests.exe");
            File.Copy(System.IO.Path.Combine(dotnetRoot, "dotnet.exe"), renamedHost);
            await ProbeProcessAsync(renamedHost, System.IO.Path.Combine(probeRoot, "PicotooPet.MediaWorker.SmokeTests.dll"), true);
        }
        finally
        {
            // Delete only CI-owned directory links, never follow them into SDK.
            foreach (var link in new[] { "host", "shared" })
                if (Directory.Exists(System.IO.Path.Combine(probeRoot, link))) Directory.Delete(System.IO.Path.Combine(probeRoot, link));
        }
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
        return false;
    }
    private static async Task ProbeProcessAsync(string executable, string assembly, bool renamed)
    {
        var info = new ProcessStartInfo(executable) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
        info.ArgumentList.Add(assembly); info.ArgumentList.Add("--exe-identity-process-probe");
        using var process = Process.Start(info) ?? throw new InvalidOperationException("could not start CI-only host probe");
        var output = process.StandardOutput.ReadToEndAsync(); var errors = process.StandardError.ReadToEndAsync();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        try { await process.WaitForExitAsync(deadline.Token); }
        catch { process.Kill(entireProcessTree: true); throw; }
        var text = await output + await errors;
        if (process.ExitCode == 0 && text.Contains("P0_GENERIC_PROCESS_MEASUREMENT_DENIED=WORKER_EXE_", StringComparison.Ordinal))
        {
            Console.WriteLine(renamed ? "P0_RENAMED_MUXER_RUNNING_PROCESS=DENIED" : "P0_GENERIC_DOTNET_RUNNING_PROCESS=DENIED");
            return;
        }
        // Some muxer versions themselves prohibit renaming before CLR entry.
        // Report that distinct boundary honestly; arbitrary startup failures fail.
        if (renamed && process.ExitCode != 0 && text.Contains("cannot execute dotnet when renamed", StringComparison.OrdinalIgnoreCase))
        {
            Console.WriteLine("P0_RENAMED_MUXER_RUNTIME_REFUSED=PASS; MANAGED_MEASUREMENT=UNREACHED");
            return;
        }
        throw new InvalidOperationException("CI process identity probe did not prove rejection: " + text);
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
