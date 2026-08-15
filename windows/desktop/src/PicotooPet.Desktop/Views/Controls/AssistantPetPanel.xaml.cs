using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>原生 WPF 桌宠视图；只消费只读 Presentation，不持有 Session 或业务写入能力。</summary>
public partial class AssistantPetPanel : System.Windows.Controls.UserControl
{
    // Presentation : mirrors existing Core/Worker/task facts through a dependency property.
    public static readonly DependencyProperty PresentationProperty = DependencyProperty.Register(
        nameof(Presentation),
        typeof(AssistantPetPresentation),
        typeof(AssistantPetPanel),
        new FrameworkPropertyMetadata(null, OnPresentationChanged));

    // Frame sets    : local compiled resources only; no network fetch and no provider dependency.
    private static readonly IReadOnlyDictionary<string, string[]> FrameSets =
        new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            ["idle"]    = new[] { "idle_0", "idle_1" },
            ["working"] = new[] { "working_0", "working_1", "working_2" },
            ["resting"] = new[] { "resting_0", "resting_1", "resting_2" },
            ["offline"] = new[] { "offline_0", "offline_1" },
        };

    private readonly DispatcherTimer _frameTimer;
    private AssistantPetMode? _lastMode;
    private string _activeAssetKey = "idle";
    private int _frameIndex;
    private bool _isLoaded;
    private bool _pointerCaptured;
    private bool _isDragging;
    private Point _pointerDown;

    public AssistantPetPanel()
    {
        InitializeComponent();
        _frameTimer = new DispatcherTimer(DispatcherPriority.Render)
        {
            Interval = TimeSpan.FromMilliseconds(760),
        };
        _frameTimer.Tick += FrameTimer_Tick;
        Loaded += PetSurface_Loaded;
    }

    /// <summary>当前桌宠只读展示；nullable 仅覆盖 XAML 初始化窗口。</summary>
    public AssistantPetPresentation? Presentation
    {
        get => (AssistantPetPresentation?)GetValue(PresentationProperty);
        set => SetValue(PresentationProperty, value);
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

    private void PetSurface_Loaded(object sender, RoutedEventArgs e)
    {
        _isLoaded = true;
        ApplyPresentation(Presentation);
        StartBreathing(Presentation?.Mode ?? AssistantPetMode.Resting);
        ConfigureFrameTimer(Presentation?.Mode ?? AssistantPetMode.Resting);
    }

    private void ApplyPresentation(AssistantPetPresentation? presentation)
    {
        if (presentation is null)
        {
            ModeTitleText.Text = "状态读取中";
            DetailText.Text = "正在读取系统状态…";
            IndicatorDot.Fill = BrushFrom("#FF8A9AAD");
            _activeAssetKey = "idle";
            _frameIndex = 0;
            TrySetPetFrame();
            return;
        }

        ModeTitleText.Text = presentation.Title;
        DetailText.Text = presentation.Detail;
        IndicatorDot.Fill = presentation.Indicator switch
        {
            AssistantPetIndicator.Green  => BrushFrom("#FF19C37D"),
            AssistantPetIndicator.Orange => BrushFrom("#FFFF8A00"),
            _                            => BrushFrom("#FF8A9AAD"),
        };

        _activeAssetKey = NormalizeAssetKey(presentation.AssetKey);
        _frameIndex = 0;
        TrySetPetFrame();

        if (_isLoaded)
        {
            if (_lastMode != presentation.Mode)
            {
                AnimateStateTransition(presentation.Mode);
            }
            StartBreathing(presentation.Mode);
            ConfigureFrameTimer(presentation.Mode);
        }

        _lastMode = presentation.Mode;
    }

    private static string NormalizeAssetKey(string assetKey) => assetKey switch
    {
        "working" => "working",
        "resting" => "resting",
        "offline" => "offline",
        _          => "idle",
    };

    private void ConfigureFrameTimer(AssistantPetMode mode)
    {
        _frameTimer.Stop();
        _frameTimer.Interval = mode switch
        {
            AssistantPetMode.Working => TimeSpan.FromMilliseconds(330),
            AssistantPetMode.Offline => TimeSpan.FromMilliseconds(1250),
            AssistantPetMode.Error   => TimeSpan.FromMilliseconds(560),
            AssistantPetMode.Waiting => TimeSpan.FromMilliseconds(820),
            _                        => TimeSpan.FromMilliseconds(720),
        };

        if (_isLoaded)
        {
            _frameTimer.Start();
        }
    }

    private void FrameTimer_Tick(object? sender, EventArgs e)
    {
        if (!FrameSets.TryGetValue(_activeAssetKey, out var frames) || frames.Length == 0)
        {
            return;
        }

        _frameIndex = (_frameIndex + 1) % frames.Length;
        TrySetPetFrame();
    }

    private void TrySetPetFrame()
    {
        if (!FrameSets.TryGetValue(_activeAssetKey, out var frames) || frames.Length == 0)
        {
            ShowFallbackPet();
            return;
        }

        var safeIndex = Math.Clamp(_frameIndex, 0, frames.Length - 1);
        var frameName = frames[safeIndex];

        try
        {
            var uri = new Uri(
                $"/Picotoo Pet AI;component/Assets/Pet/Husky/V1/{frameName}.png",
                UriKind.Relative);
            PetImage.Source = new BitmapImage(uri);
            PetImage.Visibility = Visibility.Visible;
            FallbackPet.Visibility = Visibility.Collapsed;
        }
        catch (Exception)
        {
            // Missing/corrupt decorative resources degrade to a safe glyph instead of crashing the app.
            ShowFallbackPet();
        }
    }

    private void ShowFallbackPet()
    {
        PetImage.Source = null;
        PetImage.Visibility = Visibility.Collapsed;
        FallbackPet.Visibility = Visibility.Visible;
    }

    private void StartBreathing(AssistantPetMode mode)
    {
        PetScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);

        var amplitude = mode switch
        {
            AssistantPetMode.Working => 1.012,
            AssistantPetMode.Offline => 1.026,
            AssistantPetMode.Error   => 1.008,
            _                        => 1.020,
        };
        var duration = mode switch
        {
            AssistantPetMode.Working => 1.15,
            AssistantPetMode.Offline => 2.10,
            AssistantPetMode.Error   => 0.85,
            _                        => 1.55,
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

    private void PetSurface_MouseEnter(object sender, MouseEventArgs e)
    {
        CardBorder.BorderBrush = BrushFrom("#FF2F9BFF");
        Cursor = Cursors.Hand;
    }

    private void PetSurface_MouseLeave(object sender, MouseEventArgs e)
    {
        if (_pointerCaptured)
        {
            return;
        }

        CardBorder.BorderBrush = BrushFrom("#FF135D96");
        Cursor = Cursors.Arrow;
        ResetPointerPose(animated: true);
    }

    private void PetSurface_MouseMove(object sender, MouseEventArgs e)
    {
        var position = e.GetPosition(PetStage);
        if (PetStage.ActualWidth <= 0 || PetStage.ActualHeight <= 0)
        {
            return;
        }

        if (_pointerCaptured && e.LeftButton == MouseButtonState.Pressed)
        {
            var delta = position - _pointerDown;
            if (!_isDragging && Math.Abs(delta.X) + Math.Abs(delta.Y) >= 5)
            {
                _isDragging = true;
                ReactionText.Text = "别把我拎太远～";
                ShowReactionBubble(620);
            }

            if (_isDragging)
            {
                PetTranslate.X = Math.Clamp(delta.X, -18, 18);
                PetTranslate.Y = Math.Clamp(delta.Y, -11, 9);
                PetRotate.Angle = Math.Clamp(delta.X * 0.35, -7, 7);
                return;
            }
        }

        var normalizedX = Math.Clamp((position.X / PetStage.ActualWidth * 2) - 1, -1, 1);
        var normalizedY = Math.Clamp((position.Y / PetStage.ActualHeight * 2) - 1, -1, 1);
        PetRotate.Angle = normalizedX * 4.0;
        PetTranslate.X = normalizedX * 3.0;
        PetTranslate.Y = normalizedY * 1.5;
    }

    private void PetSurface_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        Focus();
        _pointerDown = e.GetPosition(PetStage);
        _pointerCaptured = CaptureMouse();
        _isDragging = false;
        e.Handled = true;
    }

    private void PetSurface_MouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        var releasePosition = e.GetPosition(PetStage);
        var wasDragging = _isDragging;
        ReleasePointerCapture();

        if (wasDragging)
        {
            ResetPointerPose(animated: true);
            return;
        }

        AnimateFriendlyReaction(releasePosition);
        e.Handled = true;
    }

    private void PetSurface_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        ReactionText.Text = "好耶！✨";
        ShowReactionBubble(980);
        AnimateCelebration();
        e.Handled = true;
    }

    private void PetSurface_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key is Key.Space or Key.Enter)
        {
            AnimateFriendlyReaction(new Point(PetStage.ActualWidth / 2, PetStage.ActualHeight / 2));
            e.Handled = true;
        }
    }

    private void AnimateFriendlyReaction(Point position)
    {
        var upperHalf = position.Y <= Math.Max(1, PetStage.ActualHeight) * 0.58;
        ReactionText.Text = upperHalf ? "摸摸头～ ✨" : "击掌！🐾";
        ShowReactionBubble(820);

        var bounce = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(430),
        };
        bounce.KeyFrames.Add(new SplineDoubleKeyFrame(
            PetTranslate.Y,
            KeyTime.FromPercent(0.00)));
        bounce.KeyFrames.Add(new SplineDoubleKeyFrame(
            -9,
            KeyTime.FromPercent(0.35),
            new KeySpline(0.2, 0.8, 0.2, 1.0)));
        bounce.KeyFrames.Add(new SplineDoubleKeyFrame(
            0,
            KeyTime.FromPercent(1.00),
            new KeySpline(0.2, 0.8, 0.2, 1.0)));
        PetTranslate.BeginAnimation(TranslateTransform.YProperty, bounce);

        // An interaction also advances the sprite immediately, so the pet visibly changes pose.
        if (FrameSets.TryGetValue(_activeAssetKey, out var frames) && frames.Length > 1)
        {
            _frameIndex = (_frameIndex + 1) % frames.Length;
            TrySetPetFrame();
        }
    }

    private void AnimateCelebration()
    {
        var spin = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(620),
        };
        spin.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        spin.KeyFrames.Add(new SplineDoubleKeyFrame(-8, KeyTime.FromPercent(0.22)));
        spin.KeyFrames.Add(new SplineDoubleKeyFrame(9, KeyTime.FromPercent(0.48)));
        spin.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        PetRotate.BeginAnimation(RotateTransform.AngleProperty, spin);

        var jump = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(620),
        };
        jump.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        jump.KeyFrames.Add(new SplineDoubleKeyFrame(-12, KeyTime.FromPercent(0.38)));
        jump.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        PetTranslate.BeginAnimation(TranslateTransform.YProperty, jump);
    }

    private void ShowReactionBubble(int durationMilliseconds)
    {
        var reaction = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(durationMilliseconds),
        };
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.14)));
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.62)));
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        ReactionBubble.BeginAnimation(OpacityProperty, reaction);
    }

    private void ReleasePointerCapture()
    {
        if (_pointerCaptured)
        {
            ReleaseMouseCapture();
        }
        _pointerCaptured = false;
        _isDragging = false;
    }

    private void ResetPointerPose(bool animated)
    {
        PetRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.YProperty, null);

        if (!animated)
        {
            PetRotate.Angle = 0;
            PetTranslate.X = 0;
            PetTranslate.Y = 0;
            return;
        }

        var duration = TimeSpan.FromMilliseconds(180);
        PetRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(PetRotate.Angle, 0, duration)
            {
                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut },
            });
        PetTranslate.BeginAnimation(
            TranslateTransform.XProperty,
            new DoubleAnimation(PetTranslate.X, 0, duration)
            {
                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut },
            });
        PetTranslate.BeginAnimation(
            TranslateTransform.YProperty,
            new DoubleAnimation(PetTranslate.Y, 0, duration)
            {
                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut },
            });
    }

    private void PetSurface_Unloaded(object sender, RoutedEventArgs e)
    {
        _isLoaded = false;
        _frameTimer.Stop();
        ReleasePointerCapture();
        PetScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
        PetRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        ReactionBubble.BeginAnimation(OpacityProperty, null);
    }

    private static SolidColorBrush BrushFrom(string hex)
    {
        var brush = (SolidColorBrush)new BrushConverter().ConvertFromString(hex)!;
        brush.Freeze();
        return brush;
    }
}
