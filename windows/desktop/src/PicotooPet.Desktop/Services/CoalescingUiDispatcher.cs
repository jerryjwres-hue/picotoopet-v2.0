using System.Threading;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// Keeps at most one pending UI dispatcher callback for full-state snapshots.
/// This avoids unbounded WPF work queues when incoming state events outpace rendering.
/// </summary>
public sealed class CoalescingUiDispatcher<T> : IDisposable where T : class
{
    private readonly IUiDispatcher _dispatcher;
    private readonly Action<T> _apply;
    private T? _latest;
    private int _scheduled;
    private int _disposed;

    public CoalescingUiDispatcher(IUiDispatcher dispatcher, Action<T> apply)
    {
        _dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
        _apply      = apply ?? throw new ArgumentNullException(nameof(apply));
    }

    /// <summary>Retain only the newest complete snapshot; do not queue an action per event.</summary>
    public void Post(T snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        if (Volatile.Read(ref _disposed) != 0) return;
        Interlocked.Exchange(ref _latest, snapshot);
        ScheduleIfNeeded();
    }

    private void ScheduleIfNeeded()
    {
        if (Volatile.Read(ref _disposed) != 0
            || Interlocked.CompareExchange(ref _scheduled, 1, 0) != 0) return;

        try
        {
            _ = _dispatcher.InvokeAsync(() =>
            {
                try
                {
                    // Consume the latest whole-state projection on the UI thread.
                    // Intermediate samples may be dropped, but no durable Core facts are changed.
                    var snapshot = Interlocked.Exchange(ref _latest, null);
                    if (Volatile.Read(ref _disposed) == 0 && snapshot is not null)
                        _apply(snapshot);
                }
                finally
                {
                    // Release the single queued slot, then cover arrivals during the callback.
                    // A racing producer either schedules first or is observed here.
                    Interlocked.Exchange(ref _scheduled, 0);
                    if (Volatile.Read(ref _disposed) == 0
                        && Volatile.Read(ref _latest) is not null)
                        ScheduleIfNeeded();
                }
            }, CancellationToken.None);
        }
        catch
        {
            // Synchronous dispatcher failure must never leave a permanently occupied slot.
            Interlocked.Exchange(ref _scheduled, 0);
            Interlocked.Exchange(ref _latest, null);
            throw;
        }
    }

    public void Dispose()
    {
        Interlocked.Exchange(ref _disposed, 1);
        Interlocked.Exchange(ref _latest, null);
    }
}
