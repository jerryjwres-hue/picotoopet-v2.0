using System.Windows;
using System.Windows.Input;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>同进程透明桌宠窗口；只复用 Shell 的只读 PetPresentation。</summary>
public partial class FloatingPetWindow : Window
{
    private bool _positionInitialized;
    private bool _clampingPosition;

    /// <summary>创建透明桌宠窗口；不会创建第二个 Session 或业务控制器。</summary>
    public FloatingPetWindow(ShellViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
    }

    private void FloatingPetWindow_Loaded(object sender, RoutedEventArgs e)
    {
        if (!_positionInitialized)
        {
            var workArea = SystemParameters.WorkArea;
            Left = Math.Max(workArea.Left + 12, workArea.Right - ActualWidth - 28);
            Top  = Math.Max(workArea.Top + 12, workArea.Bottom - ActualHeight - 28);
            _positionInitialized = true;
        }

        UpdatePinLabel();
        ClampToVirtualDesktop();
    }

    private void FloatingPetWindow_LocationChanged(object? sender, EventArgs e)
    {
        if (_positionInitialized)
        {
            ClampToVirtualDesktop();
        }
    }

    private void DragHandle_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.LeftButton != MouseButtonState.Pressed)
        {
            return;
        }

        try
        {
            DragMove();
        }
        catch (InvalidOperationException)
        {
            // Drag boundary : a lost mouse button cancels only the window move.
        }
        e.Handled = true;
    }

    private void PinButton_Click(object sender, RoutedEventArgs e)
    {
        Topmost = !Topmost;
        UpdatePinLabel();
        e.Handled = true;
    }

    private void ReturnButton_Click(object sender, RoutedEventArgs e)
    {
        Close();
        e.Handled = true;
    }

    private void UpdatePinLabel() =>
        PinButton.Content = Topmost ? "取消置顶" : "置顶";

    private void ClampToVirtualDesktop()
    {
        if (_clampingPosition || ActualWidth <= 0 || ActualHeight <= 0)
        {
            return;
        }

        _clampingPosition = true;
        try
        {
            var minLeft = SystemParameters.VirtualScreenLeft;
            var minTop  = SystemParameters.VirtualScreenTop;
            var maxLeft = minLeft + Math.Max(0, SystemParameters.VirtualScreenWidth - ActualWidth);
            var maxTop  = minTop + Math.Max(0, SystemParameters.VirtualScreenHeight - ActualHeight);

            var clampedLeft = Math.Clamp(Left, minLeft, maxLeft);
            var clampedTop  = Math.Clamp(Top, minTop, maxTop);
            if (!double.IsNaN(clampedLeft))
            {
                Left = clampedLeft;
            }
            if (!double.IsNaN(clampedTop))
            {
                Top = clampedTop;
            }
        }
        finally
        {
            _clampingPosition = false;
        }
    }
}
