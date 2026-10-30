using PicotooPet.Desktop.Core.State;
using System.Text.Json;

namespace PicotooPet.Desktop.Services.QualityObservation;

internal sealed class SessionVisualObservationFacts : IVisualObservationFacts
{
    private readonly ControlCenterSession _session;
    private int _epoch;
    public SessionVisualObservationFacts(ControlCenterSession session)
    {
        _session = session;
        session.SnapshotChanged += Changed;
    }
    public event EventHandler? Invalidated;
    private void Changed(object? sender, ControlCenterSessionSnapshot snapshot)
    {
        // There is no approved credential-generation accessor. Re-pairing can
        // preserve URL and aggregate Online state, so fence EVERY notification,
        // including identical snapshots. Unrelated latency/task updates can also
        // cancel/clear review; this conservative limitation is explicit in handoff.
        Interlocked.Increment(ref _epoch); Invalidated?.Invoke(this, EventArgs.Empty);
    }
    public async Task<VisualObservationFacts> ReadAsync(string exactJobId, CancellationToken ct)
    {
        var epoch = Volatile.Read(ref _epoch);
        if (_session.Snapshot.State.Connection.State != ConnectionState.Online) throw new VisualObservationException("SESSION_UNVERIFIED");
        var job = _session.GetProductionJobAsync(exactJobId, ct);
        var plan = _session.GetProductionPlanAsync(exactJobId, ct);
        var package = _session.GetProductionPackageAsync(exactJobId, ct);
        await Task.WhenAll(job, plan, package).WaitAsync(ct).ConfigureAwait(false);
        if (epoch != Volatile.Read(ref _epoch) || _session.Snapshot.State.Connection.State != ConnectionState.Online)
            throw new VisualObservationException("SESSION_CHANGED");
        var facts = new VisualObservationFacts(await job.ConfigureAwait(false), await plan.ConfigureAwait(false),
            await package.ConfigureAwait(false) ?? throw new VisualObservationException("PACKAGE_MISSING"));
        // Freeze arrays and JsonElement lifetime before handing data to an async consumer.
        return JsonSerializer.Deserialize<VisualObservationFacts>(JsonSerializer.Serialize(facts))!;
    }
    public void Dispose() => _session.SnapshotChanged -= Changed;
}
