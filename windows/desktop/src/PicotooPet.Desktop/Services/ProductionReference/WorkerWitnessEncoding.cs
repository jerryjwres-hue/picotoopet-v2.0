using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>Frozen Core byte contract, not a trusted challenge decoder or admission token.</summary>
internal static partial class WorkerWitnessEncoding
{
    private const string Fields = "schema_version algorithm worker_key_id executor_id production_job_id plan_digest issued_at expires_at nonce worker_executable_sha256 journal_digest journal_generation journal_state references signature";
    private const string ReferenceFields = "production_task_id shot_id asset_id approval_id approval_request_digest source_sha256 source_bytes source_relative_path snapshot_sha256 snapshot_bytes snapshot_receipt_sha256 graph_digest snapshot_relative_path";
    internal static byte[] Payload(JsonElement witness)
    {
        Shape(witness, Fields);
        Equal(witness, "schema_version", "production.worker_witness.v1");
        Equal(witness, "algorithm", "ed25519");
        Identifier(Text(witness, "executor_id", 120));
        Identifier(Text(witness, "worker_key_id", 128), 16);
        Text(witness, "production_job_id", 160);
        foreach (var name in new[] { "plan_digest", "nonce", "worker_executable_sha256", "journal_digest" }) Hex(witness, name, 64);
        Hex(witness, "signature", 128);
        foreach (var name in new[] { "nonce", "signature", "worker_executable_sha256" })
            if (witness.GetProperty(name).GetString()!.All(c => c == '0')) throw Invalid();
        if (!witness.GetProperty("journal_generation").TryGetInt64(out var generation) || generation < 0) throw Invalid();
        // This first signer deliberately supports only an empty, reconciled journal.
        Equal(witness, "journal_state", "NO_PRIOR_POST");
        var issued = Date(witness, "issued_at"); var expires = Date(witness, "expires_at");
        if (expires <= issued || expires - issued > TimeSpan.FromSeconds(30)) throw Invalid();
        var references = witness.GetProperty("references");
        if (references.ValueKind != JsonValueKind.Array || references.GetArrayLength() is < 1 or > 12) throw Invalid();
        HashSet<string> tasks = new(StringComparer.Ordinal), shots = new(StringComparer.Ordinal);
        foreach (var reference in references.EnumerateArray())
        {
            Shape(reference, ReferenceFields);
            if (!tasks.Add(Text(reference, "production_task_id", 160)) || !shots.Add(Text(reference, "shot_id", 80))) throw Invalid();
            Text(reference, "asset_id", 160); Text(reference, "approval_id", 160);
            foreach (var name in new[] { "approval_request_digest", "source_sha256", "snapshot_sha256", "snapshot_receipt_sha256", "graph_digest" }) Hex(reference, name, 64);
            foreach (var name in new[] { "source_bytes", "snapshot_bytes" })
                if (!reference.GetProperty(name).TryGetInt64(out var count) || count is <= 0 or > 33554432) throw Invalid();
            foreach (var name in new[] { "source_relative_path", "snapshot_relative_path" })
            {
                var path = Text(reference, name, 300);
                if (path.Contains('\\', StringComparison.Ordinal) || path.StartsWith('/') || path.Contains(':', StringComparison.Ordinal)
                    || path.Split('/').Any(p => p is "" or "." or "..")) throw Invalid();
            }
        }
        var output = new StringBuilder("picotoopet.production.worker_witness.v1\n");
        Write(output, witness, true);
        return new UTF8Encoding(false, true).GetBytes(output.ToString());
    }

    internal static void RequireFresh(JsonElement witness, DateTimeOffset now)
    {
        if (now.Offset != TimeSpan.Zero || Date(witness, "issued_at") > now.AddSeconds(5) || Date(witness, "expires_at") <= now) throw Invalid();
    }

    private static DateTimeOffset Date(JsonElement value, string name)
    {
        var text = value.GetProperty(name).GetString() ?? throw Invalid();
        if (!UtcStamp().IsMatch(text) || !DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture,
                DateTimeStyles.None, out var date) || date.Offset != TimeSpan.Zero) throw Invalid();
        return date;
    }
    [GeneratedRegex(@"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$", RegexOptions.CultureInvariant)]
    private static partial Regex UtcStamp();
    private static void Shape(JsonElement value, string fields)
    {
        if (value.ValueKind != JsonValueKind.Object) throw Invalid();
        var expected = fields.Split(' ').ToHashSet(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject()) if (!expected.Remove(property.Name)) throw Invalid();
        if (expected.Count != 0) throw Invalid();
    }
    private static string Text(JsonElement value, string name, int max)
    {
        var text = value.GetProperty(name).GetString() ?? throw Invalid();
        if (text.Length < 1 || text.EnumerateRunes().Count() > max) throw Invalid();
        return text;
    }
    private static void Identifier(string value, int min = 1)
    {
        if (value.Length < min || value.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not ('_' or '.' or '-'))) throw Invalid();
    }
    private static void Hex(JsonElement value, string name, int length)
    {
        var text = value.GetProperty(name).GetString() ?? throw Invalid();
        if (text.Length != length || text.Any(c => c is not (>= '0' and <= '9') and not (>= 'a' and <= 'f'))) throw Invalid();
    }
    private static void Equal(JsonElement value, string name, string expected)
    {
        if (value.GetProperty(name).GetString() != expected) throw Invalid();
    }
    private static InvalidDataException Invalid() => new("WORKER_WITNESS_INVALID_OR_STALE");

    // Python ensure_ascii=False is not System.Text.Json's HTML/Unicode escaping.
    // All object keys in this closed schema are ASCII. Integers never pass through double.
    private static void Write(StringBuilder output, JsonElement value, bool outer = false)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                output.Append('\u007b'); var first = true;
                foreach (var property in value.EnumerateObject().Where(p => !outer || p.Name != "signature").OrderBy(p => p.Name, StringComparer.Ordinal))
                {
                    if (!first) output.Append(','); first = false;
                    String(output, property.Name); output.Append(':');
                    if (outer && property.Name is "issued_at" or "expires_at")
                    {
                        var date = Date(value, property.Name);
                        var stamp = date.ToString("yyyy-MM-dd'T'HH:mm:ss", CultureInfo.InvariantCulture);
                        var micros = date.Ticks % TimeSpan.TicksPerSecond / 10;
                        if (micros != 0) stamp += "." + micros.ToString("D6", CultureInfo.InvariantCulture);
                        String(output, stamp + "Z");
                    }
                    else Write(output, property.Value);
                }
                output.Append('\u007d'); break;
            case JsonValueKind.Array:
                output.Append('\u005b'); var separator = false;
                foreach (var item in value.EnumerateArray()) { if (separator) output.Append(','); separator = true; Write(output, item); }
                output.Append('\u005d'); break;
            case JsonValueKind.String: String(output, value.GetString()!); break;
            case JsonValueKind.Number: output.Append(value.GetInt64().ToString(CultureInfo.InvariantCulture)); break;
            default: throw Invalid();
        }
    }
    private static void String(StringBuilder output, string value)
    {
        output.Append('\u0022');
        foreach (var c in value)
            switch (c)
            {
                case '\u0022': output.Append("\\\""); break;
                case '\\': output.Append("\\\\"); break;
                case '\b': output.Append("\\b"); break;
                case '\f': output.Append("\\f"); break;
                case '\n': output.Append("\\n"); break;
                case '\r': output.Append("\\r"); break;
                case '\t': output.Append("\\t"); break;
                default:
                    if (c < 32) output.Append("\\u" + ((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    else output.Append(c);
                    break;
            }
        output.Append('\u0022');
    }
}
