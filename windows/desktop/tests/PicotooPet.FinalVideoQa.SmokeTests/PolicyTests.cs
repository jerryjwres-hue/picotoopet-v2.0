using System.Globalization;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Services;

namespace PicotooPet.FinalVideoQa.SmokeTests;

internal static class PolicyTests
{
    internal static void Run()
    {
        foreach (var (profile, w, h) in new[] { ("video.landscape.v1", 832, 480), ("video.vertical.v1", 480, 832), ("video.square.v1", 640, 640) })
        {
            var v = new FinalQaVideoFacts(0, "h264", "yuv420p", w, h, 24, 1, 2_000_000, 48);
            var a = new FinalQaAudioFacts(1, "aac", "LC", 48000, 1, "mono", 2_000_000);
            var m = new FinalQaObservedMedia("mp4", 2_000_000, 1, v, null);
            void Validate(FinalQaObservedMedia facts, bool narration = false, long frames = 48, long ms = 2000) => FinalVideoQaMediaProbe.Validate(facts, profile, narration, frames, ms);
            Validate(m);
            foreach (var wrong in new[] { v with { CodecName = "hevc" }, v with { PixelFormat = "yuv444p" }, v with { Index = 1 }, v with { PacketCount = 0 } })
                Reject("VIDEO_STREAM_INVALID", () => Validate(m with { Video = wrong }));
            foreach (var wrong in new[] { v with { Width = w + 1 }, v with { Height = h + 1 }, v with { FpsNumerator = 25 },
                v with { FpsNumerator = 30 }, v with { FpsNumerator = 24000, FpsDenominator = 1001 }, v with { FpsNumerator = 0 } })
                Reject("OUTPUT_PROFILE_MISMATCH", () => Validate(m with { Video = wrong }));
            Validate(m with { Video = v with { DurationUs = 2_041_667 }, FormatDurationUs = 2_041_667 });
            Reject("RUNTIME_MISMATCH", () => Validate(m with { Video = v with { DurationUs = 2_041_668 } }));
            Validate(m with { FormatDurationUs = 2_100_000 });
            Reject("RUNTIME_MISMATCH", () => Validate(m with { FormatDurationUs = 2_100_001 }));
            Validate(m with { Audio = a, StreamCount = 2 }, true);
            Validate(m with { Audio = a with { DurationUs = 2_100_000 }, StreamCount = 2, FormatDurationUs = 2_100_000 }, true);
            Reject("RUNTIME_MISMATCH", () => Validate(m with { Audio = a with { DurationUs = 2_100_001 }, StreamCount = 2 }, true));
            Reject("AUDIO_STREAM_INVALID", () => Validate(m, true));
            Reject("AUDIO_STREAM_INVALID", () => Validate(m with { Audio = a, StreamCount = 2 }));
            foreach (var wrong in new[] { a with { CodecName = "mp3" }, a with { Profile = "HE-AAC" }, a with { SampleRate = 44100 },
                a with { Channels = 2 }, a with { Index = 0 }, a with { ChannelLayout = "stereo" }, a with { DurationUs = 0 } })
                Reject("AUDIO_STREAM_INVALID", () => Validate(m with { Audio = wrong, StreamCount = 2 }, true));
            var culture = CultureInfo.CurrentCulture;
            try { CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("fr-FR"); Validate(m); }
            finally { CultureInfo.CurrentCulture = culture; }
            // 49 frames /24 != 2000ms: legitimate quantization is not a fixed target-duration tolerance.
            Validate(m with { Video = v with { DurationUs = 2_041_667, PacketCount = 49 }, FormatDurationUs = 2_041_667 }, frames: 49);
        }
        Reject("OUTPUT_PROFILE_MISMATCH", () => FinalVideoQaMediaProbe.Validate(
            new("mp4", 1, 1, new(0, "h264", "yuv420p", 832, 480, 24, 1, 1, null), null), "unknown", false, 48, 2000));
        foreach (var bad in new[] { "{}", "[]", "{\"streams\":[],\"streams\":[]}", new string('x', 524289) })
            Reject("PROBE_FAILED", () => FinalVideoQaMediaProbe.Parse(bad));
        const string probe = """
        {"streams":[{"index":0,"codec_type":"video","codec_name":"h264","pix_fmt":"yuv420p","width":832,"height":480,"r_frame_rate":"24/1","avg_frame_rate":"24/1","duration":"2.000000","nb_read_packets":"48","disposition":{"attached_pic":0}}],"format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2","duration":"2.000000","nb_streams":1},"chapters":[]}
        """;
        foreach (var kind in new[] { "subtitle", "data", "attachment", "unknown" })
            Reject("UNEXPECTED_STREAM", () => FinalVideoQaMediaProbe.Parse(probe.Replace("\"codec_type\":\"video\"", $"\"codec_type\":\"{kind}\"", StringComparison.Ordinal)));
        Reject("UNEXPECTED_STREAM", () => FinalVideoQaMediaProbe.Parse(probe.Replace("\"chapters\":[]", "\"chapters\":[{\"id\":0}]", StringComparison.Ordinal)));
        Reject("CONTAINER_INVALID", () => FinalVideoQaMediaProbe.Parse(probe.Replace("mov,mp4,m4a,3gp,3g2,mj2", "matroska", StringComparison.Ordinal)));
        Console.WriteLine("QA_BOUNDARIES=PASS");
    }
    private static void Reject(string error, Action action)
    {
        try { action(); throw new InvalidOperationException("Expected FINAL_QA_" + error); }
        catch (FinalVideoQaException e) when (e.Code == "FINAL_QA_" + error) { }
    }
}
