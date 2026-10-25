using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>Bounded WPF snapshot scheduling must preserve the newest complete state.</summary>
internal static class CoalescingUiDispatcherSmokeTests
{
    public static void Run()
    {
        var manual = new ManualUiDispatcher();
        var applied = new List<string>();
        using (var coalescer = new CoalescingUiDispatcher<string>(manual, applied.Add))
        {
            // Simulate a stalled UI thread while thousands of Mac/REST/WS updates arrive.
            for (var i = 0; i < 10000; i++)
                coalescer.Post($"snapshot-{i}");

            SmokeAssert.True(manual.PendingCount == 1,
                "10,000 incoming snapshots must enqueue exactly one WPF callback");
            manual.RunOne();
            SmokeAssert.True(applied.SequenceEqual(new[] { "snapshot-9999" }),
                "The newest full-state snapshot must win without stale UI replay");
            SmokeAssert.True(manual.PendingCount == 0,
                "The queue slot must become available after successful delivery");

            // New events are still delivered normally after the queue drains.
            coalescer.Post("new");
            manual.RunOne();
            SmokeAssert.True(applied.Last() == "new",
                "Backpressure must not disable subsequent live status updates");
        }

        var duringApply = new ManualUiDispatcher();
        var reentrantApplied = new List<string>();
        CoalescingUiDispatcher<string>? reentrant = null;
        reentrant = new CoalescingUiDispatcher<string>(duringApply, value =>
        {
            reentrantApplied.Add(value);
            if (value == "first")
                reentrant!.Post("second");
        });
        using (reentrant)
        {
            reentrant.Post("first");
            duringApply.RunOne();
            SmokeAssert.True(duringApply.PendingCount == 1,
                "Arrival during UI callback must cause exactly one follow-up dispatch");
            duringApply.RunOne();
            SmokeAssert.True(reentrantApplied.SequenceEqual(new[] { "first", "second" }),
                "Arrival while applying a previous snapshot must not be lost");
            SmokeAssert.True(duringApply.PendingCount == 0,
                "Reentrant notifications must not cause a perpetual dispatcher loop");
        }

        var onDispose = new ManualUiDispatcher();
        var afterDisposeApplied = new List<string>();
        var stopping = new CoalescingUiDispatcher<string>(onDispose, afterDisposeApplied.Add);
        stopping.Post("before-disposal");
        stopping.Dispose();
        stopping.Post("after-disposal");
        onDispose.RunOne();
        SmokeAssert.True(afterDisposeApplied.Count == 0 && onDispose.PendingCount == 0,
            "Disposed Shell must neither apply stale snapshots nor enqueue new UI work");
    }

    private sealed class ManualUiDispatcher : IUiDispatcher
    {
        private readonly Queue<Action> _actions = new();
        public int PendingCount => _actions.Count;

        public Task InvokeAsync(Action action, CancellationToken cancellationToken = default)
        {
            _actions.Enqueue(action);
            return Task.CompletedTask;
        }

        public void RunOne()
        {
            SmokeAssert.True(_actions.Count > 0, "Expected one queued UI callback");
            _actions.Dequeue().Invoke();
        }
    }
}
