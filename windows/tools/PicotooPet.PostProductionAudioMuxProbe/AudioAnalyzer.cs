namespace PicotooPet.PostProductionAudioMuxProbe;

/// <summary>Placement validation + signal analysis over decoded mono 48 kHz s16le audio.</summary>
internal static class AudioAnalyzer
{
    public static readonly int[] CandidateHz = [440, 660, 880];

    public static double Rms(ReadOnlySpan<byte> pcm, int fromMs, int toMs)
    {
        var (start, count) = Range(pcm.Length, fromMs, toMs);
        if (count == 0)
        {
            return 0;
        }
        double sum = 0;
        for (var index = 0; index < count; index++)
        {
            var sample = (double)BitConverter.ToInt16(pcm.Slice((start + index) * 2, 2));
            sum += sample * sample;
        }
        return Math.Sqrt(sum / count);
    }

    /// <summary>Goertzel magnitude per candidate tone; returns the strongest frequency (0 when silent).</summary>
    public static int StrongestTone(ReadOnlySpan<byte> pcm, int fromMs, int toMs)
    {
        var (start, count) = Range(pcm.Length, fromMs, toMs);
        var best = 0;
        double bestMagnitude = 0;
        foreach (var hz in CandidateHz)
        {
            var coefficient = 2 * Math.Cos(2 * Math.PI * hz / Profile.AudioRate);
            double q1 = 0, q2 = 0;
            for (var index = 0; index < count; index++)
            {
                var q0 = BitConverter.ToInt16(pcm.Slice((start + index) * 2, 2)) + (coefficient * q1) - q2;
                q2 = q1;
                q1 = q0;
            }
            var magnitude = Math.Sqrt((q1 * q1) + (q2 * q2) - (coefficient * q1 * q2)) / Math.Max(1, count);
            if (magnitude > bestMagnitude)
            {
                bestMagnitude = magnitude;
                best = hz;
            }
        }
        return bestMagnitude > 100 ? best : 0;
    }

    private static (int Start, int Count) Range(int byteLength, int fromMs, int toMs)
    {
        var total = byteLength / 2;
        var start = Math.Clamp(fromMs * Profile.AudioRate / 1000, 0, total);
        var end = Math.Clamp(toMs * Profile.AudioRate / 1000, start, total);
        return (start, end - start);
    }

    /// <summary>
    /// Expected layout: tone windows [start+margin, tone_end-margin] must be non-silent with the right
    /// frequency; gap windows [tone_end+margin, next_start-margin] must be silent.
    /// </summary>
    public static IReadOnlyList<WindowCheck> CheckTimeline(
        ReadOnlySpan<byte> pcm,
        IReadOnlyList<(NarrationPlacement Placement, int DurationMs, int ExpectedHz)> segments,
        int timelineMs)
    {
        var checks = new List<WindowCheck>();
        var cursor = 0;
        foreach (var (placement, durationMs, expectedHz) in segments)
        {
            AddGap(checks, pcm, $"gap-before-{placement.Label}", cursor, placement.StartMs);
            var toneFrom = placement.StartMs + Profile.EdgeMarginMs;
            var toneTo = placement.StartMs + durationMs - Profile.EdgeMarginMs;
            var rms = Rms(pcm, toneFrom, toneTo);
            var hz = StrongestTone(pcm, toneFrom, toneTo);
            checks.Add(new WindowCheck(placement.Label, "tone", toneFrom, toneTo, Math.Round(rms), hz,
                rms >= Profile.ToneMinRms && hz == expectedHz));
            cursor = placement.StartMs + durationMs;
        }
        AddGap(checks, pcm, "gap-after-last", cursor, timelineMs);
        return checks;
    }

    private static void AddGap(List<WindowCheck> checks, ReadOnlySpan<byte> pcm, string name, int fromMs, int toMs)
    {
        var from = fromMs + Profile.EdgeMarginMs;
        var to = toMs - Profile.EdgeMarginMs;
        if (to <= from)
        {
            return; // gap too short to measure past the edge margins
        }
        var rms = Rms(pcm, from, to);
        checks.Add(new WindowCheck(name, "silence", from, to, Math.Round(rms), 0, rms <= Profile.SilenceMaxRms));
    }
}

/// <summary>Pre-mux validation: overlong narration is rejected, never truncated or sped up.</summary>
internal static class SegmentValidator
{
    public static string? Validate(
        IReadOnlyList<(NarrationPlacement Placement, WavFacts? Wav)> segments,
        int timelineMs)
    {
        var previousEnd = 0;
        foreach (var (placement, wav) in segments)
        {
            if (wav is null)
            {
                return Status.SegmentInvalid;
            }
            var window = placement.WindowEndMs - placement.StartMs;
            if (window <= 0 || placement.StartMs < 0)
            {
                return Status.SegmentInvalid;
            }
            if (placement.StartMs < previousEnd)
            {
                return Status.SegmentOverlap;
            }
            if (wav.DurationMs > window)
            {
                return Status.SegmentTooLong;
            }
            if (placement.WindowEndMs > timelineMs || placement.StartMs + wav.DurationMs > timelineMs)
            {
                return Status.SegmentOutsideTimeline;
            }
            previousEnd = placement.WindowEndMs;
        }
        return null;
    }
}
