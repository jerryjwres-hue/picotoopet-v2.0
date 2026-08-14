using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using WpfMouseEventArgs = System.Windows.Input.MouseEventArgs;
using WpfUserControl = System.Windows.Controls.UserControl;

namespace PicotooPet.Desktop.Controls.PetMascot;

/// <summary>
/// 茅台轻量互动组件：只负责视觉、鼠标互动和气泡事件；任何展示失败都不向宿主业务链路抛出。
/// </summary>
public partial class PetMascotControl : WpfUserControl
{
    private static readonly Duration QuickMotionDuration =
        new(TimeSpan.FromMilliseconds(150));

    private readonly DispatcherTimer _ambientHintTimer;
    private readonly DispatcherTimer _calloutTimer;
    private readonly DispatcherTimer _workingTimer;
    private readonly DispatcherTimer _blinkTimer;

    private bool _workingBeat;

    public static readonly DependencyProperty StateProperty = DependencyProperty.Register(
        nameof(State),
        typeof(PetMascotState),
        typeof(PetMascotControl),
        new PropertyMetadata(PetMascotState.Idle, OnStateChanged));

    public static readonly DependencyProperty PendingReviewCountProperty = DependencyProperty.Register(
        nameof(PendingReviewCount),
        typeof(int),
        typeof(PetMascotControl),
        new PropertyMetadata(0));

    public static readonly DependencyProperty InProgressCountProperty = DependencyProperty.Register(
        nameof(InProgressCount),
        typeof(int),
        typeof(PetMascotControl),
        new PropertyMetadata(0, OnInProgressCountChanged));

    public static readonly DependencyProperty CompletedCountProperty = DependencyProperty.Register(
        nameof(CompletedCount),
        typeof(int),
        typeof(PetMascotControl),
        new PropertyMetadata(0));

    public PetMascotControl()
    {
        InitializeComponent();

        _ambientHintTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMinutes(24),
        };
        _ambientHintTimer.Tick += OnAmbientHintTick;

        _calloutTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(8),
        };
        _calloutTimer.Tick += OnCalloutTimerTick;

        _workingTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(850),
        };
        _workingTimer.Tick += OnWorkingTimerTick;

        _blinkTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(5.2),
        };
        _blinkTimer.Tick += OnBlinkTimerTick;

        ApplyStateSafely();
    }

    /// <summary>宿主只写入展示状态；组件不会反向修改任务或 Worker 状态。</summary>
    public PetMascotState State
    {
        get => (PetMascotState)GetValue(StateProperty);
        set => SetValue(StateProperty, value);
    }

    /// <summary>仅用于选择一句本地提示，不触发任何业务查询。</summary>
    public int PendingReviewCount
    {
        get => (int)GetValue(PendingReviewCountProperty);
        set => SetValue(PendingReviewCountProperty, value);
    }

    /// <summary>仅用于选择一句本地提示，并让默认待机状态轻量跟随“是否有任务在跑”。</summary>
    public int InProgressCount
    {
        get => (int)GetValue(InProgressCountProperty);
        set => SetValue(InProgressCountProperty, value);
    }

    /// <summary>仅用于选择一句本地提示，不触发任何业务查询。</summary>
    public int CompletedCount
    {
        get => (int)GetValue(CompletedCountProperty);
        set => SetValue(CompletedCountProperty, value);
    }

    /// <summary>用户选择“新建任务”时通知宿主；组件本身不创建任务。</summary>
    public event EventHandler? NewTaskRequested;

    /// <summary>用户选择“看看进度”时通知宿主；组件本身不执行导航。</summary>
    public event EventHandler? ProgressRequested;

    /// <summary>点击茅台时显示一条短句和两个已有功能的轻量入口。</summary>
    public void ShowInteractionCallout() =>
        ShowCalloutSafely(showActions: true, autoHideAfter: TimeSpan.FromSeconds(11));

    private static void OnStateChanged(
        DependencyObject dependencyObject,
        DependencyPropertyChangedEventArgs eventArgs)
    {
        if (dependencyObject is PetMascotControl control)
        {
            control.ApplyStateSafely();
        }
    }

    private static void OnInProgressCountChanged(
        DependencyObject dependencyObject,
        DependencyPropertyChangedEventArgs eventArgs)
    {
        if (dependencyObject is PetMascotControl control && control.State == PetMascotState.Idle)
        {
            control.ApplyStateSafely();
        }
    }

    private void OnLoaded(object sender, RoutedEventArgs eventArgs)
    {
        TryPresentationOperation(() =>
        {
            ApplyStateCore();
            _ambientHintTimer.Start();
        });
    }

    private void OnUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        StopAllTimers();
        StopMotionAnimations();
    }

    private void OnMouseEnter(object sender, WpfMouseEventArgs eventArgs)
    {
        TryPresentationOperation(() =>
        {
            AnimateDouble(HoverScale, ScaleTransform.ScaleXProperty, 1.03, QuickMotionDuration);
            AnimateDouble(HoverScale, ScaleTransform.ScaleYProperty, 1.03, QuickMotionDuration);
            AnimateDouble(HoverRotate, RotateTransform.AngleProperty, 1.6, QuickMotionDuration);
        });
    }

    private void OnMouseMove(object sender, WpfMouseEventArgs eventArgs)
    {
        TryPresentationOperation(() =>
        {
            if (MascotStage.ActualWidth <= 1 || MascotStage.ActualHeight <= 1)
            {
                return;
            }

            var position = eventArgs.GetPosition(MascotStage);
            var normalizedX = (position.X / MascotStage.ActualWidth) - 0.5;
            var normalizedY = (position.Y / MascotStage.ActualHeight) - 0.5;
            var targetX = Math.Clamp(normalizedX * 10.0, -5.0, 5.0);
            var targetY = Math.Clamp(normalizedY * 5.0, -2.5, 2.5);

            AnimateDouble(PointerTranslate, TranslateTransform.XProperty, targetX, QuickMotionDuration);
            AnimateDouble(PointerTranslate, TranslateTransform.YProperty, targetY, QuickMotionDuration);
        });
    }

    private void OnMouseLeave(object sender, WpfMouseEventArgs eventArgs)
    {
        TryPresentationOperation(() =>
        {
            AnimateDouble(HoverScale, ScaleTransform.ScaleXProperty, 1.0, QuickMotionDuration);
            AnimateDouble(HoverScale, ScaleTransform.ScaleYProperty, 1.0, QuickMotionDuration);
            AnimateDouble(HoverRotate, RotateTransform.AngleProperty, 0.0, QuickMotionDuration);
            AnimateDouble(PointerTranslate, TranslateTransform.XProperty, 0.0, QuickMotionDuration);
            AnimateDouble(PointerTranslate, TranslateTransform.YProperty, 0.0, QuickMotionDuration);
        });
    }

    private void OnMouseLeftButtonUp(object sender, MouseButtonEventArgs eventArgs)
    {
        eventArgs.Handled = true;
        TryPresentationOperation(() =>
        {
            PlayClickPulse();
            ShowInteractionCallout();
        });
    }

    private void OnNewTaskClick(object sender, RoutedEventArgs eventArgs)
    {
        eventArgs.Handled = true;
        HideCalloutSafely();
        RaiseHostEventSafely(NewTaskRequested);
    }

    private void OnProgressClick(object sender, RoutedEventArgs eventArgs)
    {
        eventArgs.Handled = true;
        HideCalloutSafely();
        RaiseHostEventSafely(ProgressRequested);
    }

    private void OnAmbientHintTick(object? sender, EventArgs eventArgs)
    {
        if (!IsLoaded || !IsVisible || CalloutBorder.Visibility == Visibility.Visible)
        {
            return;
        }

        ShowCalloutSafely(showActions: false, autoHideAfter: TimeSpan.FromSeconds(7));
    }

    private void OnCalloutTimerTick(object? sender, EventArgs eventArgs) =>
        HideCalloutSafely();

    private void OnWorkingTimerTick(object? sender, EventArgs eventArgs)
    {
        if (ResolveEffectiveState() != PetMascotState.Working)
        {
            _workingTimer.Stop();
            return;
        }

        _workingBeat = !_workingBeat;
        AnimateDouble(
            ClickScale,
            ScaleTransform.ScaleYProperty,
            _workingBeat ? 1.012 : 1.0,
            new Duration(TimeSpan.FromMilliseconds(180)));
    }

    private void OnBlinkTimerTick(object? sender, EventArgs eventArgs)
    {
        if (ResolveEffectiveState() != PetMascotState.Idle)
        {
            _blinkTimer.Stop();
            return;
        }

        PlayIdleMicroMotion();
    }

    private void ApplyStateSafely() =>
        TryPresentationOperation(ApplyStateCore);

    private void ApplyStateCore()
    {
        _workingTimer.Stop();
        _blinkTimer.Stop();
        _workingBeat = false;

        switch (ResolveEffectiveState())
        {
            case PetMascotState.Working:
                SetMascotImageCore("working_a.png");
                StartBreathing(amplitude: -1.3, duration: TimeSpan.FromSeconds(1.4));
                _workingTimer.Start();
                break;

            case PetMascotState.Success:
                SetMascotImageCore("greeting_success.png");
                StartBreathing(amplitude: -2.0, duration: TimeSpan.FromSeconds(1.1));
                PlayClickPulse();
                break;

            case PetMascotState.Away:
                SetMascotImageCore("away.png");
                StartBreathing(amplitude: -1.5, duration: TimeSpan.FromSeconds(1.8));
                break;

            case PetMascotState.Bath:
                SetMascotImageCore("bath.png");
                StartBreathing(amplitude: -1.0, duration: TimeSpan.FromSeconds(2.0));
                break;

            case PetMascotState.Offline:
                SetMascotImageCore("idle.png");
                StartBreathing(amplitude: -1.1, duration: TimeSpan.FromSeconds(2.8));
                break;

            default:
                SetMascotImageCore("idle.png");
                StartBreathing(amplitude: -2.2, duration: TimeSpan.FromSeconds(2.1));
                _blinkTimer.Start();
                break;
        }
    }

    private PetMascotState ResolveEffectiveState() =>
        State == PetMascotState.Idle && InProgressCount > 0
            ? PetMascotState.Working
            : State;

    private void SetMascotImageCore(string fileName)
    {
        BitmapImage bitmap;

        try
        {
            bitmap = LoadEmbeddedRaster(fileName);
        }
        catch (Exception) when (!string.Equals(fileName, "idle.png", StringComparison.Ordinal))
        {
            bitmap = LoadEmbeddedRaster("idle.png");
        }

        MascotImage.Source = bitmap;
        MascotImage.Visibility = Visibility.Visible;
    }

    private static BitmapImage LoadEmbeddedRaster(string fileName)
    {
        var resourceUri = new Uri(
            $"pack://application:,,,/Assets/PetMascot/{fileName}.b64",
            UriKind.Absolute);
        var resource = System.Windows.Application.GetResourceStream(resourceUri)
            ?? throw new InvalidOperationException($"茅台素材不存在：{fileName}");

        using var reader = new StreamReader(resource.Stream);
        var encoded = reader.ReadToEnd();
        var bytes = Convert.FromBase64String(encoded);
        using var stream = new MemoryStream(bytes, writable: false);

        var bitmap = new BitmapImage();
        bitmap.BeginInit();
        bitmap.CacheOption = BitmapCacheOption.OnLoad;
        bitmap.StreamSource = stream;
        bitmap.EndInit();
        bitmap.Freeze();
        return bitmap;
    }

    private void StartBreathing(double amplitude, TimeSpan duration)
    {
        BreathTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        BreathTranslate.Y = 0;
        BreathTranslate.BeginAnimation(
            TranslateTransform.YProperty,
            new DoubleAnimation
            {
                From = 0,
                To = amplitude,
                Duration = new Duration(duration),
                AutoReverse = true,
                RepeatBehavior = RepeatBehavior.Forever,
                EasingFunction = new SineEase
                {
                    EasingMode = EasingMode.EaseInOut,
                },
            });
    }

    private void PlayIdleMicroMotion()
    {
        BreathTranslate.BeginAnimation(
            TranslateTransform.XProperty,
            new DoubleAnimation
            {
                From = 0,
                To = 0.9,
                Duration = new Duration(TimeSpan.FromMilliseconds(130)),
                AutoReverse = true,
                EasingFunction = new SineEase
                {
                    EasingMode = EasingMode.EaseInOut,
                },
            });
    }

    private void PlayClickPulse()
    {
        var pulseX = new DoubleAnimation
        {
            From = 1,
            To = 1.055,
            Duration = new Duration(TimeSpan.FromMilliseconds(115)),
            AutoReverse = true,
            EasingFunction = new CubicEase
            {
                EasingMode = EasingMode.EaseOut,
            },
        };
        var pulseY = pulseX.Clone();

        ClickScale.BeginAnimation(ScaleTransform.ScaleXProperty, pulseX);
        ClickScale.BeginAnimation(ScaleTransform.ScaleYProperty, pulseY);
    }

    private void ShowCalloutSafely(bool showActions, TimeSpan autoHideAfter)
    {
        TryPresentationOperation(() =>
        {
            CalloutText.Text = PetMascotPromptPolicy.Select(
                ResolveEffectiveState(),
                PendingReviewCount,
                InProgressCount,
                CompletedCount);
            CalloutActions.Visibility = showActions
                ? Visibility.Visible
                : Visibility.Collapsed;
            CalloutBorder.Visibility = Visibility.Visible;
            CalloutBorder.Opacity = 0;
            CalloutBorder.BeginAnimation(
                OpacityProperty,
                new DoubleAnimation
                {
                    From = 0,
                    To = 1,
                    Duration = new Duration(TimeSpan.FromMilliseconds(180)),
                });

            _calloutTimer.Stop();
            _calloutTimer.Interval = autoHideAfter;
            _calloutTimer.Start();
        });
    }

    private void HideCalloutSafely()
    {
        TryPresentationOperation(() =>
        {
            _calloutTimer.Stop();
            CalloutBorder.BeginAnimation(OpacityProperty, null);
            CalloutBorder.Opacity = 1;
            CalloutBorder.Visibility = Visibility.Collapsed;
        });
    }

    private void RaiseHostEventSafely(EventHandler? handler)
    {
        if (handler is null)
        {
            return;
        }

        try
        {
            handler.Invoke(this, EventArgs.Empty);
        }
        catch (Exception)
        {
            // 宿主快捷入口异常不能由茅台组件扩大成主程序崩溃。                        // 安全边界
        }
    }

    private void StopAllTimers()
    {
        _ambientHintTimer.Stop();
        _calloutTimer.Stop();
        _workingTimer.Stop();
        _blinkTimer.Stop();
    }

    private void StopMotionAnimations()
    {
        BreathTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        BreathTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        PointerTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        PointerTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        HoverScale.BeginAnimation(ScaleTransform.ScaleXProperty, null);
        HoverScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
        HoverRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        ClickScale.BeginAnimation(ScaleTransform.ScaleXProperty, null);
        ClickScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
    }

    private static void AnimateDouble(
        Animatable target,
        DependencyProperty property,
        double value,
        Duration duration)
    {
        target.BeginAnimation(
            property,
            new DoubleAnimation
            {
                To = value,
                Duration = duration,
                EasingFunction = new CubicEase
                {
                    EasingMode = EasingMode.EaseOut,
                },
                FillBehavior = FillBehavior.HoldEnd,
            });
    }

    private void TryPresentationOperation(Action action)
    {
        try
        {
            action();
        }
        catch (Exception)
        {
            StopAllTimers();
            MascotImage.Visibility = Visibility.Collapsed;                                // 茅台失败只隐藏自身
            CalloutBorder.Visibility = Visibility.Collapsed;                              // 不把异常扩散给宿主
        }
    }
}
