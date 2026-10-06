using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Production 客户端在配对生命周期内复用、重连替换、并发共享和仅释放一次。</summary>
internal static class ProductionClientHolderSmokeTests
{
    public static async Task RunAsync()
    {
        var baseA = new Uri("http://mac-a.local:8787/");
        var baseB = new Uri("http://mac-b.local:8787/");

        // 同一会话内多次操作复用同一个客户端/handler。
        var created = new List<RecordingHandler>();
        await using (var holder = new ProductionClientHolder(options => Create(options, created)))
        {
            for (var i = 0; i < 5; i++)
            {
                await using var lease = holder.Acquire(baseA, "token-1");
                await lease.Client.GetJobsAsync(CancellationToken.None).ConfigureAwait(false);
            }
            SmokeAssert.Equal(1, created.Count, "多次 Production 调用必须复用同一个 handler");
            SmokeAssert.Equal(5, created[0].Requests, "所有调用都应经过同一个连接池");
            SmokeAssert.Equal(0, created[0].Disposed, "单次调用结束不得释放共享客户端");

            // 并发调用共享同一个池，不产生重复 handler。
            var concurrent = Enumerable.Range(0, 16).Select(async _ =>
            {
                await using var lease = holder.Acquire(baseA, "token-1");
                await lease.Client.GetJobsAsync(CancellationToken.None).ConfigureAwait(false);
            });
            await Task.WhenAll(concurrent).ConfigureAwait(false);
            SmokeAssert.Equal(1, created.Count, "并发调用不得创建重复连接池");

            // 重连：地址或令牌变化时释放旧客户端，新客户端绑定新地址/令牌。
            await using (var lease = holder.Acquire(baseB, "token-2"))
            {
                SmokeAssert.Equal(2, created.Count, "地址/令牌替换必须创建新客户端");
                SmokeAssert.Equal(1, created[0].Disposed, "替换后旧客户端必须释放一次");
                await lease.Client.GetJobsAsync(CancellationToken.None).ConfigureAwait(false);
            }
            SmokeAssert.Equal(baseB.Host, created[1].LastRequestHost!, "新客户端必须使用新地址");
            SmokeAssert.Equal("Bearer token-2", created[1].LastAuthorization!, "新客户端必须使用新令牌");
            SmokeAssert.True(!string.IsNullOrEmpty(created[1].LastTraceId), "trace id 头必须保持");

            // 仅令牌变化同样替换。
            await using (holder.Acquire(baseB, "token-3")) { }
            SmokeAssert.Equal(3, created.Count, "令牌变化必须替换客户端");
            SmokeAssert.Equal(1, created[1].Disposed, "旧令牌客户端必须释放");

            // 退役（重连/连接失败）释放当前客户端，之后重新创建。
            await holder.RetireAsync().ConfigureAwait(false);
            SmokeAssert.Equal(1, created[2].Disposed, "退役必须释放当前客户端");
            await using (holder.Acquire(baseB, "token-3")) { }
            SmokeAssert.Equal(4, created.Count, "退役后必须重新创建，不得复用旧客户端");
        }
        SmokeAssert.True(created.All(handler => handler.Disposed == 1), "会话释放后每个客户端恰好释放一次");

        // 在途调用期间被替换：旧客户端等调用归还后才释放。
        created.Clear();
        var inflightHolder = new ProductionClientHolder(options => Create(options, created));
        var oldLease = inflightHolder.Acquire(baseA, "token-1");
        await using (inflightHolder.Acquire(baseB, "token-2")) { }
        SmokeAssert.Equal(0, created[0].Disposed, "在途调用未结束前不得释放旧客户端");
        await oldLease.DisposeAsync().ConfigureAwait(false);
        await oldLease.DisposeAsync().ConfigureAwait(false);
        SmokeAssert.Equal(1, created[0].Disposed, "在途调用归还后旧客户端释放且仅一次");

        // 重复 Dispose 只关闭一次，释放后不得再取客户端。
        await inflightHolder.DisposeAsync().ConfigureAwait(false);
        await inflightHolder.DisposeAsync().ConfigureAwait(false);
        SmokeAssert.True(created.All(handler => handler.Disposed == 1), "重复释放不得二次关闭");
        var rejected = false;
        try
        {
            inflightHolder.Acquire(baseA, "token-1");
        }
        catch (ObjectDisposedException)
        {
            rejected = true;
        }
        SmokeAssert.True(rejected, "释放后的会话不得再创建 Production 客户端");

        // 创建失败不泄漏，且保留原客户端。
        created.Clear();
        var fail = false;
        await using (var failing = new ProductionClientHolder(options =>
        {
            if (fail)
            {
                throw new InvalidOperationException("setup failed");
            }
            return Create(options, created);
        }))
        {
            await using (failing.Acquire(baseA, "token-1")) { }
            fail = true;
            var threw = false;
            try
            {
                failing.Acquire(baseB, "token-2");
            }
            catch (InvalidOperationException)
            {
                threw = true;
            }
            SmokeAssert.True(threw, "工厂失败必须向调用方抛出");
            SmokeAssert.Equal(1, created.Count, "失败的替换不得留下额外客户端");
            SmokeAssert.Equal(0, created[0].Disposed, "失败的替换不得提前释放仍有效的客户端");
        }
        SmokeAssert.Equal(1, created[0].Disposed, "失败后会话释放仍须关闭客户端");
    }

    private static MacCoreProductionClient Create(
        MacCoreClientOptions options,
        List<RecordingHandler> created)
    {
        var handler = new RecordingHandler();
        lock (created)
        {
            created.Add(handler);
        }
        var http = new HttpClient(handler, disposeHandler: true) { BaseAddress = options.BaseUri };
        return MacCoreProductionClient.CreateOwning(http, options.Token);
    }

    private sealed class RecordingHandler : HttpMessageHandler
    {
        private int _requests;
        private int _disposed;

        public int Requests => Volatile.Read(ref _requests);
        public int Disposed => Volatile.Read(ref _disposed);
        public string? LastRequestHost { get; private set; }
        public string? LastAuthorization { get; private set; }
        public string? LastTraceId { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _requests);
            LastRequestHost = request.RequestUri?.Host;
            LastAuthorization = request.Headers.Authorization?.ToString()
                ?? (request.Headers.TryGetValues("Authorization", out var values) ? values.FirstOrDefault() : null);
            LastTraceId = request.Headers.TryGetValues("X-Picotoo-Trace-Id", out var trace)
                ? trace.FirstOrDefault()
                : null;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("[]", Encoding.UTF8, "application/json"),
            });
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                Interlocked.Increment(ref _disposed);
            }
            base.Dispose(disposing);
        }
    }
}
