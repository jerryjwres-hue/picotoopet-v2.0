namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>Pins belong to the existing executor invocation; disk copies outlive them.</summary>
internal sealed class DurableReferenceSnapshotBatch : IDisposable
{
    private readonly Dictionary<string, DurableReferenceSnapshot> _items = new(StringComparer.Ordinal);
    public void Add(string taskId, DurableReferenceSnapshot item) => _items.Add(taskId, item);
    public DurableReferenceSnapshot? Get(string taskId) => _items.GetValueOrDefault(taskId);
    public async Task ReauthorizeAsync(CancellationToken ct)
    {
        foreach (var item in _items.Values) await item.ReauthorizeAsync(ct).ConfigureAwait(false);
    }
    public void Dispose()
    {
        foreach (var item in _items.Values) item.Dispose();
    }
}
