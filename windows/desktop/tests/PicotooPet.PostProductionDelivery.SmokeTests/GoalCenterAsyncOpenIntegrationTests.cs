using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.PostProductionDelivery.SmokeTests;

/// <summary>
/// Executes the Goal Center ViewModel's one async open action on a real STA WPF dispatcher,
/// without FFmpeg, Core networking, or C010 receipt APIs.
/// </summary>
internal static class GoalCenterAsyncOpenIntegrationTests
{
    public static async Task RunAsync()
    {
        await OnDispatcherAsync(async () =>
        {
            var observer = new PendingDeliveryObserver();
            var gateway = new FakeGateway();
            var viewModel = new GoalVideoContinuationViewModel(gateway, null, observer);
            viewModel.SetContext(Goal("goal-a"), Handoff("goal-a"));
            await viewModel.RefreshAsync().ConfigureAwait(true);
            Check(viewModel.CanOpenFinalVideo, "ready should enable only the bound button");

            var first = viewModel.OpenFinalVideoAsync();
            Check(!first.IsCompleted, "open must not synchronously block the STA dispatcher");
            Check(!viewModel.CanOpenFinalVideo, "in-flight open must disable bound button");
            Check(!await viewModel.OpenFinalVideoAsync().ConfigureAwait(true),
                "concurrent duplicate open must be refused");
            Check(observer.OpenCalls == 1, "only one underlying open attempt");

            var responsiveness = new TaskCompletionSource<bool>(
                TaskCreationOptions.RunContinuationsAsynchronously);
            _ = Dispatcher.CurrentDispatcher.BeginInvoke(() =>
            {
                responsiveness.TrySetResult(true);
                observer.Resolve(true);
            }, DispatcherPriority.Background);
            await responsiveness.Task.ConfigureAwait(true);
            Check(await first.ConfigureAwait(true), "verified current open succeeds");
            Check(viewModel.CanOpenFinalVideo, "button returns to ready on success");

            observer.Reset();
            var stale = viewModel.OpenFinalVideoAsync();
            Check(!stale.IsCompleted, "second open remains async");
            viewModel.SetContext(Goal("goal-b"), Handoff("goal-b"));
            observer.Resolve(true);
            Check(!await stale.ConfigureAwait(true), "stale Goal open must not report success");
            Check(!viewModel.CanOpenFinalVideo, "new goal without continuation cannot open");

            gateway.Goal = "goal-b";
            viewModel.SetContext(Goal("goal-b"), Handoff("goal-b"));
            await viewModel.RefreshAsync().ConfigureAwait(true);
            Check(viewModel.CanOpenFinalVideo, "new verified goal restored");
            observer.Reset();
            var rejected = viewModel.OpenFinalVideoAsync();
            observer.Resolve(false);
            Check(!await rejected.ConfigureAwait(true), "failed verification rejects click");
            Check(!viewModel.CanOpenFinalVideo, "failed open disables button");
            Check(viewModel.ProductionStatusText.Contains("暂时无法打开", StringComparison.Ordinal),
                "bounded failure status");
        }).ConfigureAwait(false);
        Console.WriteLine("GOAL_CENTER_ASYNC_OPEN_DISPATCHER=PASS");
    }

    private static void Check(bool value, string message)
    {
        if (!value) throw new InvalidOperationException("C009C_UI: " + message);
    }

    private static HumanGoalRecord Goal(string goal) => new(
        goal, null, "workflow-1", "human", "product.research_to_video", "P1",
        "research and video", JsonDocument.Parse("{}").RootElement.Clone(), "local-first",
        false, null, "Completed", "goal-key", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);

    private static GoalHandoffMetadataRecord Handoff(string goal) => new(
        "1.0", goal, true, goal + ".zip", new string('a', 64), 100, "web-gpt-master-v1.0", true);

    private sealed class FakeGateway : IGoalVideoContinuationGateway
    {
        public string Goal = "goal-a";
        public Task<GoalVideoContinuationRecord> GetGoalVideoContinuationAsync(
            string goal, CancellationToken cancellationToken) =>
            Task.FromResult(new GoalVideoContinuationRecord(
                goal, new string('a', 64), new string('b', 64),
                "creative", "creative-package", new string('c', 64),
                "creative_ready", "job-" + goal, "production_ready"));

        public Task<GoalVideoContinuationRecord> SubmitGoalVideoReturnAsync(
            string goal, JsonElement payload, CancellationToken cancellationToken) =>
            GetGoalVideoContinuationAsync(goal, cancellationToken);
    }

    private sealed class PendingDeliveryObserver : IPostProductionDeliveryObserver
    {
        private TaskCompletionSource<bool> _pending = NewPending();
        public int OpenCalls;

        public GoalDeliverySnapshot Observe(string? goalId, GoalVideoContinuationRecord? continuation) =>
            continuation is { ProductionStatus: "production_ready" }
                ? new GoalDeliverySnapshot(goalId, continuation.ProductionJobId,
                    GoalDeliveryPhase.MasteredReady, "最终成片已就绪", true)
                : GoalDeliverySnapshot.Idle(goalId, continuation?.ProductionJobId);

        public Task<bool> OpenCurrentAsync(CancellationToken cancellationToken = default)
        {
            Interlocked.Increment(ref OpenCalls);
            return _pending.Task;
        }

        public void Resolve(bool accepted) => _pending.TrySetResult(accepted);

        public void Reset() => _pending = NewPending();

        private static TaskCompletionSource<bool> NewPending() =>
            new(TaskCreationOptions.RunContinuationsAsynchronously);
    }

    private static async Task OnDispatcherAsync(Func<Task> action)
    {
        var completed = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var thread = new Thread(() =>
        {
            var dispatcher = Dispatcher.CurrentDispatcher;
            SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(dispatcher));
            dispatcher.BeginInvoke(async () =>
            {
                try
                {
                    await action().ConfigureAwait(true);
                    completed.TrySetResult(true);
                }
                catch (Exception ex)
                {
                    completed.TrySetException(ex);
                }
                finally
                {
                    dispatcher.BeginInvokeShutdown(DispatcherPriority.Background);
                }
            }, DispatcherPriority.Normal);
            Dispatcher.Run();
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.IsBackground = true;
        thread.Start();
        await completed.Task.WaitAsync(TimeSpan.FromSeconds(15)).ConfigureAwait(false);
        if (!thread.Join(TimeSpan.FromSeconds(5)))
        {
            throw new TimeoutException("C009C WPF dispatcher failed to shut down");
        }
    }
}
