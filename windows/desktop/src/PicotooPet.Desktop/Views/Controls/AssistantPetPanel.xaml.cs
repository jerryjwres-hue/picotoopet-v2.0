using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>原生 WPF 桌宠视图；只消费只读 Presentation，不持有 Session 或业务写入能力。</summary>
public partial class AssistantPetPanel : UserControl
{
    // Presentation : mirrors existing Core/Worker/task facts through a dependency property.
    public static readonly DependencyProperty PresentationProperty = DependencyProperty.Register(
        nameof(Presentation),
        typeof(AssistantPetPresentation),
        typeof(AssistantPetPanel),
        new FrameworkPropertyMetadata(null, OnPresentationChanged));

    private AssistantPetMode? _lastMode;
    private bool _isLoaded;

    public AssistantPetPanel()
    {
        InitializeComponent();
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
    }

    private void ApplyPresentation(AssistantPetPresentation? presentation)
    {
        if (presentation is null)
        {
            ModeTitleText.Text = "状态读取中";
            DetailText.Text = "正在读取系统状态…";
            IndicatorDot.Fill = BrushFrom("#FF8A9AAD");
            ShowFallbackPet();
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

        TrySetPetImage(presentation.AssetKey);

        if (_isLoaded)
        {
            if (_lastMode != presentation.Mode)
            {
                AnimateStateTransition(presentation.Mode);
            }
            StartBreathing(presentation.Mode);
        }

        _lastMode = presentation.Mode;
    }

    private void TrySetPetImage(string assetKey)
    {
        var safeKey = assetKey switch
        {
            "working" => "working",
            "resting" => "resting",
            "offline" => "offline",
            _          => "idle",
        };

        try
        {
            var uri = new Uri($"/Picotoo Pet AI;component/Assets/Pet/Husky/V1/{safeKey}.png", UriKind.Relative);
            PetImage.Source = new BitmapImage(uri);
            PetImage.Visibility = Visibility.Visible;
            FallbackPet.Visibility = Visibility.Collapsed;
        }
        catch (Exception)
        {
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
            AssistantPetMode.Offline => 1.028,
            AssistantPetMode.Error   => 1.008,
            _                        => 1.020,
        };
        var duration = mode switch
        {
            AssistantPetMode.Working => 1.15,
            AssistantPetMode.Offline => 2.15,
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
        CardBorder.BorderBrush = BrushFrom("#FF135D96");
        Cursor = Cursors.Arrow;

        PetRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        PetRotate.Angle = 0;
        PetTranslate.X = 0;
    }

    private void PetSurface_MouseMove(object sender, MouseEventArgs e)
    {
        var position = e.GetPosition(PetStage);
        if (PetStage.ActualWidth <= 0 || PetStage.ActualHeight <= 0)
        {
            return;
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
        AnimateFriendlyReaction();
        e.Handled = true;
    }

    private void PetSurface_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key is Key.Space or Key.Enter)
        {
            AnimateFriendlyReaction();
            e.Handled = true;
        }
    }

    private void AnimateFriendlyReaction()
    {
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

        var reaction = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(780),
        };
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.15)));
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.55)));
        reaction.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        ReactionText.BeginAnimation(OpacityProperty, reaction);
    }

    private void PetSurface_Unloaded(object sender, RoutedEventArgs e)
    {
        _isLoaded = false;
        PetScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
        PetRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        PetTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        ReactionText.BeginAnimation(OpacityProperty, null);
    }

    private static SolidColorBrush BrushFrom(string hex)
    {
        var brush = (SolidColorBrush)new BrushConverter().ConvertFromString(hex)!;
        brush.Freeze();
        return brush;
    }
}
