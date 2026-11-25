// P0-Q2 #140: independent read-only observer CLI. Review logic lives in
// tools/p0_visual_review_core (shared with the Desktop app); this file is only the entry point.
using System.Text.Json;

namespace PicotooPet.QualityObservation;

public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        // Invocation       : no implicit default paths or silent LAN model enablement.
        if (args.Length != 5 && args.Length != 9)
        {
            Console.Error.WriteLine("Usage: review <manifest.json> <comfy-output-root> <new-output-dir> <ffprobe> <ffmpeg> [--allow-lan-vlm <http://PRIVATE_IPV4:11434> <installed-model>]");
            return 2;
        }
        try
        {
            var opts = new ReviewOptions(args[0], args[1], args[2], args[3], args[4],
                args.Length == 9 && args[5] == "--allow-lan-vlm" ? args[6] : null,
                args.Length == 9 && args[5] == "--allow-lan-vlm" ? args[7] : null,
                args.Length == 9 && args[5] == "--allow-lan-vlm" && args[8] == "--consent");
            if (args.Length == 9 && !opts.ApproveLanFrames)
                throw new InvalidOperationException("LOCAL_VLM_NEEDS_EXPLICIT_OPT_IN");
            var report = await ReviewRunner.ExecuteAsync(opts);
            Console.WriteLine($"VISUAL_REVIEW={report.Status}; SHOTS={report.Shots.Count}; MODEL={report.ModelState}");
            return report.Status == "UNVERIFIED" ? 2 : 0;
        }
        catch (Exception ex) when (ex is IOException or JsonException or InvalidOperationException
            or UnauthorizedAccessException or ArgumentException or KeyNotFoundException)
        {
            Console.Error.WriteLine("VISUAL_REVIEW=UNVERIFIED; " + ex.Message);
            return 2;
        }
    }
}
