using System.Reflection;
using PicotooPet.Desktop.Services;

var type = typeof(MasterVideoArtifact).Assembly.GetType("PicotooPet.Desktop.Services.FinalVideoQaMediaProbe")
    ?? throw new InvalidOperationException("C010A missing: strict final-video media QA must exist independently of mux acceptance.");
var parse = type.GetMethod("Parse", BindingFlags.Public | BindingFlags.Static)!;
var validate = type.GetMethod("Validate", BindingFlags.Public | BindingFlags.Static)!;
const string good = """
{"streams":[{"index":0,"codec_type":"video","codec_name":"h264","pix_fmt":"yuv420p","width":832,"height":480,"r_frame_rate":"24/1","avg_frame_rate":"24/1","duration":"2.000000","nb_read_packets":"48","disposition":{"attached_pic":0}}],"format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2","duration":"2.000000","nb_streams":1},"chapters":[]}
""";
void Check(string json, string? error = null)
{
    try
    {
        var facts = parse.Invoke(null, [json]);
        validate.Invoke(null, [facts, "video.landscape.v1", false, 48L, 2000L]);
        if (error is not null) throw new InvalidOperationException("Expected " + error);
    }
    catch (TargetInvocationException e) when (e.InnerException?.Message == error) { }
}
Check(good);
Check(good.Replace("h264", "hevc", StringComparison.Ordinal), "FINAL_QA_VIDEO_STREAM_INVALID");
Check(good.Replace("24/1", "24000/1001", StringComparison.Ordinal), "FINAL_QA_OUTPUT_PROFILE_MISMATCH");
Check(good.Replace("2.000000", "2.200000", StringComparison.Ordinal), "FINAL_QA_RUNTIME_MISMATCH");
Check(good.Replace("\"attached_pic\":0", "\"attached_pic\":1", StringComparison.Ordinal), "FINAL_QA_UNEXPECTED_STREAM");
Check("{}", "FINAL_QA_PROBE_FAILED");
Console.WriteLine("QA_MEDIA_POLICY=PASS");
PicotooPet.FinalVideoQa.SmokeTests.PolicyTests.Run();
await PicotooPet.FinalVideoQa.SmokeTests.SecurityTests.RunAsync();
await PicotooPet.FinalVideoQa.SmokeTests.LifecycleTests.RunAsync(args.Contains("--real", StringComparer.Ordinal));
