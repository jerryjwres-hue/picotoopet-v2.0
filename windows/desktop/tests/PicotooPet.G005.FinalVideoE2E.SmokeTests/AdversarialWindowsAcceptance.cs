using System;
using System.Buffers.Binary;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using PicotooPet.Desktop.Services;
using PicotooPet.FinalVideoQa.SmokeTests;

namespace PicotooPet.G005.FinalVideoE2E;

/// <summary>G005-owned native adversarial acceptance; never a synthetic PASS or production hook.</summary>
internal static class AdversarialWindowsAcceptance
{
    private static void Assert(bool value, string why) => Program.Check(value, "NATIVE_" + why);
    private static string Hash(string path) =>
        Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();

    private static Process LaunchChild(string mode, string control, string? isolatedPath = null)
    {
        var processExe = Environment.ProcessPath ?? throw new InvalidOperationException("DOTNET_HOST_UNKNOWN");
        var assembly = typeof(Program).Assembly.Location;
        var start = new ProcessStartInfo(processExe)
        {
            UseShellExecute = false, CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(control)!,
            RedirectStandardOutput = false, RedirectStandardError = false,
        };
        start.ArgumentList.Add(assembly);
        start.ArgumentList.Add(mode);
        start.ArgumentList.Add(control);
        if (isolatedPath is not null)
            start.Environment["PATH"] = isolatedPath;
        var process = Process.Start(start) ?? throw new InvalidOperationException("CHILD_START_FAILED");
        Assert(process.Id > 0 && !process.HasExited, "CONTROLLED_CHILD_PID");
        return process;
    }

    private static async Task<string> WaitForFile(string file, Process child, TimeSpan timeout)
    {
        var until = DateTimeOffset.UtcNow + timeout;
        while (DateTimeOffset.UtcNow < until)
        {
            if (File.Exists(file))
            {
                try
                {
                    var value = await File.ReadAllTextAsync(file);
                    if (value.Length > 0) return value;
                }
                catch (IOException) { }
            }
            if (child.HasExited) throw new InvalidOperationException("CHILD_EXITED_BEFORE_SIGNAL");
            await Task.Delay(15);
        }
        throw new TimeoutException("REAL_CHILD_SIGNAL_TIMEOUT");
    }

    public static async Task<int> AtomicChild(string signal)
    {
        using var f = await Fixture.CreateAsync(true, false);
        // Serialize the *actual C009A input* for a different process to recover.
        var payload = new AtomicPayload(f.Root, f.Input);
        var snapshot = signal + ".input.json";
        await File.WriteAllTextAsync(snapshot, JsonSerializer.Serialize(payload));
        var service = new PostProductionMasterCompositorService(new PausingComposer(signal),
            Path.Combine(f.Root, "finals"), Path.Combine(f.Root, "narration"),
            Path.Combine(f.Root, "overlays"), f.MasterRoot, TimeProvider.System);
        // This call is intentionally terminated by external OS Process.Kill().
        await service.ComposeAsync(f.Input);
        return 19; // reaching this indicates a broken adversarial fixture
    }

    private sealed record AtomicPayload(string Root, MasterCompositionInputV1 Input);

    private sealed class PausingComposer(string signal) : IMasterVideoComposer
    {
        public async Task ComposeAsync(MasterVideoCompositionRequest request, CancellationToken ct)
        {
            // Genuine C009A temporary output path, allocated by the production service.
            var visual = await File.ReadAllBytesAsync(request.Visual.Path, ct);
            await File.WriteAllBytesAsync(request.OutputPath,
                visual.Concat(Encoding.UTF8.GetBytes("|C009A_REAL_STAGED_MASTER|")).ToArray(), ct);
            await File.WriteAllTextAsync(signal, request.OutputPath, ct);
            await Task.Delay(Timeout.InfiniteTimeSpan, ct);
        }
    }

    public static async Task AtomicKillAndRecovery()
    {
        var staging = Path.Combine(Path.GetTempPath(), "g005-real-atomic-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(staging);
        var signal = Path.Combine(staging, "atomic-staged.txt");
        using var child = LaunchChild("--g005-atomic-child", signal);
        try
        {
            var outputPath = await WaitForFile(signal, child, TimeSpan.FromSeconds(25));
            var temp = Path.GetDirectoryName(outputPath)!;
            Assert(Path.GetFileName(temp).EndsWith(".tmp", StringComparison.Ordinal), "C009A_PRODUCTION_TEMP_DIRECTORY");
            Assert(File.Exists(outputPath) && new FileInfo(outputPath).Length > 0, "REAL_TEMP_MASTER_WRITTEN");
            Assert(!File.Exists(Path.Combine(temp, "master-manifest.json")), "PRE_MANIFEST_COMMIT_STAGE");
            Assert(Directory.Exists(temp), "C009A_UNCOMMITTED_DIRECTORY");
            var snapshot = JsonSerializer.Deserialize<AtomicPayload>(
                await File.ReadAllTextAsync(signal + ".input.json"))!;
            Assert(snapshot.Input.NarrationPlan.Plan.NarrationRequired, "REQUIRED_MASTER_NO_FALLBACK");
            // Actual bounded OS PID termination (not cancellation, throw, or temp deletion).
            var killedPid = child.Id;
            child.Kill(entireProcessTree: true);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            await child.WaitForExitAsync(deadline.Token);
            Assert(child.HasExited && child.Id == killedPid && child.ExitCode != 0,
                "CHILD_PROCESS_WAS_FORCE_KILLED");
            Assert(Directory.Exists(temp) && File.Exists(outputPath),
                "PROCESS_CRASH_LEFT_UNCOMMITTED_BYTES");
            var jobDir = Directory.GetParent(temp)!.FullName;
            Assert(Directory.GetDirectories(jobDir)
                .All(d => d.EndsWith(".tmp", StringComparison.OrdinalIgnoreCase)),
                "NO_PARTIAL_PUBLISHED_DIGEST_DIRECTORY");
            Assert(!Directory.Exists(Path.Combine(snapshot.Root, "receipts")),
                "KILLED_PROCESS_NO_QA_RECEIPT");
            var service = new PostProductionMasterCompositorService(new FixtureComposer(false),
                Path.Combine(snapshot.Root, "finals"), Path.Combine(snapshot.Root, "narration"),
                Path.Combine(snapshot.Root, "overlays"), Path.Combine(snapshot.Root, "master"), TimeProvider.System);
            var recovered = await service.ComposeAsync(snapshot.Input);
            Assert(recovered.Required && recovered.C004Fallback is null && recovered.Artifact is not null,
                "REAL_RESTART_COMMITS_C009_REQUIRED_ONLY");
            var master = recovered.Artifact!;
            Assert(File.Exists(master.FilePath) && File.Exists(master.ManifestPath),
                "ATOMIC_MASTER_AND_MANIFEST_PUBLISHED_TOGETHER");
            Assert(master.Sha256 == Hash(master.FilePath)
                && new FileInfo(master.FilePath).Length == master.Bytes,
                "RECOVERED_MASTER_SHA_AND_SIZE");
            Assert(Directory.GetFiles(Path.GetDirectoryName(master.FilePath)!).Length == 2,
                "COMMIT_EXACTLY_TWO_ARTIFACTS");
            var reused = await service.ComposeAsync(snapshot.Input);
            Assert(reused.Artifact?.Reused == true && reused.Artifact.Sha256 == master.Sha256,
                "EXACT_DURABLE_REUSE_AFTER_PROCESS_CRASH");
            Console.WriteLine("G005_REAL_KILLED_PID=" + killedPid);
            Console.WriteLine("G005_C009A_RECOVERED_SHA=" + master.Sha256);
        }
        finally
        {
            if (!child.HasExited) { child.Kill(entireProcessTree: true); await child.WaitForExitAsync(); }
            // Do not delete crash evidence until the complete assertion finishes; temp is isolated.
        }
    }

    private static async Task<(int Exit, byte[] Output)> Exec(string exe, string[] args, bool binary = false)
    {
        var start = new ProcessStartInfo(exe) {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        foreach (var arg in args) start.ArgumentList.Add(arg);
        using var p = Process.Start(start) ?? throw new InvalidOperationException("MEDIA_PROCESS_NOT_STARTED");
        using var output = new MemoryStream();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(35));
        var stdout = p.StandardOutput.BaseStream.CopyToAsync(output, deadline.Token);
        var stderr = p.StandardError.ReadToEndAsync(deadline.Token);
        try
        {
            await Task.WhenAll(stdout,stderr,p.WaitForExitAsync(deadline.Token));
        }
        catch (OperationCanceledException)
        {
            p.Kill(entireProcessTree:true); await p.WaitForExitAsync();
            throw new TimeoutException("NATIVE_FFMPEG_TIMEOUT");
        }
        var err = await stderr;
        if (p.ExitCode != 0) throw new InvalidDataException(
            "REAL_MEDIA_COMMAND_FAILED=" + p.ExitCode + ":" + err[..Math.Min(300, err.Length)]);
        return (p.ExitCode, output.ToArray());
    }

    private static Task<byte[]> DecodePcm(string path) => Decode(path);
    private static async Task<byte[]> Decode(string path)
    {
        var r = await Exec("ffmpeg.exe", new[] {
            "-hide_banner","-loglevel","error","-nostdin","-i",path,
            "-map","0:a:0","-ar","48000","-ac","1","-f","s16le","-"
        }, true);
        Assert(r.Output.Length > 48000 * 2, "REAL_AAC_DECODED_PCM");
        return r.Output;
    }
    private static double Rms(byte[] pcm, double from, double to)
    {
        const int sampleRate = 48000;
        var first = (int)(from * sampleRate);
        var last = (int)(to * sampleRate);
        if (pcm.Length < last * 2) throw new InvalidDataException("AAC_PCM_TOO_SHORT");
        double power = 0;
        for (var n = first; n < last; n++) {
            var sample = BinaryPrimitives.ReadInt16LittleEndian(pcm.AsSpan(n * 2, 2));
            power += (double)sample * sample;
        }
        return Math.Sqrt(power / (last - first));
    }

    public static async Task RealAacTimelineCorruption()
    {
        using var fixture = await Fixture.CreateAsync(true, false, wavFrames: 48000,
            narrationWindowMs: 1000, real: true);
        var wav = fixture.Input.NarrationArtifact!.Segments[0].WavPath;
        var bytes = await File.ReadAllBytesAsync(wav);
        // Audible tone in [0.12,0.48]s, otherwise truly silent native WAV.
        for (int i = (int)(0.12 * 48000); i < (int)(0.48 * 48000); i++)
        {
            short sample = (short)(12000 * Math.Sin(2 * Math.PI * 900 * i / 48000));
            BinaryPrimitives.WriteInt16LittleEndian(bytes.AsSpan(44 + i * 2, 2), sample);
        }
        await File.WriteAllBytesAsync(wav, bytes);
        var manifest = fixture.Input.NarrationArtifact.ManifestPath;
        var node = JsonNode.Parse(await File.ReadAllTextAsync(manifest))!.AsObject();
        node["segments"]![0]!["wav_sha256"] = Hash(wav);
        await File.WriteAllTextAsync(manifest, node.ToJsonString());
        var master = (await fixture.Service.ComposeAsync(fixture.Input)).Artifact
            ?? throw new InvalidOperationException("REAL_C009A_MASTER_MISSING");
        var baselineSha = Hash(master.FilePath);
        var baselinePcm = await DecodePcm(master.FilePath);
        var goodSound = Rms(baselinePcm, 0.20, 0.35);
        var goodSilence = Rms(baselinePcm, 0.90, 1.05);
        Assert(goodSound > 500 && goodSilence < 120, "BASELINE_TONE_AND_EXPECTED_SILENT_INTERVAL");

        var corrupt = Path.Combine(fixture.Root, "shifted-aac.mp4");
        // Real AAC re-encode: offset the narration +700ms, keep video bitstream and duration.
        await Exec("ffmpeg.exe", new[] {
            "-hide_banner","-loglevel","error","-nostdin","-y","-i",master.FilePath,
            "-map","0:v:0","-map","0:a:0","-c:v","copy",
            "-af","adelay=700|700,atrim=0:2.0,asetpts=N/SR/TB",
            "-c:a","aac","-b:a","160k","-ar","48000","-ac","1",
            "-movflags","+faststart", corrupt
        });
        var shiftedPcm = await DecodePcm(corrupt);
        var earlySilence = Rms(shiftedPcm, 0.20, 0.35);
        var misplacedSound = Rms(shiftedPcm, 0.90, 1.05);
        Assert(earlySilence < 120 && misplacedSound > 500,
            "ACTUAL_AAC_700MS_SHIFT_BREAKS_VOICE_AND_SILENCE_INTERVALS");
        Assert(Hash(corrupt) != baselineSha, "NATIVE_CORRUPTION_BYTES_DIFFER");
        var qa = LifecycleTests.Service(fixture, new FixedMasterVideoProcessRunner());
        var input = LifecycleTests.Input(fixture, master);
        var originalBytes = await File.ReadAllBytesAsync(master.FilePath);
        try
        {
            File.Copy(corrupt, master.FilePath, true);
            var denied = false;
            try { await qa.VerifyAsync(input); }
            catch (FinalVideoQaException e) {
                denied = e.Code is "FINAL_QA_ARTIFACT_INVALID" or "FINAL_QA_HASH_MISMATCH"
                    or "FINAL_QA_RECEIPT_CONFLICT";
                Console.WriteLine("G005_REAL_AAC_QA_REJECTION=" + e.Code);
            }
            Assert(denied, "REAL_AAC_MUTATION_REJECTED_BY_PRODUCTION_QA");
            Assert(!Directory.Exists(Path.Combine(fixture.Root,"receipts")),
                "CORRUPT_TIMELINE_NO_PASS_RECEIPT");
        }
        finally { await File.WriteAllBytesAsync(master.FilePath, originalBytes); }
        var approved = await qa.VerifyAsync(input);
        Assert(approved.Receipt.Outcome == "PASS" && approved.Receipt.ArtifactSha256 == baselineSha,
            "UNMODIFIED_REAL_AAC_STILL_QA_PASS");
        Console.WriteLine($"G005_REAL_AAC_RMS=baseline_voice:{goodSound:F1},baseline_silence:{goodSilence:F1},shifted_voice:{misplacedSound:F1}");
    }

    public static async Task<int> MissingBinaryChild(string signal)
    {
        var config = JsonSerializer.Deserialize<MissingPayload>(await File.ReadAllTextAsync(signal + ".input.json"))
            ?? throw new InvalidDataException("MISSING_INPUT");
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        if (path.Contains("ffmpeg", StringComparison.OrdinalIgnoreCase)
            || path.Contains("chocolatey", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("ISOLATED_PATH_NOT_RESTRICTED");
        if (IsExecutableDiscoverable("ffmpeg.exe") || IsExecutableDiscoverable("ffprobe.exe"))
            throw new InvalidOperationException("FFMPEG_UNEXPECTEDLY_DISCOVERABLE");
        var qa = new FinalVideoQaService(new FixedMasterVideoProcessRunner(),
            Path.Combine(config.Root, "finals"), Path.Combine(config.Root, "narration"),
            Path.Combine(config.Root, "overlays"), Path.Combine(config.Root, "master"),
            Path.Combine(config.Root, "receipts"), TimeProvider.System);
        string? code = null;
        try { await qa.VerifyAsync(config.Input); }
        catch (FinalVideoQaException e) { code = e.Code; }
        if (code is not ("FINAL_QA_PROBE_FAILED" or "FINAL_QA_PROBE_UNAVAILABLE"))
            throw new InvalidOperationException("MISSING_NATIVE_NOT_FAIL_CLOSED=" + code);
        if (Directory.Exists(Path.Combine(config.Root, "receipts")))
            throw new InvalidOperationException("MISSING_NATIVE_ISSUED_RECEIPT");
        await File.WriteAllTextAsync(signal, JsonSerializer.Serialize(new {
            pid=Environment.ProcessId, no_ffmpeg=true, no_ffprobe=true,
            qa_code=code, receipt=false, candidate_kind="c009_master_v1"
        }));
        return 0;
    }

    private sealed record MissingPayload(string Root, FinalVideoQaInputV1 Input);
    private static bool IsExecutableDiscoverable(string name)
    {
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var dir in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
            if (File.Exists(Path.Combine(dir.Trim('"'), name))) return true;
        return File.Exists(Path.Combine(Environment.CurrentDirectory, name));
    }

    public static async Task RealMissingExecutables()
    {
        using var fixture = await Fixture.CreateAsync(true, false, real: true);
        var master = (await fixture.Service.ComposeAsync(fixture.Input)).Artifact
            ?? throw new InvalidOperationException("MISSING_REAL_MASTER");
        Assert(master.HasAudio, "MISSING_BINARIES_TESTS_REQUIRED_MASTER");
        var root = Path.Combine(Path.GetTempPath(), "g005-real-missing-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var signal = Path.Combine(root, "missing.json");
        await File.WriteAllTextAsync(signal + ".input.json",
            JsonSerializer.Serialize(new MissingPayload(fixture.Root, LifecycleTests.Input(fixture, master))));
        var windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        var cleanPath = Path.Combine(windows,"System32") + Path.PathSeparator + windows;
        using var child = LaunchChild("--g005-missing-child", signal, cleanPath);
        try {
            var output = await WaitForFile(signal, child, TimeSpan.FromSeconds(25));
            using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            await child.WaitForExitAsync(cancellation.Token);
            Assert(child.ExitCode == 0, "MISSING_EXECUTABLE_CHILD_EXIT_SUCCESS_WITH_EXPECTED_REJECTION");
            using var result = JsonDocument.Parse(output);
            Assert(result.RootElement.GetProperty("pid").GetInt32() == child.Id,
                "REAL_SEPARATE_PID_MISSING_PATH");
            Assert(result.RootElement.GetProperty("no_ffmpeg").GetBoolean()
                && result.RootElement.GetProperty("no_ffprobe").GetBoolean(),
                "PATH_ISOLATED_BOTH_NATIVE_TOOLS_MISSING");
            Assert(result.RootElement.GetProperty("qa_code").GetString() is
                "FINAL_QA_PROBE_FAILED" or "FINAL_QA_PROBE_UNAVAILABLE",
                "C010A_REAL_MISSING_PROBE_CLOSED_CODE");
            Assert(!Directory.Exists(Path.Combine(fixture.Root, "receipts")),
                "NO_PASS_RECEIPT_WHEN_NATIVE_TOOL_MISSING");
            Assert(!Directory.EnumerateDirectories(fixture.MasterRoot,"*.tmp",SearchOption.AllDirectories).Any(),
                "NO_UNCOMMITTED_MASTER_TEMP_LEAK");
            Assert(master.Sha256 == Hash(master.FilePath),
                "ORIGINAL_REAL_MASTER_UNMODIFIED_BY_MISSING_TOOLS");
            // Parent's native environment remains intact: a fresh C010A QA succeeds.
            var approved = await LifecycleTests.Service(fixture,
                new FixedMasterVideoProcessRunner()).VerifyAsync(LifecycleTests.Input(fixture, master));
            Assert(approved.Receipt.Outcome == "PASS",
                "PARENT_NATIVE_ENVIRONMENT_UNMODIFIED");
            Console.WriteLine("G005_MISSING_FFMPEG_CHILD_PID=" + child.Id);
        }
        finally {
            if (!child.HasExited) { child.Kill(entireProcessTree:true); await child.WaitForExitAsync(); }
        }
    }
}
