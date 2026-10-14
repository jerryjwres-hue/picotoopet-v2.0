using System.IO;
using PicotooPet.Desktop.Services;

namespace PicotooPet.FinalVideoQa.SmokeTests;

/// <summary>
/// G006's OWN native Windows three-profile E2E, not a mapping to C010A smoke.
/// Every combination independently runs genuine C004/C008B and C009B when
/// required, C010A ffprobe/full decode, receipt persistence and restart reuse.
/// </summary>
internal static class C010BThreeProfileWindowsMedia
{
    private static readonly (string Profile, int Width, int Height)[] Profiles =
    [
        ("video.landscape.v1", 832, 480),
        ("video.vertical.v1", 480, 832),
        ("video.square.v1", 640, 640),
    ];

    public static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows())
            throw new InvalidOperationException("UNVERIFIED_NATIVE_WINDOWS_REQUIRED");

        var success = 0;
        foreach (var (profile, width, height) in Profiles)
        foreach (var narration in new[] { false, true })
        foreach (var overlays in new[] { false, true })
        {
            using var fixture = await Fixture.CreateAsync(
                narration, overlays, profile: profile, real: true);
            var result = await fixture.Service.ComposeAsync(fixture.Input);
            var master = result.Artifact;
            var required = narration || overlays;
            Check(result.Required == required, "actual C009A Required shape");
            Check((master is not null) == required, "real master only for required postproduction");
            if (required)
            {
                Check(fixture.Composer.Calls == 1,
                    "C009B real FixedFfmpegMasterVideoComposer invoked exactly once");
                Check(File.Exists(master!.FilePath) && File.Exists(master.ManifestPath),
                    "real C009A durable master and manifest exist");
            }
            var input = LifecycleTests.Input(fixture, master);
            var first = await LifecycleTests.Service(fixture, new FixedMasterVideoProcessRunner())
                .VerifyAsync(input);
            Check(!first.Reused && first.Receipt.Outcome == "PASS",
                "actual C010A native full-decode PASS and durable receipt");
            var evidence = first.Receipt;
            var video = evidence.ObservedMedia.Video;
            Check(evidence.OutputProfileId == profile && video.Width == width && video.Height == height,
                "exact native C005 profile width/height");
            Check(video.CodecName == "h264" && video.PixelFormat == "yuv420p"
                && video.FpsNumerator == 24L * video.FpsDenominator,
                "actual H264/yuv420p/24fps");
            Check(video.Index == 0 && evidence.ObservedMedia.StreamCount == (narration ? 2 : 1),
                "closed video/audio stream count");
            var audio = evidence.ObservedMedia.Audio;
            if (narration)
            {
                Check(audio is not null && audio.Index == 1 && audio.CodecName == "aac"
                    && audio.Profile == "LC" && audio.SampleRate == 48_000
                    && audio.Channels == 1 && audio.ChannelLayout is (null or "mono"),
                    "real AAC LC/48kHz/mono index 1");
            }
            else Check(audio is null, "no narration must have zero AAC tracks");
            Check(evidence.NarrationRequired == narration && evidence.OverlaysRequired == overlays,
                "actual plan flags committed to receipt");
            Check(evidence.CandidateKind == (required ? "c009_master_v1" : "c004_fallback_v1"),
                "strict actual candidate selection");
            Check(evidence.PassedCheckIds.Contains("full-decode.v1", StringComparer.Ordinal),
                "native decode mandatory");
            Check(evidence.QaInputDigest.Length == 64 && evidence.ReceiptDigest.Length == 64,
                "persistent QA/receipt digests");
            Check(File.Exists(first.ReceiptPath) && first.Receipt.ArtifactBytes > 0,
                "PASS-only durable receipt file exists");

            // A fresh service instance with a runner that throws on ANY media
            // invocation must reuse the original immutable receipt.
            var repeat = await LifecycleTests.Service(fixture, new NeverRunner()).VerifyAsync(input);
            Check(repeat.Reused && repeat.ReceiptDigestEqual(first), "restart reuses exact QA identity");
            success++;
            Console.WriteLine($"C010B_THREE_PROFILE_REAL_PASS {profile} narration={narration} overlay={overlays}");
        }
        Check(success == 12, "3 exact profiles times 4 real media combinations");
        Console.WriteLine("C010B_THREE_PROFILE_REAL_SUMMARY=passed=12;failed=0");
    }

    private static bool ReceiptDigestEqual(this FinalVideoQaResult result, FinalVideoQaResult prior)
        => result.ReceiptPath == prior.ReceiptPath
        && result.Receipt.QaInputDigest == prior.Receipt.QaInputDigest
        && result.Receipt.ReceiptDigest == prior.Receipt.ReceiptDigest;

    private static void Check(bool condition, string description) =>
        LifecycleTests.Assert(condition, description);
}
