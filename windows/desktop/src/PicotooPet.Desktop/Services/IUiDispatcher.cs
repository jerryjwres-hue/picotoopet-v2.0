namespace PicotooPet.Desktop.Services;

/// <summary>把状态更新安全调度到 WPF UI 线程。</summary>
public interface IUiDispatcher
{
    Task InvokeAsync(Action action, CancellationToken cancellationToken = default);
}
