using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using Brush = System.Windows.Media.Brush;
using Brushes = System.Windows.Media.Brushes;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>原生 WPF 桌宠视图；只消费只读 Presentation，不持有 Session 或业务写入能力。</summary>
public partial class AssistantPetPanel : System.Windows.Controls.UserControl
{
    // Presentation      : mirrors existing Core/Worker/task facts through a dependency property.
    public static readonly DependencyProperty PresentationProperty = DependencyProperty.Register(
        nameof(Presentation),
        typeof(AssistantPetPresentation),
        typeof(AssistantPetPanel),
        new FrameworkPropertyMetadata(null, OnPresentationChanged));

    // Floating mode     : reuses the same articulated renderer while removing sidebar card chrome.
    public static readonly DependencyProperty IsFloatingModeProperty = DependencyProperty.Register(
        nameof(IsFloatingMode),
        typeof(bool),
        typeof(AssistantPetPanel),
        new FrameworkPropertyMetadata(false, OnFloatingModeChanged));

    // Frame timer       : advances independent body-part poses; it never loads remote/sprite content.
    private readonly DispatcherTimer _frameTimer;

    // Behavior scheduler: adds bounded emotion/micro-action overlays without owning business state.
    private readonly PetBehaviorController _behaviorController;

    // Part transforms   : each named WPF shape owns its own motion, so the pet is articulated.
    private readonly RotateTransform _leftEarRotate    = new();
    private readonly RotateTransform _rightEarRotate   = new();
    private readonly RotateTransform _leftPawRotate    = new();
    private readonly RotateTransform _rightPawRotate   = new();
    private readonly ScaleTransform _leftEyeScale      = new(1, 1);
    private readonly ScaleTransform _rightEyeScale     = new(1, 1);
    private readonly ScaleTransform _leftPupilScale    = new(1, 1);
    private readonly ScaleTransform _rightPupilScale   = new(1, 1);
    private readonly TranslateTransform _tongueTranslate = new();

    private AssistantPetMode _activeMode = AssistantPetMode.Resting;
    private AssistantPetMode? _lastMode;
    private PetEmotion? _lastEmotion;
    private int _frameIndex;
    private bool _isLoaded;
    private bool _pointerInside;
    private bool _pointerCaptured;
    private bool _isDragging;
    private System.Windows.Point _pointerDown;

    public AssistantPetPanel()
    {
        _behaviorController = new PetBehaviorController();
        _frameTimer = new DispatcherTimer(DispatcherPriority.Render)
        {
            Interval = TimeSpan.FromMilliseconds(720),
        };
        _frameTimer.Tick += FrameTimer_Tick;

        InitializeComponent();

        // Transform setup  : XAML owns geometry; code only drives bounded presentation motion.
        LeftEar.RenderTransform           = _leftEarRotate;
        RightEar.RenderTransform          = _rightEarRotate;
        LeftPaw.RenderTransform           = _leftPawRotate;
        RightPaw.RenderTransform          = _rightPawRotate;
        LeftEye.RenderTransform           = _leftEyeScale;
        RightEye.RenderTransform          = _rightEyeScale;
        LeftPupil.RenderTransform         = _leftPupilScale;
        RightPupil.RenderTransform        = _rightPupilScale;
        Tongue.RenderTransform            = _tongueTranslate;
        LeftEye.RenderTransformOrigin     = new System.Windows.Point(0.5, 0.5);
        RightEye.RenderTransformOrigin    = new System.Windows.Point(0.5, 0.5);
        LeftPupil.RenderTransformOrigin   = new System.Windows.Point(0.5, 0.5);
        RightPupil.RenderTransformOrigin  = new System.Windows.Point(0.5, 0.5);
        Tongue.RenderTransformOrigin      = new System.Windows.Point(0.5, 0.5);

        Loaded += PetSurface_Loaded;
    }

    /// <summary>请求 Shell 展示同一只桌宠的透明悬浮窗口；事件本身不执行任何业务动作。</summary>
    public event EventHandler? FloatRequested;

    /// <summary>当前桌宠只读展示；nullable 仅覆盖 XAML 初始化窗口。</summary>
    public AssistantPetPresentation? Presentation
    {
        get => (AssistantPetPresentation?)GetValue(PresentationProperty);
        set => SetValue(PresentationProperty, value);
    }

    /// <summary>开启后仅保留角色舞台与微型状态灯，供透明桌面窗口复用。</summary>
    public bool IsFloatingMode
    {
        get => (bool)GetValue(IsFloatingModeProperty);
        set => SetValue(IsFloatingModeProperty, value);
    }

    private static void OnPresentationChanged(
        DependencyObject dependencyObject,
        DependencyPropertyChangedEventArgs args)
    {
        if (dependencyObject is AssistantPetPanel panel)
        {
            panel.ApplyPresentation(args.NewValue as AssistantPetPresentation);
        }
    }

    private static void OnFloatingModeChanged(
        DependencyObject dependencyObject,
        DependencyPropertyChangedEventArgs args)
    {
        if (dependencyObject is AssistantPetPanel panel)
        {
            panel.ApplyFloatingMode(args.NewValue is true);
        }
    }

    private void PetSurface_Loaded(object sender, RoutedEventArgs e)
    {
        _isLoaded = true;
        ApplyFloatingMode(IsFloatingMode);
        ApplyPresentation(Presentation);

        if (IsVisible)
        {
            StartBreathing(_activeMode);
            ConfigureFrameTimer(_activeMode);
        }
    }

    private void ApplyPresentation(AssistantPetPresentation? presentation)
    {
        if (presentation is null)
        {
            ModeTitleText.Text        = "状态读取中";
            DetailText.Text           = "正在读取系统状态…";
            IndicatorDot.Fill         = BrushFrom("#FF8A9AAD");
            FloatingIndicatorDot.Fill = IndicatorDot.Fill;
            _activeMode               = AssistantPetMode.Offline;
            ApplyModeVisuals(_activeMode);
            return;
        }

        ModeTitleText.Text = presentation.Title;
        DetailText.Text    = presentation.Detail;
        var indicatorBrush = presentation.Indicator switch
        {
            AssistantPetIndicator.Green  => BrushFrom("#FF19C37D"),
            AssistantPetIndicator.Orange => BrushFrom("#FFFF8A00"),
            _                            => BrushFrom("#FF8A9AAD"),
        };
        IndicatorDot.Fill         = indicatorBrush;
        FloatingIndicatorDot.Fill = indicatorBrush;

        _activeMode = presentation.Mode;
        _frameIndex = 0;
        ApplyModeVisuals(_activeMode);

        if (_isLoaded && IsVisible)
        {
            if (_lastMode != _activeMode)
            {
                AnimateStateTransition(_activeMode);
            }
            StartBreathing(_activeMode);
            ConfigureFrameTimer(_activeMode);
        }

        _lastMode = _activeMode;
    }

    private void ApplyFloatingMode(bool floating)
    {
        if (CardBorder is null)
        {
            return;
        }

        HeaderPanel.Visibility          = floating ? Visibility.Collapsed : Visibility.Visible;
        DetailText.Visibility           = floating ? Visibility.Collapsed : Visibility.Visible;
        FooterPanel.Visibility          = floating ? Visibility.Collapsed : Visibility.Visible;
        StateStrip.Visibility           = floating ? Visibility.Collapsed : Visibility.Visible;
        FloatingIndicatorDot.Visibility = floating ? Visibility.Visible : Visibility.Collapsed;
        CardBorder.Effect               = floating ? null : CardBorder.Effect;
        CardBorder.Background           = floating
            ? Brushes.Transparent
            : (Brush)FindResource("PetCardBackground");
        CardBorder.BorderBrush = floating
            ? Brushes.Transparent
            : BrushFrom("#FF176AA9");
        CardBorder.BorderThickness = floating
            ? new Thickness(0)
            : new Thickness(1);
        CardBorder.Padding = floating
            ? new Thickness(0)
            : new Thickness(12);
        PetStage.Margin = floating
            ? new Thickness(0)
            : new Thickness(0, 3, 0, 0);
    }

    private void ApplyModeVisuals(AssistantPetMode mode)
    {
        // Props            : exactly one state prop is active; task truth is never changed here.
        Laptop.Visibility = mode == AssistantPetMode.Working
            ? Visibility.Visible
            : Visibility.Collapsed;
        BathTub.Visibility = mode == AssistantPetMode.Resting
            ? Visibility.Visible
            : Visibility.Collapsed;
        SleepZzz.Visibility = mode == AssistantPetMode.Offline
            ? Visibility.Visible
            : Visibility.Collapsed;
        WaitBubble.Visibility = mode is AssistantPetMode.Waiting or AssistantPetMode.Error
            ? Visibility.Visible
            : Visibility.Collapsed;
        WaitBubble.Text = mode == AssistantPetMode.Error ? "!" : "?";

        // Base pose        : reset prior frame pose before applying the new state.
        SetEyesClosed(mode == AssistantPetMode.Offline);
        Tongue.Visibility = mode == AssistantPetMode.Offline
            ? Visibility.Collapsed
            : Visibility.Visible;
        HeadRotate.Angle = mode switch
        {
            AssistantPetMode.Waiting => -4,
            AssistantPetMode.Offline => 4,
            AssistantPetMode.Error   => -3,
            _                        => 0,
        };
        HeadTranslate.X       = 0;
        HeadTranslate.Y       = mode == AssistantPetMode.Offline ? 4 : 0;
        _leftEarRotate.Angle  = mode == AssistantPetMode.Error ? -8 : 0;
        _rightEarRotate.Angle = mode == AssistantPetMode.Error ? 8 : 0;
        _leftPawRotate.Angle  = 0;
        _rightPawRotate.Angle = 0;
        TailRotate.Angle      = mode == AssistantPetMode.Offline ? -38 : -28;
        BathDuckRotate.Angle  = 0;
        BathBubbleOne.Opacity = 0.92;
        BathBubbleTwo.Opacity = 0.90;
        EmotionGlyph.Opacity  = 0;

        _lastEmotion = null;
        ApplyEmotion(ModeEmotion(mode));

        // State cards      : small strip mirrors the large pet state and uses the same status semantics.
        ApplyStateCard(
            RestingCard,
            mode == AssistantPetMode.Resting,
            "#2A19C37D",
            "#FF19C37D");
        ApplyStateCard(
            WorkingCard,
            mode == AssistantPetMode.Working,
            "#2A2F8CFF",
            "#FF4F9DFF");
        ApplyStateCard(
            OfflineCard,
            mode == AssistantPetMode.Offline,
            "#2A718096",
            "#FF8A9AAD");
    }

    private static void ApplyStateCard(
        System.Windows.Controls.Border card,
        bool active,
        string activeBackground,
        string activeBorder)
    {
        card.Background      = BrushFrom(active ? activeBackground : "#1018273B");
        card.BorderBrush     = BrushFrom(active ? activeBorder : "#334C6078");
        card.BorderThickness = new Thickness(active ? 1.6 : 1.0);
    }

    private void ConfigureFrameTimer(AssistantPetMode mode)
    {
        _frameTimer.Stop();
        _frameTimer.Interval = mode switch
        {
            AssistantPetMode.Working => TimeSpan.FromMilliseconds(310),
            AssistantPetMode.Offline => TimeSpan.FromMilliseconds(950),
            AssistantPetMode.Error   => TimeSpan.FromMilliseconds(440),
            AssistantPetMode.Waiting => TimeSpan.FromMilliseconds(620),
            _                        => TimeSpan.FromMilliseconds(560),
        };

        if (_isLoaded && IsVisible)
        {
            _frameTimer.Start();
        }
    }

    private void FrameTimer_Tick(object? sender, EventArgs e)
    {
        _frameIndex++;
        switch (_activeMode)
        {
            case AssistantPetMode.Working:
                AdvanceWorkingPose();
                break;
            case AssistantPetMode.Resting:
                AdvanceRestingPose();
                break;
            case AssistantPetMode.Waiting:
                AdvanceWaitingPose();
                break;
            case AssistantPetMode.Offline:
                AdvanceSleepingPose();
                break;
            case AssistantPetMode.Error:
                AdvanceErrorPose();
                break;
        }

        var behaviorFrame = _behaviorController.Next(
            _activeMode,
            allowMicroAction: !_pointerInside && !_pointerCaptured && !_isDragging);
        ApplyBehaviorFrame(behaviorFrame);
    }

    private void AdvanceWorkingPose()
    {
        var alternate = _frameIndex % 2 == 0;
        _leftPawRotate.Angle  = alternate ? -7 : 3;
        _rightPawRotate.Angle = alternate ? 5 : -6;
        TailRotate.Angle      = alternate ? -20 : -37;

        if (!_pointerInside && !_pointerCaptured)
        {
            HeadRotate.Angle = _frameIndex % 6 == 0
                ? -3.2
                : alternate ? -1.4 : 1.2;
            HeadTranslate.Y = _frameIndex % 6 == 0 ? 1.2 : 0;
        }
        if (_frameIndex % 7 == 0)
        {
            Blink();
        }
    }

    private void AdvanceRestingPose()
    {
        var phase = _frameIndex % 4;
        TailRotate.Angle = phase switch
        {
            0 => -17,
            1 => -29,
            2 => -41,
            _ => -27,
        };
        _leftEarRotate.Angle  = phase == 1 ? -5 : 0;
        _rightEarRotate.Angle = phase == 3 ? 5 : 0;
        BathDuckRotate.Angle  = phase is 0 or 3 ? -6 : 6;
        BathBubbleOne.Opacity = phase is 0 or 2 ? 0.98 : 0.58;
        BathBubbleTwo.Opacity = phase is 1 or 3 ? 0.95 : 0.50;

        if (!_pointerInside && !_pointerCaptured)
        {
            HeadRotate.Angle = phase is 0 or 3 ? -1.5 : 1.2;
        }
        if (_frameIndex % 6 == 0)
        {
            Blink();
        }
    }

    private void AdvanceWaitingPose()
    {
        var alternate = _frameIndex % 2 == 0;
        if (!_pointerInside && !_pointerCaptured)
        {
            HeadRotate.Angle = alternate ? -6 : 5;
        }
        _leftEarRotate.Angle  = alternate ? -4 : 1;
        _rightEarRotate.Angle = alternate ? 1 : 4;
        WaitBubble.Opacity    = alternate ? 1.0 : 0.62;
        TailRotate.Angle      = alternate ? -23 : -34;

        if (_frameIndex % 5 == 0)
        {
            Blink();
        }
    }

    private void AdvanceSleepingPose()
    {
        SetEyesClosed(true);
        var alternate = _frameIndex % 2 == 0;
        HeadTranslate.Y  = alternate ? 3.0 : 5.0;
        PetScale.ScaleY  = alternate ? 1.0 : 1.012;
        SleepZzz.Opacity = alternate ? 0.58 : 1.0;
        System.Windows.Controls.Canvas.SetTop(SleepZzz, alternate ? 35 : 31);
    }

    private void AdvanceErrorPose()
    {
        var alternate = _frameIndex % 2 == 0;
        _leftEarRotate.Angle  = alternate ? -11 : -6;
        _rightEarRotate.Angle = alternate ? 11 : 6;
        WaitBubble.Opacity    = alternate ? 1.0 : 0.55;
        if (!_pointerCaptured)
        {
            PetTranslate.X = alternate ? -2.5 : 2.5;
        }
        if (_frameIndex % 4 == 0)
        {
            Blink();
        }
    }

    private void ApplyBehaviorFrame(PetBehaviorFrame frame)
    {
        if (_lastEmotion != frame.Emotion)
        {
            ApplyEmotion(frame.Emotion);
        }

        if (frame.Action == PetMicroAction.None)
        {
            return;
        }

        if (!string.IsNullOrWhiteSpace(frame.ReactionGlyph))
        {
            ShowEmotionGlyph(frame.ReactionGlyph!, 760);
        }

        switch (frame.Action)
        {
            case PetMicroAction.LookAround:
                AnimateHeadLook(frame.HeadTilt);
                break;
            case PetMicroAction.Stretch:
                AnimateStretch();
                break;
            case PetMicroAction.Yawn:
                AnimateYawn();
                break;
            case PetMicroAction.LickNose:
                AnimateLickNose();
                break;
            case PetMicroAction.CuriousTilt:
                AnimateCuriousTilt(frame.HeadTilt, frame.EarTilt);
                break;
            case PetMicroAction.HappyBounce:
                AnimateCelebration();
                break;
            case PetMicroAction.FocusGlance:
                AnimateFocusGlance();
                break;
        }
    }

    private void ApplyEmotion(PetEmotion emotion)
    {
        _lastEmotion = emotion;
        LeftBrow.Opacity  = 0.72;
        RightBrow.Opacity = 0.72;
        LeftBlush.Opacity = emotion == PetEmotion.Happy ? 0.68 : 0;
        RightBlush.Opacity = emotion == PetEmotion.Happy ? 0.68 : 0;

        var (leftBrow, rightBrow, mouth) = emotion switch
        {
            PetEmotion.Focused => (
                "M 29,39 Q 37,36 45,42",
                "M 60,42 Q 68,36 76,39",
                "M 49,73 Q 54,75 60,73"),
            PetEmotion.Happy => (
                "M 29,40 Q 37,35 45,39",
                "M 60,39 Q 68,35 76,40",
                "M 47,71 Q 54,81 62,71"),
            PetEmotion.Curious => (
                "M 29,38 Q 37,33 45,37",
                "M 60,41 Q 68,37 76,40",
                "M 49,72 Q 54,77 60,72"),
            PetEmotion.Sleepy => (
                "M 29,42 Q 37,40 45,42",
                "M 60,42 Q 68,40 76,42",
                "M 49,72 Q 54,78 60,72"),
            PetEmotion.Concerned => (
                "M 29,38 Q 37,43 45,41",
                "M 60,41 Q 68,43 76,38",
                "M 49,77 Q 54,72 60,77"),
            _ => (
                "M 29,41 Q 37,36 45,40",
                "M 60,40 Q 68,36 76,41",
                "M 48,72 Q 54,79 61,72"),
        };
        LeftBrow.Data  = Geometry.Parse(leftBrow);
        RightBrow.Data = Geometry.Parse(rightBrow);
        Mouth.Data     = Geometry.Parse(mouth);

        if (_activeMode == AssistantPetMode.Offline)
        {
            SetEyesClosed(true);
            Tongue.Visibility = Visibility.Collapsed;
            return;
        }

        var eyeScale = emotion switch
        {
            PetEmotion.Sleepy    => 0.60,
            PetEmotion.Concerned => 0.82,
            _                    => 1.0,
        };
        SetEyeScale(eyeScale);
        Tongue.Visibility = emotion is PetEmotion.Happy or PetEmotion.Sleepy
            ? Visibility.Visible
            : Visibility.Collapsed;
    }

    private static PetEmotion ModeEmotion(AssistantPetMode mode) => mode switch
    {
        AssistantPetMode.Working => PetEmotion.Focused,
        AssistantPetMode.Waiting => PetEmotion.Curious,
        AssistantPetMode.Offline => PetEmotion.Sleepy,
        AssistantPetMode.Error   => PetEmotion.Concerned,
        _                        => PetEmotion.Calm,
    };

    private void AnimateHeadLook(double targetAngle)
    {
        HeadRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(HeadRotate.Angle, targetAngle, TimeSpan.FromMilliseconds(310))
            {
                AutoReverse    = true,
                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseInOut },
            });
    }

    private void AnimateStretch()
    {
        PetScale.BeginAnimation(
            ScaleTransform.ScaleXProperty,
            new DoubleAnimation(1.0, 1.055, TimeSpan.FromMilliseconds(330))
            {
                AutoReverse    = true,
                EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
            });
        _leftPawRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(_leftPawRotate.Angle, -18, TimeSpan.FromMilliseconds(330))
            {
                AutoReverse = true,
            });
        _rightPawRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(_rightPawRotate.Angle, 18, TimeSpan.FromMilliseconds(330))
            {
                AutoReverse = true,
            });
    }

    private void AnimateYawn()
    {
        var squint = new DoubleAnimation(1.0, 0.34, TimeSpan.FromMilliseconds(260))
        {
            AutoReverse    = true,
            EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
        };
        _leftEyeScale.BeginAnimation(ScaleTransform.ScaleYProperty, squint);
        _rightEyeScale.BeginAnimation(ScaleTransform.ScaleYProperty, squint.Clone());
        Tongue.Visibility = Visibility.Visible;
        Tongue.BeginAnimation(
            HeightProperty,
            new DoubleAnimation(Tongue.Height, 11, TimeSpan.FromMilliseconds(310))
            {
                AutoReverse = true,
            });
        Mouth.BeginAnimation(
            System.Windows.Shapes.Shape.StrokeThicknessProperty,
            new DoubleAnimation(Mouth.StrokeThickness, 3.2, TimeSpan.FromMilliseconds(310))
            {
                AutoReverse = true,
            });
    }

    private void AnimateLickNose()
    {
        Tongue.Visibility = Visibility.Visible;
        var lick = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(430),
        };
        lick.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        lick.KeyFrames.Add(new SplineDoubleKeyFrame(-8, KeyTime.FromPercent(0.38)));
        lick.KeyFrames.Add(new SplineDoubleKeyFrame(-3, KeyTime.FromPercent(0.62)));
        lick.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        _tongueTranslate.BeginAnimation(TranslateTransform.YProperty, lick);
    }

    private void AnimateCuriousTilt(double targetAngle, double earTilt)
    {
        HeadRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(HeadRotate.Angle, targetAngle, TimeSpan.FromMilliseconds(350))
            {
                AutoReverse    = true,
                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseInOut },
            });
        _leftEarRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(_leftEarRotate.Angle, -earTilt, TimeSpan.FromMilliseconds(300))
            {
                AutoReverse = true,
            });
        _rightEarRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(_rightEarRotate.Angle, earTilt, TimeSpan.FromMilliseconds(300))
            {
                AutoReverse = true,
            });
    }

    private void AnimateFocusGlance()
    {
        var duration = TimeSpan.FromMilliseconds(360);
        LeftPupil.BeginAnimation(
            System.Windows.Controls.Canvas.LeftProperty,
            new DoubleAnimation(36, 34.2, duration) { AutoReverse = true });
        RightPupil.BeginAnimation(
            System.Windows.Controls.Canvas.LeftProperty,
            new DoubleAnimation(64, 62.2, duration) { AutoReverse = true });
        LeftPupil.BeginAnimation(
            System.Windows.Controls.Canvas.TopProperty,
            new DoubleAnimation(48, 50.2, duration) { AutoReverse = true });
        RightPupil.BeginAnimation(
            System.Windows.Controls.Canvas.TopProperty,
            new DoubleAnimation(48, 50.2, duration) { AutoReverse = true });
    }

    private void ShowEmotionGlyph(string glyph, int durationMilliseconds)
    {
        EmotionGlyph.Text = glyph;
        var animation = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(durationMilliseconds),
        };
        animation.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        animation.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.18)));
        animation.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.58)));
        animation.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        EmotionGlyph.BeginAnimation(OpacityProperty, animation);
    }

    private void Blink()
    {
        if (_activeMode == AssistantPetMode.Offline)
        {
            return;
        }

        var openScale = _lastEmotion switch
        {
            PetEmotion.Sleepy    => 0.60,
            PetEmotion.Concerned => 0.82,
            _                    => 1.0,
        };
        var animation = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(170),
        };
        animation.KeyFrames.Add(new LinearDoubleKeyFrame(openScale, KeyTime.FromPercent(0.00)));
        animation.KeyFrames.Add(new LinearDoubleKeyFrame(0.10, KeyTime.FromPercent(0.45)));
        animation.KeyFrames.Add(new LinearDoubleKeyFrame(openScale, KeyTime.FromPercent(1.00)));
        _leftEyeScale.BeginAnimation(ScaleTransform.ScaleYProperty, animation);
        _rightEyeScale.BeginAnimation(ScaleTransform.ScaleYProperty, animation.Clone());
        _leftPupilScale.BeginAnimation(ScaleTransform.ScaleYProperty, animation.Clone());
        _rightPupilScale.BeginAnimation(ScaleTransform.ScaleYProperty, animation.Clone());
    }

    private void SetEyesClosed(bool closed)
    {
        SetEyeScale(closed ? 0.10 : 1.0);
    }

    private void SetEyeScale(double scale)
    {
        _leftEyeScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
        _rightEyeScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
        _leftPupilScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
        _rightPupilScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
        _leftEyeScale.ScaleY    = scale;
        _rightEyeScale.ScaleY   = scale;
        _leftPupilScale.ScaleY  = scale;
        _rightPupilScale.ScaleY = scale;
    }

    private void StartBreathing(AssistantPetMode mode)
    {
        PetScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
        if (!_isLoaded || !IsVisible)
        {
            return;
        }

        var amplitude = mode switch
        {
            AssistantPetMode.Working => 1.010,
            AssistantPetMode.Offline => 1.020,
            AssistantPetMode.Error   => 1.006,
            _                        => 1.016,
        };
        var duration = mode switch
        {
            AssistantPetMode.Working => 1.10,
            AssistantPetMode.Offline => 2.05,
            AssistantPetMode.Error   => 0.80,
            _                        => 1.45,
        };

        var breathing = new DoubleAnimation
        {
            From           = 1.0,
            To             = amplitude,
            Duration       = TimeSpan.FromSeconds(duration),
            AutoReverse    = true,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
        };
        PetScale.BeginAnimation(ScaleTransform.ScaleYProperty, breathing);
    }

    private void AnimateStateTransition(AssistantPetMode mode)
    {
        var fade = new DoubleAnimation
        {
            From           = 0.45,
            To             = 1.0,
            Duration       = TimeSpan.FromMilliseconds(240),
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut },
        };
        PetMotionLayer.BeginAnimation(OpacityProperty, fade);

        if (mode == AssistantPetMode.Error)
        {
            AnimateErrorShake();
        }
    }

    private void AnimateErrorShake()
    {
        var shake = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(420),
        };
        shake.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        shake.KeyFrames.Add(new LinearDoubleKeyFrame(-5, KeyTime.FromPercent(0.18)));
        shake.KeyFrames.Add(new LinearDoubleKeyFrame(5, KeyTime.FromPercent(0.36)));
        shake.KeyFrames.Add(new LinearDoubleKeyFrame(-3, KeyTime.FromPercent(0.56)));
        shake.KeyFrames.Add(new LinearDoubleKeyFrame(3, KeyTime.FromPercent(0.76)));
        shake.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        PetTranslate.BeginAnimation(TranslateTransform.XProperty, shake);
    }

    private void PetSurface_MouseEnter(object sender, System.Windows.Input.MouseEventArgs e)
    {
        _pointerInside = true;
        if (!IsFloatingMode)
        {
            CardBorder.BorderBrush = BrushFrom("#FF2F9BFF");
        }
        Cursor = System.Windows.Input.Cursors.Hand;
        ApplyEmotion(PetEmotion.Curious);
    }

    private void PetSurface_MouseLeave(object sender, System.Windows.Input.MouseEventArgs e)
    {
        _pointerInside = false;
        if (_pointerCaptured)
        {
            return;
        }

        if (!IsFloatingMode)
        {
            CardBorder.BorderBrush = BrushFrom("#FF176AA9");
        }
        Cursor = System.Windows.Input.Cursors.Arrow;
        ResetPointerPose(animated: true);
        ApplyEmotion(ModeEmotion(_activeMode));
    }

    private void PetSurface_MouseMove(object sender, System.Windows.Input.MouseEventArgs e)
    {
        var position = e.GetPosition(PetStage);
        if (PetStage.ActualWidth <= 0 || PetStage.ActualHeight <= 0)
        {
            return;
        }

        if (_pointerCaptured && e.LeftButton == System.Windows.Input.MouseButtonState.Pressed)
        {
            var delta = position - _pointerDown;
            if (!_isDragging && Math.Abs(delta.X) + Math.Abs(delta.Y) >= 5)
            {
                _isDragging = true;
                ReactionText.Text = "别把我拎太远～";
                ShowReaction(650);
            }

            if (_isDragging)
            {
                PetTranslate.X  = Math.Clamp(delta.X, -19, 19);
                PetTranslate.Y  = Math.Clamp(delta.Y, -12, 9);
                PetRotate.Angle = Math.Clamp(delta.X * 0.35, -7, 7);
                return;
            }
        }

        // Pointer follow    : only eyes/head track the pointer; the body remains anchored like a pet.
        var normalizedX = Math.Clamp((position.X / PetStage.ActualWidth * 2) - 1, -1, 1);
        var normalizedY = Math.Clamp((position.Y / PetStage.ActualHeight * 2) - 1, -1, 1);
        HeadRotate.Angle = normalizedX * 4.5;
        HeadTranslate.X  = normalizedX * 1.6;
        HeadTranslate.Y  = normalizedY * 1.1;
        System.Windows.Controls.Canvas.SetLeft(LeftPupil, 36 + (normalizedX * 1.8));
        System.Windows.Controls.Canvas.SetTop(LeftPupil, 48 + (normalizedY * 1.1));
        System.Windows.Controls.Canvas.SetLeft(RightPupil, 64 + (normalizedX * 1.8));
        System.Windows.Controls.Canvas.SetTop(RightPupil, 48 + (normalizedY * 1.1));
    }

    private void PetSurface_MouseLeftButtonDown(
        object sender,
        System.Windows.Input.MouseButtonEventArgs e)
    {
        Focus();
        _pointerDown     = e.GetPosition(PetStage);
        _pointerCaptured = CaptureMouse();
        _isDragging      = false;
        e.Handled        = true;
    }

    private void PetSurface_MouseLeftButtonUp(
        object sender,
        System.Windows.Input.MouseButtonEventArgs e)
    {
        var releasePosition = e.GetPosition(PetStage);
        var wasDragging     = _isDragging;
        ReleasePointerCapture();

        if (wasDragging)
        {
            ResetPointerPose(animated: true);
            e.Handled = true;
            return;
        }

        AnimateFriendlyReaction(releasePosition);
        e.Handled = true;
    }

    private void PetSurface_MouseDoubleClick(
        object sender,
        System.Windows.Input.MouseButtonEventArgs e)
    {
        ApplyEmotion(PetEmotion.Happy);
        ReactionText.Text = "好耶！✨";
        ShowReaction(980);
        AnimateCelebration();
        e.Handled = true;
    }

    private void PetSurface_KeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key is System.Windows.Input.Key.Space or System.Windows.Input.Key.Enter)
        {
            AnimateFriendlyReaction(
                new System.Windows.Point(PetStage.ActualWidth / 2, PetStage.ActualHeight / 2));
            e.Handled = true;
        }
    }

    private void FloatButton_Click(object sender, RoutedEventArgs e)
    {
        FloatRequested?.Invoke(this, EventArgs.Empty);
        e.Handled = true;
    }

    private void AnimateFriendlyReaction(System.Windows.Point position)
    {
        var upperHalf = position.Y <= Math.Max(1, PetStage.ActualHeight) * 0.58;
        ApplyEmotion(PetEmotion.Happy);
        ReactionText.Text = upperHalf ? "摸摸头～ ✨" : "击掌！🐾";
        ShowReaction(820);

        if (upperHalf)
        {
            AnimateHeadPat();
        }
        else
        {
            AnimatePawWave();
        }
    }

    private void AnimateHeadPat()
    {
        var nod = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(430),
        };
        nod.KeyFrames.Add(new SplineDoubleKeyFrame(HeadRotate.Angle, KeyTime.FromPercent(0.00)));
        nod.KeyFrames.Add(new SplineDoubleKeyFrame(-7, KeyTime.FromPercent(0.32)));
        nod.KeyFrames.Add(new SplineDoubleKeyFrame(5, KeyTime.FromPercent(0.62)));
        nod.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        HeadRotate.BeginAnimation(RotateTransform.AngleProperty, nod);

        _leftEarRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(-8, 3, TimeSpan.FromMilliseconds(280))
            {
                AutoReverse = true,
            });
        _rightEarRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(8, -3, TimeSpan.FromMilliseconds(280))
            {
                AutoReverse = true,
            });
    }

    private void AnimatePawWave()
    {
        var wave = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(560),
        };
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(-28, KeyTime.FromPercent(0.28)));
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(16, KeyTime.FromPercent(0.52)));
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(-18, KeyTime.FromPercent(0.72)));
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        _rightPawRotate.BeginAnimation(RotateTransform.AngleProperty, wave);
    }

    private void AnimateCelebration()
    {
        var jump = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(620),
        };
        jump.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        jump.KeyFrames.Add(new SplineDoubleKeyFrame(-12, KeyTime.FromPercent(0.38)));
        jump.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        PetTranslate.BeginAnimation(TranslateTransform.YProperty, jump);

        TailRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(-48, -12, TimeSpan.FromMilliseconds(150))
            {
                AutoReverse    = true,
                RepeatBehavior = new RepeatBehavior(2.0),
            });
        AnimatePawWave();
    }

    private void ShowReaction(int durationMilliseconds)
    {
        var reaction = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(durationMilliseconds),
        };
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.14)));
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.62)));
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        ReactionText.BeginAnimation(OpacityProperty, reaction);
    }

    private void ReleasePointerCapture()
    {
        if (_pointerCaptured)
        {
            ReleaseMouseCapture();
        }
        _pointerCaptured = false;
        _isDragging      = false;
    }

    private void ResetPointerPose(bool animated)
    {
        PetRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        HeadRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        HeadTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        HeadTranslate.BeginAnimation(TranslateTransform.YProperty, null);

        System.Windows.Controls.Canvas.SetLeft(LeftPupil, 36);
        System.Windows.Controls.Canvas.SetTop(LeftPupil, 48);
        System.Windows.Controls.Canvas.SetLeft(RightPupil, 64);
        System.Windows.Controls.Canvas.SetTop(RightPupil, 48);

        if (!animated)
        {
            PetRotate.Angle  = 0;
            PetTranslate.X   = 0;
            PetTranslate.Y   = 0;
            HeadRotate.Angle = 0;
            HeadTranslate.X  = 0;
            HeadTranslate.Y  = 0;
            return;
        }

        var duration = TimeSpan.FromMilliseconds(180);
        PetRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            EaseTo(PetRotate.Angle, 0, duration));
        PetTranslate.BeginAnimation(
            TranslateTransform.XProperty,
            EaseTo(PetTranslate.X, 0, duration));
        PetTranslate.BeginAnimation(
            TranslateTransform.YProperty,
            EaseTo(PetTranslate.Y, 0, duration));
        HeadRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            EaseTo(HeadRotate.Angle, 0, duration));
        HeadTranslate.BeginAnimation(
            TranslateTransform.XProperty,
            EaseTo(HeadTranslate.X, 0, duration));
        HeadTranslate.BeginAnimation(
            TranslateTransform.YProperty,
            EaseTo(HeadTranslate.Y, 0, duration));
    }

    private static DoubleAnimation EaseTo(double from, double to, TimeSpan duration) => new(from, to, duration)
    {
        EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut },
    };

    private void PetSurface_IsVisibleChanged(
        object sender,
        DependencyPropertyChangedEventArgs e)
    {
        if (!_isLoaded)
        {
            return;
        }

        if (e.NewValue is true)
        {
            StartBreathing(_activeMode);
            ConfigureFrameTimer(_activeMode);
            return;
        }

        SuspendContinuousMotion();
    }

    private void SuspendContinuousMotion()
    {
        _frameTimer.Stop();
        PetScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
        PetScale.BeginAnimation(ScaleTransform.ScaleXProperty, null);
        PetMotionLayer.BeginAnimation(OpacityProperty, null);
        EmotionGlyph.BeginAnimation(OpacityProperty, null);
    }

    private void PetSurface_Unloaded(object sender, RoutedEventArgs e)
    {
        _isLoaded = false;
        SuspendContinuousMotion();
        ReleasePointerCapture();
        PetRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        HeadRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        ReactionText.BeginAnimation(OpacityProperty, null);
        _tongueTranslate.BeginAnimation(TranslateTransform.YProperty, null);
    }

    private static SolidColorBrush BrushFrom(string hex)
    {
        var brush = (SolidColorBrush)new BrushConverter().ConvertFromString(hex)!;
        brush.Freeze();
        return brush;
    }
}
