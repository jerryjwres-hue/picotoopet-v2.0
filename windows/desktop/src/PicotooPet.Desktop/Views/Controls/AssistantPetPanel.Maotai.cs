using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>Q版阿拉斯加“茅台”的独立光栅表现层；业务状态仍由主 partial 的 Presentation 决定。</summary>
public partial class AssistantPetPanel
{
    private readonly PetBehaviorSequenceController _maotaiSequenceController = new();
    private readonly DispatcherTimer _maotaiTimer = new(DispatcherPriority.Background)
    {
        Interval = TimeSpan.FromMilliseconds(220),
    };

    private ImageSource? _maotaiWorking;
    private ImageSource? _maotaiWorkingTired;
    private ImageSource? _maotaiWorkingAnnoyed;
    private ImageSource? _maotaiResting;
    private ImageSource? _maotaiOffline;
    private AssistantPetMode? _maotaiRenderedMode;
    private int _maotaiFrame;
    private int _maotaiMoodFramesRemaining;
    private MaotaiWorkMood _maotaiMood = MaotaiWorkMood.Focused;

    /// <summary>在 XAML 初始化完成时并行挂接 Q 版表现层；不会替换既有业务/交互事件。</summary>
    protected override void OnInitialized(EventArgs e)
    {
        base.OnInitialized(e);

        _maotaiTimer.Tick += MaotaiTimer_Tick;
        Loaded             += MaotaiPet_Loaded;
        Unloaded           += MaotaiPet_Unloaded;
        IsVisibleChanged   += MaotaiPet_IsVisibleChanged;
        MouseMove          += MaotaiPet_MouseMove;
        MouseLeave         += MaotaiPet_MouseLeave;
        MouseLeftButtonUp  += MaotaiPet_MouseLeftButtonUp;
        MouseDoubleClick   += MaotaiPet_MouseDoubleClick;
    }

    private void MaotaiPet_Loaded(object sender, RoutedEventArgs e)
    {
        EnsureMaotaiSources();
        ApplyMaotaiMode(force: true);
        StartMaotaiTimer();
    }

    private void MaotaiPet_Unloaded(object sender, RoutedEventArgs e)
    {
        StopMaotaiTimer();
        ClearMaotaiAnimations();
    }

    private void MaotaiPet_IsVisibleChanged(
        object sender,
        DependencyPropertyChangedEventArgs e)
    {
        if (e.NewValue is true)
        {
            ApplyMaotaiMode(force: true);
            StartMaotaiTimer();
            return;
        }

        StopMaotaiTimer();
        ClearMaotaiAnimations();
    }

    private void StartMaotaiTimer()
    {
        if (!IsLoaded || !IsVisible)
        {
            return;
        }

        _maotaiTimer.Stop();
        _maotaiTimer.Interval = _activeMode switch
        {
            AssistantPetMode.Working => TimeSpan.FromMilliseconds(210),
            AssistantPetMode.Waiting => TimeSpan.FromMilliseconds(360),
            AssistantPetMode.Error   => TimeSpan.FromMilliseconds(300),
            AssistantPetMode.Offline => TimeSpan.FromMilliseconds(900),
            _                        => TimeSpan.FromMilliseconds(620),
        };
        _maotaiTimer.Start();
    }

    private void StopMaotaiTimer() => _maotaiTimer.Stop();

    private void MaotaiTimer_Tick(object? sender, EventArgs e)
    {
        if (!IsVisible)
        {
            StopMaotaiTimer();
            return;
        }

        if (_maotaiRenderedMode != _activeMode)
        {
            ApplyMaotaiMode(force: true);
            StartMaotaiTimer();
        }

        _maotaiFrame++;
        switch (_activeMode)
        {
            case AssistantPetMode.Working:
                AdvanceMaotaiWorking();
                break;
            case AssistantPetMode.Waiting:
                AdvanceMaotaiWaiting();
                break;
            case AssistantPetMode.Error:
                AdvanceMaotaiError();
                break;
            case AssistantPetMode.Resting:
                AdvanceMaotaiResting();
                break;
            case AssistantPetMode.Offline:
                AdvanceMaotaiOffline();
                break;
        }
    }

    private void EnsureMaotaiSources()
    {
        _maotaiWorking ??= MaotaiPetAssetLoader.LoadOrFallback(
            MaotaiPetRig.WorkingFile,
            MaotaiPetRig.WorkingFallback);
        _maotaiWorkingTired ??= MaotaiPetAssetLoader.LoadOrFallback(
            MaotaiPetRig.WorkingTiredFile,
            MaotaiPetRig.WorkingFallback);
        _maotaiWorkingAnnoyed ??= MaotaiPetAssetLoader.LoadOrFallback(
            MaotaiPetRig.WorkingAnnoyedFile,
            MaotaiPetRig.WorkingFallback);
        _maotaiResting ??= MaotaiPetAssetLoader.LoadOrFallback(
            MaotaiPetRig.RestingFile,
            MaotaiPetRig.RestingFallback);
        _maotaiOffline ??= MaotaiPetAssetLoader.LoadOrFallback(
            MaotaiPetRig.OfflineFile,
            MaotaiPetRig.OfflineFallback);
    }

    private void ApplyMaotaiMode(bool force)
    {
        EnsureMaotaiSources();
        if (!force && _maotaiRenderedMode == _activeMode)
        {
            return;
        }

        _maotaiRenderedMode      = _activeMode;
        _maotaiFrame             = 0;
        _maotaiMoodFramesRemaining = 0;
        _maotaiMood              = MaotaiWorkMood.Focused;

        switch (_activeMode)
        {
            case AssistantPetMode.Working:
                ApplyMaotaiSource(_maotaiWorking!, articulate: true);
                break;
            case AssistantPetMode.Resting:
                ApplyMaotaiSource(_maotaiResting!, articulate: false);
                break;
            case AssistantPetMode.Offline:
                ApplyMaotaiSource(_maotaiOffline!, articulate: false);
                break;
            case AssistantPetMode.Waiting:
            case AssistantPetMode.Error:
                ApplyMaotaiSource(_maotaiWorking!, articulate: true);
                break;
        }

        ResetMaotaiPose(animated: false);
    }

    private void ApplyMaotaiSource(
        ImageSource source,
        bool articulate)
    {
        MaotaiBody.Source          = source;
        MaotaiHead.Source          = source;
        MaotaiTail.Source          = source;
        MaotaiLeftPawImage.Source  = source;
        MaotaiRightPawImage.Source = source;

        var overlayOpacity            = articulate ? 1.0 : 0.0;
        MaotaiHead.Opacity            = overlayOpacity;
        MaotaiTail.Opacity            = overlayOpacity;
        MaotaiLeftPawImage.Opacity    = overlayOpacity;
        MaotaiRightPawImage.Opacity   = overlayOpacity;
    }

    private void AdvanceMaotaiWorking()
    {
        var alternate = _maotaiFrame % 2 == 0;
        MaotaiLeftPawTranslate.Y   = alternate ? -2.7 : 1.1;
        MaotaiRightPawTranslate.Y  = alternate ? 1.0 : -2.8;
        MaotaiLeftPawRotate.Angle  = alternate ? -3.8 : 2.0;
        MaotaiRightPawRotate.Angle = alternate ? 2.2 : -4.0;
        MaotaiTailRotate.Angle     = alternate ? -3.0 : 3.0;

        if (!_pointerInside && !_pointerCaptured)
        {
            MaotaiHeadRotate.Angle = _maotaiFrame % 10 == 0
                ? -2.4
                : alternate ? -0.7 : 0.8;
            MaotaiHeadTranslate.Y = _maotaiFrame % 10 == 0 ? 0.8 : 0;
        }

        if (_maotaiMoodFramesRemaining > 0)
        {
            _maotaiMoodFramesRemaining--;
            if (_maotaiMoodFramesRemaining == 0)
            {
                _maotaiMood = MaotaiWorkMood.Focused;
                ApplyMaotaiSource(_maotaiWorking!, articulate: true);
            }
            return;
        }

        if (_maotaiFrame % 18 != 0)
        {
            return;
        }

        var sequence = _maotaiSequenceController.NextSequence(
            AssistantPetMode.Working,
            PetEmotion.Focused);
        if (sequence.Name == "WorkingTired")
        {
            _maotaiMood                = MaotaiWorkMood.Tired;
            _maotaiMoodFramesRemaining = 5;
            ApplyMaotaiSource(_maotaiWorkingTired!, articulate: true);
            ReactionText.Text = "有点累了…";
            ShowReaction(900);
            return;
        }
        if (sequence.Name == "WorkingAnnoyed")
        {
            _maotaiMood                = MaotaiWorkMood.Annoyed;
            _maotaiMoodFramesRemaining = 4;
            ApplyMaotaiSource(_maotaiWorkingAnnoyed!, articulate: true);
            ReactionText.Text = "键盘要冒烟啦！";
            ShowReaction(850);
        }
    }

    private void AdvanceMaotaiWaiting()
    {
        var alternate = _maotaiFrame % 2 == 0;
        if (!_pointerInside && !_pointerCaptured)
        {
            MaotaiHeadRotate.Angle = alternate ? -4.5 : 4.0;
        }
        MaotaiTailRotate.Angle = alternate ? -2.5 : 2.5;
    }

    private void AdvanceMaotaiError()
    {
        var alternate = _maotaiFrame % 2 == 0;
        if (!_pointerCaptured)
        {
            MaotaiHeadTranslate.X = alternate ? -1.6 : 1.6;
        }
    }

    private void AdvanceMaotaiResting()
    {
        // Resting scene : the Q-version bath art stays intact; whole-stage breathing is owned by the base partial.
        MaotaiHeadRotate.Angle = 0;
    }

    private void AdvanceMaotaiOffline()
    {
        // Offline scene : the Q-version sleep art remains whole; the base partial supplies slow breathing cadence.
        MaotaiHeadRotate.Angle = 0;
    }

    private void MaotaiPet_MouseMove(object sender, MouseEventArgs e)
    {
        if (_activeMode is AssistantPetMode.Offline or AssistantPetMode.Error)
        {
            return;
        }
        if (PetStage.ActualWidth <= 0 || PetStage.ActualHeight <= 0 || _pointerCaptured)
        {
            return;
        }

        var position    = e.GetPosition(PetStage);
        var normalizedX = Math.Clamp((position.X / PetStage.ActualWidth * 2) - 1, -1, 1);
        var normalizedY = Math.Clamp((position.Y / PetStage.ActualHeight * 2) - 1, -1, 1);

        MaotaiHeadRotate.Angle  = normalizedX * 3.5;
        MaotaiHeadTranslate.X   = normalizedX * 1.2;
        MaotaiHeadTranslate.Y   = normalizedY * 0.8;
    }

    private void MaotaiPet_MouseLeave(object sender, MouseEventArgs e)
    {
        if (!_pointerCaptured)
        {
            ResetMaotaiPose(animated: true);
        }
    }

    private void MaotaiPet_MouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (_isDragging)
        {
            return;
        }

        var position  = e.GetPosition(PetStage);
        var upperHalf = position.Y <= Math.Max(1, PetStage.ActualHeight) * 0.58;
        if (upperHalf)
        {
            AnimateMaotaiHeadPat();
            return;
        }

        AnimateMaotaiPawWave();
    }

    private void MaotaiPet_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        MaotaiTailRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(-8, 8, TimeSpan.FromMilliseconds(120))
            {
                AutoReverse    = true,
                RepeatBehavior = new RepeatBehavior(3),
            });
    }

    private void AnimateMaotaiHeadPat()
    {
        var nod = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(460),
        };
        nod.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        nod.KeyFrames.Add(new SplineDoubleKeyFrame(-6, KeyTime.FromPercent(0.30)));
        nod.KeyFrames.Add(new SplineDoubleKeyFrame(4, KeyTime.FromPercent(0.62)));
        nod.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        MaotaiHeadRotate.BeginAnimation(RotateTransform.AngleProperty, nod);
    }

    private void AnimateMaotaiPawWave()
    {
        var wave = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(560),
        };
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(0.00)));
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(-20, KeyTime.FromPercent(0.27)));
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(12, KeyTime.FromPercent(0.52)));
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(-13, KeyTime.FromPercent(0.73)));
        wave.KeyFrames.Add(new SplineDoubleKeyFrame(0, KeyTime.FromPercent(1.00)));
        MaotaiRightPawRotate.BeginAnimation(RotateTransform.AngleProperty, wave);
    }

    private void ResetMaotaiPose(bool animated)
    {
        MaotaiHeadRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        MaotaiHeadTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        MaotaiHeadTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        MaotaiLeftPawRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        MaotaiRightPawRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        MaotaiLeftPawTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        MaotaiRightPawTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        MaotaiTailRotate.BeginAnimation(RotateTransform.AngleProperty, null);

        if (!animated)
        {
            MaotaiHeadRotate.Angle      = 0;
            MaotaiHeadTranslate.X       = 0;
            MaotaiHeadTranslate.Y       = 0;
            MaotaiLeftPawRotate.Angle   = 0;
            MaotaiRightPawRotate.Angle  = 0;
            MaotaiLeftPawTranslate.Y    = 0;
            MaotaiRightPawTranslate.Y   = 0;
            MaotaiTailRotate.Angle      = 0;
            return;
        }

        var duration = TimeSpan.FromMilliseconds(170);
        MaotaiHeadRotate.BeginAnimation(
            RotateTransform.AngleProperty,
            new DoubleAnimation(MaotaiHeadRotate.Angle, 0, duration));
        MaotaiHeadTranslate.BeginAnimation(
            TranslateTransform.XProperty,
            new DoubleAnimation(MaotaiHeadTranslate.X, 0, duration));
        MaotaiHeadTranslate.BeginAnimation(
            TranslateTransform.YProperty,
            new DoubleAnimation(MaotaiHeadTranslate.Y, 0, duration));
    }

    private void ClearMaotaiAnimations()
    {
        MaotaiHeadRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        MaotaiHeadTranslate.BeginAnimation(TranslateTransform.XProperty, null);
        MaotaiHeadTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        MaotaiLeftPawRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        MaotaiRightPawRotate.BeginAnimation(RotateTransform.AngleProperty, null);
        MaotaiLeftPawTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        MaotaiRightPawTranslate.BeginAnimation(TranslateTransform.YProperty, null);
        MaotaiTailRotate.BeginAnimation(RotateTransform.AngleProperty, null);
    }

    private enum MaotaiWorkMood
    {
        Focused,
        Tired,
        Annoyed,
    }
}
