using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace PicotooPet.Desktop.Views;

/// <summary>隔离单个页面在 WPF Measure/Arrange 阶段抛出的可恢复异常。</summary>
public sealed class NavigationContentHost : ContentControl
{
    private object? _faultedContent;
    private bool _faultNotificationQueued;

    /// <summary>页面布局故障被隔离后，在 Dispatcher 上发布一次恢复通知。</summary>
    public event EventHandler<NavigationFaultEventArgs>? NavigationFaulted;

    /// <summary>执行子页面 Measure；可恢复异常只隔离当前内容。</summary>
    protected override Size MeasureOverride(Size constraint)
    {
        if (ReferenceEquals(_faultedContent, Content))
        {
            return new Size();
        }

        ResetFaultStateForReplacementContent();
        try
        {
            return base.MeasureOverride(constraint);
        }
        catch (Exception exception) when (IsRecoverable(exception))
        {
            QueueFaultNotification(exception);
            return new Size();
        }
    }

    /// <summary>执行子页面 Arrange；已故障内容不再进入重复布局。</summary>
    protected override Size ArrangeOverride(Size arrangeBounds)
    {
        if (ReferenceEquals(_faultedContent, Content))
        {
            return arrangeBounds;
        }

        ResetFaultStateForReplacementContent();
        try
        {
            return base.ArrangeOverride(arrangeBounds);
        }
        catch (Exception exception) when (IsRecoverable(exception))
        {
            QueueFaultNotification(exception);
            return arrangeBounds;
        }
    }

    /// <summary>新内容替换故障内容后，允许正常布局并接受新的独立故障。</summary>
    private void ResetFaultStateForReplacementContent()
    {
        if (_faultedContent is null || ReferenceEquals(_faultedContent, Content))
        {
            return;
        }

        _faultedContent          = null;
        _faultNotificationQueued = false;
    }

    /// <summary>冻结当前故障内容，并避免同一布局异常重复通知 Shell。</summary>
    private void QueueFaultNotification(Exception exception)
    {
        var failedContent = Content;
        _faultedContent = failedContent;
        if (_faultNotificationQueued)
        {
            return;
        }

        _faultNotificationQueued = true;
        _ = Dispatcher.BeginInvoke(
            DispatcherPriority.Send,
            new Action(() =>
            {
                NavigationFaulted?.Invoke(
                    this,
                    new NavigationFaultEventArgs(failedContent, exception));
            }));
    }

    /// <summary>进程或运行时完整性异常不得被页面级边界吞掉。</summary>
    private static bool IsRecoverable(Exception exception) => exception is not
        (OutOfMemoryException or
         AccessViolationException or
         BadImageFormatException or
         CannotUnloadAppDomainException or
         InvalidProgramException or
         SEHException);
}

/// <summary>描述被隔离的页面内容和原始布局异常。</summary>
public sealed class NavigationFaultEventArgs : EventArgs
{
    /// <summary>创建不可变的页面故障通知。</summary>
    public NavigationFaultEventArgs(
        object? failedContent,
        Exception exception)
    {
        FailedContent = failedContent;
        Exception     = exception ?? throw new ArgumentNullException(nameof(exception));
    }

    /// <summary>发生故障时绑定到内容宿主的页面模型。</summary>
    public object? FailedContent { get; }

    /// <summary>由页面布局流水线抛出的原始异常。</summary>
    public Exception Exception { get; }
}
