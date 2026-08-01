using System.Windows.Input;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>防止重复执行并把异常交给显式处理器的异步命令。</summary>
public sealed class AsyncRelayCommand : ICommand
{
    private readonly Func<Task> _execute;
    private readonly Func<bool>? _canExecute;
    private readonly Action<Exception> _onError;
    private bool _isRunning;

    /// <summary>创建异步命令。</summary>
    public AsyncRelayCommand(
        Func<Task> execute,
        Action<Exception> onError,
        Func<bool>? canExecute = null)
    {
        _execute    = execute;
        _onError    = onError;
        _canExecute = canExecute;
    }

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter) =>
        !_isRunning && (_canExecute?.Invoke() ?? true);

    public async void Execute(object? parameter)
    {
        if (!CanExecute(parameter))
        {
            return;
        }
        _isRunning = true;
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
        try
        {
            await _execute();
        }
        catch (Exception exception)
        {
            _onError(exception);
        }
        finally
        {
            _isRunning = false;
            CanExecuteChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    /// <summary>外部状态变化后刷新可执行状态。</summary>
    public void NotifyCanExecuteChanged() =>
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}
