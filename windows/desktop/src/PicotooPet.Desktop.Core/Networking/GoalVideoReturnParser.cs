using System.Text;
using System.Text.Json;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>仅处理剪贴板传输语法；字段、证据与权限语义只由 Mac Core 校验。</summary>
public static class GoalVideoReturnParser
{
    public const int MaxUtf8Bytes = 512 * 1024;
    private const string Marker = "PICOTOO_RETURN_JSON";

    public static JsonElement Parse(string text)
    {
        if (text is null)
        {
            throw new GoalVideoReturnParseException("EMPTY_INPUT");
        }
        if (Encoding.UTF8.GetByteCount(text) > MaxUtf8Bytes)
        {
            throw new GoalVideoReturnParseException("INPUT_TOO_LARGE");
        }

        var candidate = text.Trim();
        if ((candidate.Length == 0 || candidate[0] != 0x7B) && !StartsJsonFence(candidate))
        {
            var firstMarker = candidate.IndexOf(Marker, StringComparison.Ordinal);
            if (firstMarker < 0)
            {
                throw new GoalVideoReturnParseException("RETURN_JSON_NOT_FOUND");
            }
            if (candidate.IndexOf(
                    Marker,
                    firstMarker + Marker.Length,
                    StringComparison.Ordinal) >= 0)
            {
                throw new GoalVideoReturnParseException("DUPLICATE_MARKER");
            }
            candidate = candidate[(firstMarker + Marker.Length)..].Trim();
        }

        candidate = UnwrapJsonFence(candidate);
        try
        {
            using var document = JsonDocument.Parse(
                candidate,
                new JsonDocumentOptions
                {
                    AllowTrailingCommas = false,
                    CommentHandling = JsonCommentHandling.Disallow,
                    MaxDepth = 64,
                });
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                throw new GoalVideoReturnParseException("OBJECT_ROOT_REQUIRED");
            }
            return document.RootElement.Clone();
        }
        catch (JsonException exception)
        {
            throw new GoalVideoReturnParseException("MALFORMED_JSON", exception);
        }
    }

    private static bool StartsJsonFence(string value) =>
        value.StartsWith("```json", StringComparison.OrdinalIgnoreCase);

    private static string UnwrapJsonFence(string value)
    {
        if (!value.StartsWith("```", StringComparison.Ordinal))
        {
            if (value.Contains("```", StringComparison.Ordinal))
            {
                throw new GoalVideoReturnParseException("INVALID_JSON_FENCE");
            }
            return value;
        }

        var lineEnd = value.IndexOf('\n');
        if (lineEnd < 0
            || !string.Equals(value[..lineEnd].Trim(), "```json", StringComparison.OrdinalIgnoreCase)
            || !value.EndsWith("```", StringComparison.Ordinal))
        {
            throw new GoalVideoReturnParseException("INVALID_JSON_FENCE");
        }
        var body = value[(lineEnd + 1)..^3].Trim();
        if (body.Contains("```", StringComparison.Ordinal))
        {
            throw new GoalVideoReturnParseException("INVALID_JSON_FENCE");
        }
        return body;
    }
}

public sealed class GoalVideoReturnParseException : Exception
{
    public GoalVideoReturnParseException(string code, Exception? innerException = null)
        : base(code, innerException)
    {
        Code = code;
    }

    public string Code { get; }
}
