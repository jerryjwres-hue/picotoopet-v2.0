namespace PicotooPet.TtsCompatibilityProbe;

/// <summary>
/// Deterministic stand-in for logical profile voice.windows.default.v1: among installed voices whose
/// language is English (the fixed probe phrase language), prefer en-US, then order by name. The OS
/// default voice and registration order never influence the choice.
/// </summary>
internal static class VoiceSelection
{
    public static VoiceInfo? Select(IEnumerable<VoiceInfo> voices) =>
        voices
            .Where(IsCompatible)
            .OrderBy(voice => string.Equals(voice.Culture, "en-US", StringComparison.OrdinalIgnoreCase) ? 0 : 1)
            .ThenBy(voice => voice.Name, StringComparer.Ordinal)
            .ThenBy(voice => voice.Id, StringComparer.Ordinal)
            .FirstOrDefault();

    public static bool IsCompatible(VoiceInfo voice) =>
        voice.Culture.Equals("en", StringComparison.OrdinalIgnoreCase)
        || voice.Culture.StartsWith("en-", StringComparison.OrdinalIgnoreCase);
}
