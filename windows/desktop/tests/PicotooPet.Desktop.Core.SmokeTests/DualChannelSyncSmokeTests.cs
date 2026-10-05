using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 REST 真相通道与 WebSocket 实时通道互不误伤，并可从实时降级恢复。</summary>
internal static class DualChannelSyncSmokeTests
{
    /// <summary>执行双通道状态、自适应轮询与恢复合同。</summary>
    public static async Task RunAsync()
    {
        VerifyRestHealthyKeepsSystemUsableWhenRealtimeDegradesAndRecovers();
        await VerifyPollerAcceleratesDuringRealtimeDegradationAsync().ConfigureAwait(false);
    }

    private static void VerifyRestHealthyKeepsSystemUsableWhenRealtimeDegradesAndRecovers()
    {
        var store = new ConnectionStateStore();

        store.SetCoreReachability(reachable: true);
        store.SetEventStreamState(ConnectionState.Online);
        SmokeAssert.True(store.Snapshot.State == ConnectionState.Online, "双通道健康时系统必须在线");
        SmokeAssert.True(!store.Snapshot.RealtimeDegraded, "健康实时通道不得标记降级");

        store.SetEventStreamState(ConnectionState.Reconnecting, "fixture websocket silent");

        SmokeAssert.True(store.Snapshot.CoreReachable, "WebSocket 降级不得抹掉 REST Core 健康事实");
        SmokeAssert.True(store.Snapshot.State == ConnectionState.Online, "REST 健康时系统仍必须可用");
        SmokeAssert.True(store.Snapshot.RealtimeDegraded, "WebSocket 重连时必须单独标记实时通道降级");
        SmokeAssert.True(
            store.Snapshot.EventStreamState == ConnectionState.Reconnecting,
            "实时通道状态必须保留独立事实");

        store.SetEventStreamState(ConnectionState.Online);

        SmokeAssert.True(store.Snapshot.CoreReachable, "实时通道恢复不得改写 REST Core 健康事实");
        SmokeAssert.True(store.Snapshot.State == ConnectionState.Online, "实时通道恢复后系统必须继续在线");
        SmokeAssert.True(!store.Snapshot.RealtimeDegraded, "实时通道恢复后必须清除降级标记");
        SmokeAssert.True(
            store.Snapshot.EventStreamState == ConnectionState.Online,
            "恢复后的实时通道状态必须回到 Online");
    }

    private static async Task VerifyPollerAcceleratesDuringRealtimeDegradationAsync()
    {
        var realtimeHealthy = true;
        var polls           = 0;
        var delays          = new List<TimeSpan>();
        using var lifetime  = new CancellationTokenSource();
        var poller = new CoreSnapshotPoller(
            pollSnapshot: _ =>
            {
                polls++;
                if (polls == 1)
                {
                    realtimeHealthy = false;
                }
                if (polls >= 3)
                {
                    lifetime.Cancel();
                }
                return Task.CompletedTask;
            },
            realtimeHealthy: () => realtimeHealthy,
            healthyInterval: TimeSpan.FromSeconds(15),
            degradedInterval: TimeSpan.FromSeconds(3),
            delay: (duration, cancellationToken) =>
            {
                delays.Add(duration);
                cancellationToken.ThrowIfCancellationRequested();
                return Task.CompletedTask;
            });

        try
        {
            await poller.RunAsync(lifetime.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (lifetime.IsCancellationRequested)
        {
            // 第三次确定性轮询后主动结束 fixture。
        }

        SmokeAssert.True(polls == 3, "轮询器必须持续执行 REST 真相校验");
        SmokeAssert.True(delays.Count >= 2, "轮询器必须产生有界调度间隔");
        SmokeAssert.True(
            delays.All(value => value == TimeSpan.FromSeconds(3)),
            "实时通道降级后必须切换到更高频的 REST 对账");
    }
}
