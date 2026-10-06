using System.Windows;
using System.Windows.Input;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>同进程透明桌宠窗口；只复用 Shell 的只读 PetPresentation。</summary>
public partial class FloatingPetWindow : Window
{
    private const double EdgeSnapThreshold = 24d;

    // Size presets     : bounded layout presets avoid arbitrary resizing and keep hit targets usable.
    private static readonly (double Width, double Height, string Label)[] SizePresets =
    {
        (214d, 220d, "100%"),
        (248d, 255d, "115%"),
        (282d, 290d, "130%"),
    };

    private bool _positionInitialized;
    private bool _clampingPosition;
    private int _sizePresetIndex;

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
        UpdateSizeLabel();
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
        if (e.ChangedButton != MouseButton.Left)
        {
            return;
        }

        var edgeSnapped = false;
        FloatingPet.BeginFloatingWindowDrag();
        try
        {
            DragMove();
            edgeSnapped = SnapToNearestEdge();
        }
        catch (InvalidOperationException)
        {
            // Drag boundary   : a lost mouse button cancels only the window move.
        }
        finally
        {
            FloatingPet.EndFloatingWindowDrag(edgeSnapped);
        }

        e.Handled = true;
    }

    private void SizeButton_Click(object sender, RoutedEventArgs e)
    {
        CyclePetSize();
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

    /// <summary>依次切换经过验收的固定尺寸，并在缩放后重新限制到虚拟桌面内。</summary>
    private void CyclePetSize()
    {
        _sizePresetIndex = (_sizePresetIndex + 1) % SizePresets.Length;
        var preset = SizePresets[_sizePresetIndex];

        Width  = preset.Width;
        Height = preset.Height;
        MinWidth  = preset.Width;
        MinHeight = preset.Height;

        UpdateSizeLabel();
        ClampToVirtualDesktop();
    }

    /// <summary>拖动结束时只在接近虚拟桌面边缘时吸附；返回是否真的发生吸附供 Motion Engine 做站稳。</summary>
    private bool SnapToNearestEdge()
    {
        if (ActualWidth <= 0 || ActualHeight <= 0)
        {
            return false;
        }

        var minLeft = SystemParameters.VirtualScreenLeft;
        var minTop  = SystemParameters.VirtualScreenTop;
        var maxLeft = minLeft + Math.Max(0, SystemParameters.VirtualScreenWidth - ActualWidth);
        var maxTop  = minTop + Math.Max(0, SystemParameters.VirtualScreenHeight - ActualHeight);

        var distanceLeft   = Math.Abs(Left - minLeft);
        var distanceRight  = Math.Abs(maxLeft - Left);
        var distanceTop    = Math.Abs(Top - minTop);
        var distanceBottom = Math.Abs(maxTop - Top);
        var nearest = Math.Min(
            Math.Min(distanceLeft, distanceRight),
            Math.Min(distanceTop, distanceBottom));

        if (nearest > EdgeSnapThreshold)
        {
            return false;
        }

        if (nearest == distanceLeft)
        {
            Left = minLeft;
        }
        else if (nearest == distanceRight)
        {
            Left = maxLeft;
        }
        else if (nearest == distanceTop)
        {
            Top = minTop;
        }
        else
        {
            Top = maxTop;
        }

        ClampToVirtualDesktop();
        return true;
    }

    private void UpdatePinLabel() =>
        PinButton.Content = Topmost ? "取消置顶" : "置顶";

    private void UpdateSizeLabel() =>
        SizeButton.Content = SizePresets[_sizePresetIndex].Label;

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
