using System.Globalization;
using System.Text.Json;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// P0 manual approval for exactly one old, Core-bound prompt lost across a real PC reboot.
/// A checked approval is NOT proof of lost GPU work on its own: the executor must also
/// verify original Core attempt1, an empty Comfy queue, absent exact history/output,
/// and a currently authorized frozen Job before reserving attempt2.
/// </summary>
internal static class P0LostPromptRetryApproval
{
    internal static string DefaultPath => Path.Combine(
        ProductionSubmissionJournal.DefaultRoot, "lost-prompt-attempt2-approval.json");

    internal static DateTimeOffset CurrentWindowsBootUtc() =>
        DateTimeOffset.UtcNow - TimeSpan.FromMilliseconds(Environment.TickCount64);

    internal static bool IsApproved(
        string jobId, string taskId, string oldPromptId, string planDigest,
        DateTimeOffset coreTaskUpdatedUtc,
        DateTimeOffset bootUtc, DateTimeOffset nowUtc,
        string? filePath = null)
    {
        var path = filePath ?? DefaultPath;
        if (!File.Exists(path)) return false;

        for (DirectoryInfo? dir = new(Path.GetDirectoryName(Path.GetFullPath(path))!);
            dir is not null; dir = dir.Parent)
            if (dir.Exists && (dir.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new ProductionWorkerException("MEDIA_RECOVERY_APPROVAL_INVALID");
        if ((File.GetAttributes(path) & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0
            || new FileInfo(path).Length is <= 0 or > 1024)
            throw new ProductionWorkerException("MEDIA_RECOVERY_APPROVAL_INVALID");

        try
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            using var document = JsonDocument.Parse(stream);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object || root.EnumerateObject().Count() != 6
                || Text(root, "schema_version") != "p0.lost-prompt-attempt2.v1"
                || Text(root, "production_job_id") != jobId
                || Text(root, "production_task_id") != taskId
                || Text(root, "previous_prompt_id") != oldPromptId
                || Text(root, "plan_digest") != planDigest)
                throw new ProductionWorkerException("MEDIA_RECOVERY_APPROVAL_INVALID");

            var rawUtc = Text(root, "authorized_at_utc");
            if (!DateTimeOffset.TryParseExact(rawUtc, "O", CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out var authorizedUtc)
                || authorizedUtc.Offset != TimeSpan.Zero
                || authorizedUtc < bootUtc
                || authorizedUtc > nowUtc.AddMinutes(1)
                || authorizedUtc < nowUtc.AddMinutes(-30)
                // The old Core-bound prompt must be known BEFORE the current Windows boot.
                // Core task updated_at is bound durably; local Journal mtime may be rewritten
                // by the recovering worker, so it must not be treated as submission time.
                || coreTaskUpdatedUtc >= bootUtc.AddSeconds(-5))
                throw new ProductionWorkerException("MEDIA_RECOVERY_APPROVAL_INVALID");

            return true;
        }
        catch (Exception e) when (e is JsonException or FormatException or InvalidOperationException)
        {
            throw new ProductionWorkerException("MEDIA_RECOVERY_APPROVAL_INVALID");
        }
    }

    private static string? Text(JsonElement root, string property) =>
        root.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() : null;
}
