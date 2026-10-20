using System.Text.Json.Nodes;

namespace PicotooPet.Desktop.Core.Production;

public interface IComfyPromptReconciler
{
    Task<string?> FindExactAsync(string graphDigest, CancellationToken ct);
    Task<bool> IsFinishedAsync(string promptId, CancellationToken ct);
}

/// <summary>只读固定 loopback queue/history；POST /prompt 仍只由 ComfyProductionClient 执行。</summary>
public sealed class ComfyPromptReconciler : IComfyPromptReconciler, IDisposable
{
    private readonly HttpClient _http;
    private readonly bool _owns;
    public ComfyPromptReconciler(HttpClient http)
    {
        if (http.BaseAddress != ComfyProductionClient.FixedBaseAddress) throw new ProductionWorkerException("MEDIA_COMFY_ENDPOINT_INVALID");
        _http = http;
    }
    private ComfyPromptReconciler() : this(new HttpClient(new SocketsHttpHandler
    { UseProxy = false, AllowAutoRedirect = false, ConnectTimeout = TimeSpan.FromSeconds(4) })
    { BaseAddress = ComfyProductionClient.FixedBaseAddress, Timeout = TimeSpan.FromSeconds(15) }) => _owns = true;
    public static ComfyPromptReconciler Create() => new();
    public async Task<string?> FindExactAsync(string graphDigest, CancellationToken ct)
    {
        if (graphDigest.Length != 64 || !graphDigest.All(c => c is (>= '0' and <= '9') or (>= 'a' and <= 'f')))
            throw new ProductionWorkerException("MEDIA_COMFY_RECONCILE_INVALID");
        // History first; no POST exists in this interface. Read both surfaces to reject duplicates.
        var history = await GetAsync("history?max_items=1000", ct).ConfigureAwait(false);
        var queue = await GetAsync("queue", ct).ConfigureAwait(false);
        var matches = new HashSet<string>(StringComparer.Ordinal);
        foreach (var name in new[] { "queue_running", "queue_pending" })
        {
            if (queue[name] is not JsonArray items) throw new ProductionWorkerException("MEDIA_COMFY_RECONCILE_INVALID");
            foreach (var item in items) Match(item as JsonArray, graphDigest, matches);
        }
        foreach (var entry in history)
        {
            if (entry.Value is not JsonObject record || record["prompt"] is not JsonArray tuple
                || tuple.Count < 3 || tuple[1]?.GetValue<string>() != entry.Key)
                throw new ProductionWorkerException("MEDIA_COMFY_RECONCILE_INVALID");
            Match(tuple, graphDigest, matches);
        }
        if (matches.Count > 1) throw new ProductionWorkerException("MEDIA_PROMPT_ID_CONFLICT");
        return matches.SingleOrDefault();
    }
    private static void Match(JsonArray? tuple, string digest, HashSet<string> matches)
    {
        if (tuple is null || tuple.Count < 3 || tuple[2] is not JsonObject graph) throw new ProductionWorkerException("MEDIA_COMFY_RECONCILE_INVALID");
        if (ProductionSubmissionJournal.GraphDigest(graph) == digest)
        {
            var id = tuple[1]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(id) || id.Length > 200) throw new ProductionWorkerException("MEDIA_COMFY_RECONCILE_INVALID");
            matches.Add(id);
        }
    }
    public async Task<bool> IsFinishedAsync(string promptId, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(promptId) || promptId.Length > 200)
            throw new ProductionWorkerException("MEDIA_COMFY_RECONCILE_INVALID");
        var queue = await GetAsync("queue", ct).ConfigureAwait(false);
        foreach (var name in new[] { "queue_running", "queue_pending" })
        {
            if (queue[name] is not JsonArray array) throw new ProductionWorkerException("MEDIA_COMFY_RECONCILE_INVALID");
            if (array.OfType<JsonArray>().Any(t => t.Count > 1 && t[1]?.GetValue<string>() == promptId)) return false;
        }
        var history = await GetAsync("history/" + Uri.EscapeDataString(promptId), ct).ConfigureAwait(false);
        return history[promptId]?["status"]?["completed"]?.GetValue<bool>() == true
            || history[promptId]?["status"]?["status_str"]?.GetValue<string>() == "error";
    }
    private async Task<JsonObject> GetAsync(string path, CancellationToken ct)
    {
        using var response = await _http.GetAsync(path, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        await using var input = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        using var output = new MemoryStream();
        var buffer = new byte[16384];
        int count;
        while ((count = await input.ReadAsync(buffer, ct).ConfigureAwait(false)) > 0)
        {
            if (output.Length + count > 8 * 1024 * 1024) throw new ProductionWorkerException("MEDIA_COMFY_RECONCILE_INVALID");
            output.Write(buffer, 0, count);
        }
        return JsonNode.Parse(output.ToArray()) as JsonObject ?? throw new ProductionWorkerException("MEDIA_COMFY_RECONCILE_INVALID");
    }
    public void Dispose() { if (_owns) _http.Dispose(); }
}
