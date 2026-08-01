using System.Windows.Threading;

namespace PicotooPet.Desktop.Services;

/// <summary>WPF Dispatcher 的可测试适配器。</summary>
public sealed class WpfUiDispatcher : IUiDispatcher
{
    private readonly Dispatcher _dispatcher;

    /// <summary>绑定应用主 Dispatcher。</summary>
    public WpfUiDispatcher(Dispatcher dispatcher)
    {
        _dispatcher = dispatcher;
    }

    /// <summary>异步执行短小 UI 状态变更。</summary>
    public Task InvokeAsync(Action action, CancellationToken cancellationToken = default) =>
        _dispatcher.InvokeAsync(action, DispatcherPriority.DataBind, cancellationToken).Task;
}
