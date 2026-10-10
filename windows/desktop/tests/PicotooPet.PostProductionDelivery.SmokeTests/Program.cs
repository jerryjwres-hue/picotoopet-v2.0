using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Security.Cryptography;
using System.Text;
using PicotooPet.Desktop.Services;

namespace PicotooPet.PostProductionDelivery.SmokeTests;

/// <summary>无真实 mux 依赖的 C009C 独立 policy + managed artifact 防护验证。</summary>
internal static class Program
{
    private static async Task<int> Main()
    {
        foreach (var narration in new[] { false, true })
        {
            foreach (var overlays in new[] { false, true })
            {
                var required = narration || overlays;
                Check(GoalDeliveryPolicy.IsAllowed(
                    required ? GoalDeliveryKind.C009Master : GoalDeliveryKind.C004Fallback,
                    narration, overlays));
                Check(!GoalDeliveryPolicy.IsAllowed(
                    required ? GoalDeliveryKind.C004Fallback : GoalDeliveryKind.C009Master,
                    narration, overlays));
            }
        }
        Check(GoalDeliveryPolicy.IsPreQaOpenable(
            GoalDeliveryPhase.MasteredReady, GoalDeliveryKind.C009Master));
        Check(GoalDeliveryPolicy.IsPreQaOpenable(
            GoalDeliveryPhase.FallbackReady, GoalDeliveryKind.C004Fallback));
        Check(!GoalDeliveryPolicy.IsPreQaOpenable(
            GoalDeliveryPhase.PostProcessing, GoalDeliveryKind.C004Fallback));
        Check(!GoalDeliveryPolicy.IsPreQaOpenable(
            GoalDeliveryPhase.QualityChecking, GoalDeliveryKind.C009Master));

        using var fixture = new CandidateFixture();
        await fixture.VerifyFallbackAndTamperAsync().ConfigureAwait(false);
        await fixture.VerifyMasterAndTamperAsync().ConfigureAwait(false);
        await CoordinatorIntegrationTests.RunAsync().ConfigureAwait(false);
        await GoalCenterAsyncOpenIntegrationTests.RunAsync().ConfigureAwait(false);
        Console.WriteLine("POSTPRODUCTION_DELIVERY_ISOLATED_SMOKE=PASS");
        return 0;
    }

    private static void Check(bool condition)
    {
        if (!condition)
        {
            throw new InvalidOperationException("C009C_SMOKE_ASSERTION_FAILED");
        }
    }

    private sealed class CandidateFixture : IDisposable
    {
        private readonly string _root;
        private readonly string _finalRoot;
        private readonly string _masterRoot;
        private readonly GoalDeliveryCandidateVerifier _verifier;
        private const string JobId = "c009c-test-job";
        private const string Digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

        public CandidateFixture()
        {
            _root = Path.Combine(Path.GetTempPath(), "c009c-" + Guid.NewGuid().ToString("N"));
            _finalRoot = Path.Combine(_root, "FinalVideos");
            _masterRoot = Path.Combine(_root, "Master", "v1");
            Directory.CreateDirectory(_finalRoot);
            Directory.CreateDirectory(_masterRoot);
            _verifier = new GoalDeliveryCandidateVerifier(_finalRoot, _masterRoot);
        }

        public async Task VerifyFallbackAndTamperAsync()
        {
            var jobHash = Sha(Encoding.UTF8.GetBytes(JobId))[..32];
            var movie = Path.Combine(_finalRoot, "final-" + jobHash + ".mp4");
            var manifest = Path.Combine(_finalRoot, "final-" + jobHash + ".final-video.json");
            await File.WriteAllBytesAsync(movie, "visual"u8.ToArray()).ConfigureAwait(false);
            await File.WriteAllBytesAsync(manifest, "{\"schema_version\":\"1.0\"}"u8.ToArray())
                .ConfigureAwait(false);
            var candidate = Candidate(GoalDeliveryKind.C004Fallback, movie, manifest, null, false, false);
            Check(await _verifier.VerifyAtOpenAsync(candidate, CancellationToken.None).ConfigureAwait(false));
            Check(!await _verifier.VerifyAtOpenAsync(
                candidate with { NarrationRequired = true }, CancellationToken.None).ConfigureAwait(false));
            Check(!await _verifier.VerifyAtOpenAsync(
                candidate with { FilePath = Path.Combine(_root, "other.mp4") },
                CancellationToken.None).ConfigureAwait(false));
            await File.AppendAllTextAsync(movie, "tampered").ConfigureAwait(false);
            Check(!await _verifier.VerifyAtOpenAsync(candidate, CancellationToken.None).ConfigureAwait(false));
            await File.WriteAllBytesAsync(movie, "visual"u8.ToArray()).ConfigureAwait(false);
            await File.AppendAllTextAsync(manifest, "tampered").ConfigureAwait(false);
            Check(!await _verifier.VerifyAtOpenAsync(candidate, CancellationToken.None).ConfigureAwait(false));
        }

        public async Task VerifyMasterAndTamperAsync()
        {
            var safeJob = JobId;
            var suffix = Sha(Encoding.UTF8.GetBytes(JobId))[..16];
            var dir = Path.Combine(_masterRoot, safeJob + "-" + suffix, Digest);
            Directory.CreateDirectory(dir);
            var movie = Path.Combine(dir, "master.mp4");
            var manifest = Path.Combine(dir, "master-manifest.json");
            await File.WriteAllBytesAsync(movie, "master"u8.ToArray()).ConfigureAwait(false);
            await File.WriteAllBytesAsync(manifest, "{\"master_input_digest\":\"a\"}"u8.ToArray())
                .ConfigureAwait(false);
            var candidate = Candidate(GoalDeliveryKind.C009Master, movie, manifest, Digest, true, false);
            Check(await _verifier.VerifyAtOpenAsync(candidate, CancellationToken.None).ConfigureAwait(false));
            Check(!await _verifier.VerifyAtOpenAsync(
                candidate with { NarrationRequired = false, OverlaysRequired = false },
                CancellationToken.None).ConfigureAwait(false));
            Check(!await _verifier.VerifyAtOpenAsync(
                candidate with { MasterInputDigest = new string('b', 64) },
                CancellationToken.None).ConfigureAwait(false));
            Check(!await _verifier.VerifyAtOpenAsync(
                candidate with { FilePath = Path.Combine(_finalRoot, "master.mp4") },
                CancellationToken.None).ConfigureAwait(false));
            await File.AppendAllTextAsync(movie, "tampered").ConfigureAwait(false);
            Check(!await _verifier.VerifyAtOpenAsync(candidate, CancellationToken.None).ConfigureAwait(false));
            await File.WriteAllBytesAsync(movie, "master"u8.ToArray()).ConfigureAwait(false);
            File.Delete(manifest);
            Check(!await _verifier.VerifyAtOpenAsync(candidate, CancellationToken.None).ConfigureAwait(false));
        }

        private static GoalDeliveryCandidateV1 Candidate(
            GoalDeliveryKind kind, string file, string manifest,
            string? inputDigest, bool narration, bool overlays)
        {
            var bytes = File.ReadAllBytes(file);
            var manifestBytes = File.ReadAllBytes(manifest);
            return new GoalDeliveryCandidateV1(
                kind, JobId, "package", Digest, Digest, 1000, "video.landscape.v1",
                narration, Digest, overlays, Digest,
                file, manifest, Sha(bytes), bytes.LongLength,
                Sha(manifestBytes), manifestBytes.LongLength, inputDigest);
        }

        private static string Sha(byte[] bytes) =>
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

        public void Dispose()
        {
            try
            {
                if (Directory.Exists(_root))
                {
                    Directory.Delete(_root, recursive: true);
                }
            }
            catch (IOException)
            {
                // The sandbox may retain antivirus locks; no production directory is touched.
            }
            catch (UnauthorizedAccessException)
            {
                // Same cleanup policy.
            }
        }
    }
}
