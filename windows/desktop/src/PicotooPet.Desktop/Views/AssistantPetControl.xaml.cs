using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>
/// 原生 WPF 多部件桌宠。角色由独立头部、眼睛、耳机、尾巴、前爪和道具组成，
/// 交互只改变视觉表现，不写回任何任务、审批、Core 或 Worker 状态。
/// </summary>
public partial class AssistantPetControl : UserControl
{
    private readonly DispatcherTimer _idleTimer;
    private readonly DispatcherTimer _workingTimer;
    private bool _leftPawTurn;
    private bool _loaded;

    /// <summary>创建桌宠并准备有界动画计时器；未 Loaded 时不会启动后台动画。</summary>
    public AssistantPetControl()
    {
        InitializeComponent();

        _idleTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(2200),
        };
        _idleTimer.Tick += IdleTimer_Tick;

        _workingTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(430),
        };
        _workingTimer.Tick += WorkingTimer_Tick;

        Loaded   += AssistantPetControl_Loaded;
        Unloaded += AssistantPetControl_Unloaded;
    }

    /// <summary>只读桌宠事实投影；由 Shell 从既有 Session 快照生成。</summary>
    public AssistantPetPresentation? Presentation
    {
        get => (AssistantPetPresentation?)GetValue(PresentationProperty);
        set => SetValue(PresentationProperty, value);
    }

    /// <summary>桌宠事实投影依赖属性。</summary>
    public static readonly DependencyProperty PresentationProperty = DependencyProperty.Register(
        nameof(Presentation),
        typeof(AssistantPetPresentation),
        typeof(AssistantPetControl),
        new PropertyMetadata(null, OnPresentationChanged));

    /// <summary>允许在装饰性复用场景关闭鼠标互动。</summary>
    public bool IsInteractive
    {
        get => (bool)GetValue(IsInteractiveProperty);
        set => SetValue(IsInteractiveProperty, value);
    }

    /// <summary>交互开关依赖属性。</summary>
    public static readonly DependencyProperty IsInteractiveProperty = DependencyProperty.Register(
        nameof(IsInteractive),
        typeof(bool),
        typeof(AssistantPetControl),
        new PropertyMetadata(true));

    private static void OnPresentationChanged(
        DependencyObject dependencyObject,
        DependencyPropertyChangedEventArgs eventArgs)
    {
        if (dependencyObject is AssistantPetControl control)
        {
            control.ApplyPresentation(eventArgs.NewValue as AssistantPetPresentation);
        }
    }

    private void AssistantPetControl_Loaded(object sender, RoutedEventArgs e)
    {
        _loaded = true;
        _idleTimer.Start();
        ApplyPresentation(Presentation);
    }

    private void AssistantPetControl_Unloaded(object sender, RoutedEventArgs e)
    {
        _loaded = false;
        _idleTimer.Stop();
        _workingTimer.Stop();
        StopContinuousAnimations();
    }

    /// <summary>按事实状态切换动画集合；任何状态都不会修改 Presentation 本身。</summary>
    private void ApplyPresentation(AssistantPetPresentation? presentation)
    {
        if (presentation is null)
        {
            return;
        }

        PetTitle.Text  = presentation.Title;
        PetDetail.Text = presentation.Detail;
        StatusLamp.Fill = presentation.Indicator switch
        {
            AssistantPetIndicator.Green  => BrushFrom("#FF20C878"),
            AssistantPetIndicator.Orange => BrushFrom("#FFFF9A32"),
            _                            => BrushFrom("#FF8794A8"),
        };

        OfflineZzz.Opacity  = presentation.Mode == AssistantPetMode.Offline ? 1 : 0;
        AttentionMark.Opacity = presentation.Mode is AssistantPetMode.Waiting or AssistantPetMode.Error
            ? 1
            : 0;

        if (!_loaded)
        {
            return;
        }

        StopContinuousAnimations();
        ResetPose();

        switch (presentation.Mode)
        {
            case AssistantPetMode.Working:
                StartTailSway(durationMilliseconds: 720);
                StartBreathing(durationMilliseconds: 1150, scale: 1.035);
                _workingTimer.Start();
                break;

            case AssistantPetMode.Waiting:
                StartTailSway(durationMilliseconds: 980);
                StartBreathing(durationMilliseconds: 1450, scale: 1.025);
                AnimateHeadTilt(7, 460);
                break;

            case AssistantPetMode.Resting:
                StartTailSway(durationMilliseconds: 1250);
                StartBreathing(durationMilliseconds: 1700, scale: 1.03);
                break;

            case AssistantPetMode.Offline:
                EyeScale.ScaleY = 0.14;
                HeadRotate.Angle = -3;
                break;

            case AssistantPetMode.Error:
                StartBreathing(durationMilliseconds: 1050, scale: 1.02);
                AnimateHeadTilt(-7, 250);
                break;
        }
    }

    /// <summary>随机待机动作只作用于独立部件，避免角色像整张图片上下平移。</summary>
    private void IdleTimer_Tick(object? sender, EventArgs e)
    {
        if (!_loaded || Presentation?.Mode == AssistantPetMode.Offline)
        {
            return;
        }

        var action = Random.Shared.Next(0, 4);
        switch (action)
        {
            case 0:
                Blink();
                break;
            case 1:
                AnimateHeadTilt(Random.Shared.Next(-5, 6), 340);
                break;
            case 2:
                AnimatePaw(LeftPawTranslate, lift: -5, durationMilliseconds: 260);
                break;
            default:
                PulseLaptop();
                break;
        }
    }

    /// <summary>工作状态左右爪交替敲击，形成真正的多部件 typing loop。</summary>
    private void WorkingTimer_Tick(object? sender, EventArgs e)
    {
        if (Presentation?.Mode != AssistantPetMode.Working)
        {
            _workingTimer.Stop();
            return;
        }

        var paw = _leftPawTurn ? LeftPawTranslate : RightPawTranslate;
        _leftPawTurn = !_leftPawTurn;
        AnimatePaw(paw, lift: -7, durationMilliseconds: 180);
        PulseLaptop();
    }

    private void PetSurface_MouseMove(object sender, MouseEventArgs e)
    {
        if (!IsInteractive || Presentation?.Mode == AssistantPetMode.Offline)
        {
            return;
        }

        var point = e.GetPosition(PetSurface);
        var x = Math.Clamp((point.X - PetSurface.ActualWidth / 2) / 28, -2.6, 2.6);
        var y = Math.Clamp((point.Y - 92) / 34, -1.7, 1.7);
        SetPupilOffset(x, y);
    }

    private void PetSurface_MouseLeave(object sender, MouseEventArgs e) =>
        SetPupilOffset(0, 0);

    /// <summary>点击不同区域触发摸头、挥爪或敲电脑反馈，不发起任何业务动作。</summary>
    private void PetSurface_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (!IsInteractive)
        {
            return;
        }

        var point = e.GetPosition(PetSurface);
        if (point.Y < 135)
        {
            AnimateHeadTilt(point.X < PetSurface.ActualWidth / 2 ? -9 : 9, 220);
            ShowHeart();
        }
        else if (point.X < PetSurface.ActualWidth * 0.52)
        {
            AnimatePaw(LeftPawTranslate, lift: -12, durationMilliseconds: 250);
        }
        else
        {
            AnimatePaw(RightPawTranslate, lift: -12, durationMilliseconds: 250);
            PulseLaptop();
        }

        e.Handled = true;
    }

    private void Blink()
    {
        var animation = new DoubleAnimation
        {
            From       = 1,
            To         = 0.08,
            Duration   = TimeSpan.FromMilliseconds(90),
            AutoReverse = true,
        };
        EyeScale.BeginAnimation(ScaleTransform.ScaleYProperty, animation);
    }

    private void AnimateHeadTilt(double angle, int durationMilliseconds)
    {
        var animation = new DoubleAnimation
        {
            To          = angle,
            Duration    = TimeSpan.FromMilliseconds(durationMilliseconds),
            AutoReverse = true,
            EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseInOut },
        };
        HeadRotate.BeginAnimation(RotateTransform.AngleProperty, animation);
    }

    private static void AnimatePaw(
        TranslateTransform paw,
        double lift,
        int durationMilliseconds)
    {
        var animation = new DoubleAnimation
        {
            To          = lift,
            Duration    = TimeSpan.FromMilliseconds(durationMilliseconds),
            AutoReverse = true,
            EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut },
        };
        paw.BeginAnimation(TranslateTransform.YProperty, animation);
    }

    private void StartTailSway(int durationMilliseconds)
    {
        var animation = new DoubleAnimation
        {
            From           = -10,
            To             = 14,
            Duration       = TimeSpan.FromMilliseconds(durationMilliseconds),
            AutoReverse    = true,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
        };
        TailRotate.BeginAnimation(RotateTransform.AngleProperty, animation);
    }

    private void StartBreathing(int durationMilliseconds, double scale)
    {
        var animation = new DoubleAnimation
        {
            From           = 1,
            To             = scale,
            Duration       = TimeSpan.FromMilliseconds(durationMilliseconds),
            AutoReverse    = true,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
        };
        BodyScale.BeginAnimation(ScaleTransform.ScaleYProperty, animation);
    }

    private void PulseLaptop()
    {
        var animation = new DoubleAnimation
        {
            From        = 1,
            To          = 1.035,
            Duration    = TimeSpan.FromMilliseconds(120),
            AutoReverse = true,
        };
        LaptopScale.BeginAnimation(ScaleTransform.ScaleXProperty, animation);
        LaptopScale.BeginAnimation(ScaleTransform.ScaleYProperty, animation);
    }

    private void ShowHeart()
    {
        HeartTranslate.Y = 0;
        var opacity = new DoubleAnimation
        {
            From     = 0,
            To       = 1,
            Duration = TimeSpan.FromMilliseconds(120),
            AutoReverse = true,
        };
        var rise = new DoubleAnimation
        {
            From     = 8,
            To       = -15,
            Duration = TimeSpan.FromMilliseconds(420),
            EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut },
        };
        HeartParticle.BeginAnimation(OpacityProperty, opacity);
        HeartTranslate.BeginAnimation(TranslateTransform.YProperty, rise);
    }

    private void SetPupilOffset(double x, double y)
    {
        LeftPupilTranslate.X  = x;
        LeftPupilTranslate.Y  = y;
        RightPupilTranslate.X = x;
        RightPupilTranslate.Y = y;
    }

    private void StopContinuousAnimations()
    {
        _workingTimer.Stop();
        TailRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        BodyScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
    }

    private void ResetPose()
    {
        EyeScale.ScaleY       = 1;
        HeadRotate.Angle      = 0;
        TailRotate.Angle      = -8;
        BodyScale.ScaleY      = 1;
        LeftPawTranslate.Y    = 0;
        RightPawTranslate.Y   = 0;
        LaptopScale.ScaleX    = 1;
        LaptopScale.ScaleY    = 1;
        SetPupilOffset(0, 0);
    }

    private static SolidColorBrush BrushFrom(string value) =>
        new((Color)ColorConverter.ConvertFromString(value));
}
