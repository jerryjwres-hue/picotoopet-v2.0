using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// 持有当前配对生命周期内唯一的 Production 客户端；地址或令牌变化时退役旧客户端，
/// 且仅在最后一个在途调用归还后才释放，保证并发调用共享同一连接池且不被中途释放。
/// 令牌与地址只保存在内存，不做任何持久化。
/// </summary>
public sealed class ProductionClientHolder : IAsyncDisposable
{
    private readonly Func<MacCoreClientOptions, MacCoreProductionClient> _factory;
    private readonly object _gate = new();
    private Entry? _current;
    private bool _disposed;

    public ProductionClientHolder(Func<MacCoreClientOptions, MacCoreProductionClient> factory) =>
        _factory = factory ?? throw new ArgumentNullException(nameof(factory));

    /// <summary>取得绑定到指定地址和令牌的客户端租约；绑定不一致时先退役旧客户端。</summary>
    public ProductionClientLease Acquire(Uri baseUri, string token)
    {
        ArgumentNullException.ThrowIfNull(baseUri);
        ArgumentException.ThrowIfNullOrWhiteSpace(token);
        Entry? retired = null;
        Entry entry;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_current is { } existing
                && existing.BaseUri == baseUri
                && string.Equals(existing.Token, token, StringComparison.Ordinal))
            {
                entry = existing;
            }
            else
            {
                // 工厂失败时旧客户端保持原状；新客户端未创建，因此不会泄漏。
                var client = _factory(MacCoreClientOptions.CreateDefault(baseUri, token));
                entry = new Entry(client, baseUri, token);
                retired = _current;
                _current = entry;
            }
            entry.AddLease();
            retired?.Retire();
        }
        retired?.ReleaseIfIdle();
        return new ProductionClientLease(entry);
    }

    /// <summary>退役当前客户端（重连/连接失败）；在途调用归还后释放。</summary>
    public async ValueTask RetireAsync()
    {
        Entry? retired;
        lock (_gate)
        {
            retired = _current;
            _current = null;
            retired?.Retire();
        }
        if (retired is not null)
        {
            retired.ReleaseIfIdle();
            await ValueTask.CompletedTask;
        }
    }

    public async ValueTask DisposeAsync()
    {
        lock (_gate)
        {
            _disposed = true;
        }
        await RetireAsync().ConfigureAwait(false);
    }

    internal sealed class Entry
    {
        private readonly object _gate = new();
        private bool _retired;
        private bool _closed;

        public Entry(MacCoreProductionClient client, Uri baseUri, string token)
        {
            Client = client;
            BaseUri = baseUri;
            Token = token;
        }

        public MacCoreProductionClient Client { get; }
        public Uri BaseUri { get; }
        public string Token { get; }
        private int _leases;

        public void AddLease()
        {
            lock (_gate)
            {
                _leases++;
            }
        }

        public void Retire()
        {
            lock (_gate)
            {
                _retired = true;
            }
        }

        public void ReleaseIfIdle()
        {
            lock (_gate)
            {
                if (!_retired || _closed || _leases > 0)
                {
                    return;
                }
                _closed = true;
            }
            Client.Dispose();
        }

        public ValueTask Return()
        {
            lock (_gate)
            {
                _leases--;
            }
            ReleaseIfIdle();
            return ValueTask.CompletedTask;
        }
    }
}

/// <summary>单次 Production 调用的客户端租约；释放只归还，不关闭共享连接池。</summary>
public sealed class ProductionClientLease : IAsyncDisposable
{
    private ProductionClientHolder.Entry? _entry;

    internal ProductionClientLease(ProductionClientHolder.Entry entry) => _entry = entry;

    public MacCoreProductionClient Client =>
        _entry?.Client ?? throw new ObjectDisposedException(nameof(ProductionClientLease));

    public ValueTask DisposeAsync()
    {
        var entry = Interlocked.Exchange(ref _entry, null);
        return entry?.Return() ?? ValueTask.CompletedTask;
    }
}
