using System.Diagnostics;
using System.Windows;
using System.Windows.Media;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Controls.MaotaiMotion;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>Q版阿拉斯加“茅台”的连续时间表现层；真实状态仍只来自 PetPresentation。</summary>
public partial class AssistantPetPanel
{
    private const double MaotaiMaximumDeltaSeconds = 0.05;
    private const double MaotaiStageMinX           = 28.0;
    private const double MaotaiStageMaxX           = 120.0;
    private const double MaotaiRestingAnchorX      = 72.0;
    private const double MaotaiWorkingAnchorX      = 70.0;

    private static readonly string[] MaotaiRequiredRigAssets =
    [
        MaotaiAssetManifest.TorsoNeutral,
        MaotaiAssetManifest.TorsoCrouch,
        MaotaiAssetManifest.TorsoStretch,
        MaotaiAssetManifest.ChestFur,
        MaotaiAssetManifest.Head,
        MaotaiAssetManifest.EarLeft,
        MaotaiAssetManifest.EarRight,
        MaotaiAssetManifest.EyeLeftOpen,
        MaotaiAssetManifest.EyeRightOpen,
        MaotaiAssetManifest.EyeLeftHalf,
        MaotaiAssetManifest.EyeRightHalf,
        MaotaiAssetManifest.EyeLeftClosed,
        MaotaiAssetManifest.EyeRightClosed,
        MaotaiAssetManifest.PupilLeft,
        MaotaiAssetManifest.PupilRight,
        MaotaiAssetManifest.BrowLeft,
        MaotaiAssetManifest.BrowRight,
        MaotaiAssetManifest.Muzzle,
        MaotaiAssetManifest.MouthSmile,
        MaotaiAssetManifest.MouthTired,
        MaotaiAssetManifest.MouthAnnoyed,
        MaotaiAssetManifest.MouthYawn,
        MaotaiAssetManifest.MouthTongue,
        MaotaiAssetManifest.FrontLeftUpper,
        MaotaiAssetManifest.FrontLeftLower,
        MaotaiAssetManifest.FrontLeftPaw,
        MaotaiAssetManifest.FrontRightUpper,
        MaotaiAssetManifest.FrontRightLower,
        MaotaiAssetManifest.FrontRightPaw,
        MaotaiAssetManifest.HindLeftUpper,
        MaotaiAssetManifest.HindLeftLower,
        MaotaiAssetManifest.HindLeftPaw,
        MaotaiAssetManifest.HindRightUpper,
        MaotaiAssetManifest.HindRightLower,
        MaotaiAssetManifest.HindRightPaw,
        MaotaiAssetManifest.TailBase,
        MaotaiAssetManifest.TailMid,
        MaotaiAssetManifest.TailTip,
        MaotaiAssetManifest.HeadphoneBand,
        MaotaiAssetManifest.HeadphoneLeft,
        MaotaiAssetManifest.HeadphoneRight,
        MaotaiAssetManifest.Laptop,
        MaotaiAssetManifest.Drink,
        MaotaiAssetManifest.Shadow,
    ];

    private readonly Stopwatch _maotaiClock = new();

    private MaotaiMotionEngine? _maotaiMotionEngine;
    private MaotaiRasterRenderer? _maotaiRenderer;
    private bool _maotaiRigInitialized;
    private bool _maotaiRigReady;
    private bool _maotaiRenderingSubscribed;
    private double _maotaiLastSeconds;
    private double _maotaiPointerX;
    private double _maotaiPointerY;
    private bool _maotaiPointerInside;
    private MaotaiInteractionKind _maotaiInteraction = MaotaiInteractionKind.None;
    private double _maotaiInteractionUntilSeconds;
    private bool _maotaiJumpRequested;

    /// <summary>初始化一次表现层事件；不创建第二套业务状态机。</summary>
    protected override void OnInitialized(EventArgs e)
    {
        base.OnInitialized(e);

        Loaded            += MaotaiPet_Loaded;
        Unloaded          += MaotaiPet_Unloaded;
        IsVisibleChanged  += MaotaiPet_IsVisibleChanged;
        MouseMove         += MaotaiPet_MouseMove;
        MouseLeave        += MaotaiPet_MouseLeave;
        MouseLeftButtonUp += MaotaiPet_MouseLeftButtonUp;
        AddHandler(
            System.Windows.Controls.Control.MouseDoubleClickEvent,
            new System.Windows.Input.MouseButtonEventHandler(MaotaiPet_MouseDoubleClick),
            handledEventsToo: true);
    }

    private void MaotaiPet_Loaded(object sender, RoutedEventArgs e)
    {
        EnsureMaotaiV2Initialized();
        StartMaotaiRendering();
    }

    private void MaotaiPet_Unloaded(object sender, RoutedEventArgs e)
    {
        StopMaotaiRendering();
    }

    private void MaotaiPet_IsVisibleChanged(
        object sender,
        DependencyPropertyChangedEventArgs e)
    {
        if (e.NewValue is true)
        {
            EnsureMaotaiV2Initialized();
            StartMaotaiRendering();
            return;
        }

        StopMaotaiRendering();
    }

    /// <summary>只在真实可见且完整 Rig 可用时挂接显示器渲染节拍。</summary>
    private void StartMaotaiRendering()
    {
        if (!IsLoaded ||
            !IsVisible ||
            !_maotaiRigReady ||
            _maotaiRenderingSubscribed)
        {
            return;
        }

        _maotaiClock.Restart();
        _maotaiLastSeconds         = 0.0;
        _maotaiRenderingSubscribed = true;
        CompositionTarget.Rendering += MaotaiCompositionTarget_Rendering;
    }

    /// <summary>隐藏/卸载时严格退订一次，防止后台空转和窗口重复订阅。</summary>
    private void StopMaotaiRendering()
    {
        if (_maotaiRenderingSubscribed)
        {
            CompositionTarget.Rendering -= MaotaiCompositionTarget_Rendering;
            _maotaiRenderingSubscribed   = false;
        }

        _maotaiClock.Stop();
        _maotaiLastSeconds = 0.0;
    }

    private void MaotaiCompositionTarget_Rendering(object? sender, EventArgs e)
    {
        if (!_maotaiRenderingSubscribed ||
            !IsVisible ||
            _maotaiMotionEngine is null ||
            _maotaiRenderer is null)
        {
            return;
        }

        var now = _maotaiClock.Elapsed.TotalSeconds;
        var dt  = Math.Clamp(
            now - _maotaiLastSeconds,
            0.0,
            MaotaiMaximumDeltaSeconds);
        _maotaiLastSeconds = now;

        ExpireMaotaiInteraction(now);
        var input = BuildMaotaiMotionInput();
        var frame = _maotaiMotionEngine.Update(dt, input);
        _maotaiRenderer.Apply(frame);
        _maotaiJumpRequested = false;
    }

    /// <summary>首次加载时一次完成白名单解码、Transform 缓存和 Renderer 组装。</summary>
    private void EnsureMaotaiV2Initialized()
    {
        if (_maotaiRigInitialized)
        {
            return;
        }

        _maotaiRigInitialized = true;
        EnsureMaotaiV2TorsoVariantLayers();
        LoadMaotaiV2Sources();

        _maotaiRigReady = HasCompleteMaotaiV2Rig();
        if (!_maotaiRigReady)
        {
            MaotaiV2Root.Opacity   = 0.0;
            MaotaiV2Laptop.Opacity = 0.0;
            MaotaiV2Drink.Opacity  = 0.0;
            return;
        }

        ConfigureMaotaiV2LayerVisibility();
        _maotaiMotionEngine = new MaotaiMotionEngine(seed: 23, initialX: MaotaiRestingAnchorX);
        _maotaiRenderer     = new MaotaiRasterRenderer(BuildMaotaiRasterVisuals());

        // First pose       : apply while root is hidden so eyes/mouth cannot flash through all states at once.
        var initialFrame = _maotaiMotionEngine.Update(
            0.0,
            BuildMaotaiMotionInput());
        _maotaiRenderer.Apply(initialFrame);
        MaotaiV2Root.Opacity = 1.0;
    }

    private static bool HasCompleteMaotaiV2Rig()
    {
        foreach (var fileName in MaotaiRequiredRigAssets)
        {
            if (!MaotaiPetAssetLoader.HasUsableV2Part(fileName))
            {
                return false;
            }
        }

        return true;
    }

    private void LoadMaotaiV2Sources()
    {
        MaotaiV2TorsoNeutral.Source     = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.TorsoNeutral);
        MaotaiV2TorsoCrouch.Source      = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.TorsoCrouch);
        MaotaiV2TorsoStretch.Source     = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.TorsoStretch);
        MaotaiV2ChestFur.Source         = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.ChestFur);
        MaotaiV2Head.Source             = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.Head);
        MaotaiV2EarLeft.Source          = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.EarLeft);
        MaotaiV2EarRight.Source         = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.EarRight);
        MaotaiV2EyeLeftOpen.Source      = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.EyeLeftOpen);
        MaotaiV2EyeRightOpen.Source     = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.EyeRightOpen);
        MaotaiV2EyeLeftHalf.Source      = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.EyeLeftHalf);
        MaotaiV2EyeRightHalf.Source     = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.EyeRightHalf);
        MaotaiV2EyeLeftClosed.Source    = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.EyeLeftClosed);
        MaotaiV2EyeRightClosed.Source   = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.EyeRightClosed);
        MaotaiV2PupilLeft.Source        = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.PupilLeft);
        MaotaiV2PupilRight.Source       = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.PupilRight);
        MaotaiV2BrowLeft.Source         = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.BrowLeft);
        MaotaiV2BrowRight.Source        = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.BrowRight);
        MaotaiV2Muzzle.Source           = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.Muzzle);
        MaotaiV2MouthSmile.Source       = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.MouthSmile);
        MaotaiV2MouthTired.Source       = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.MouthTired);
        MaotaiV2MouthAnnoyed.Source     = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.MouthAnnoyed);
        MaotaiV2MouthYawn.Source        = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.MouthYawn);
        MaotaiV2MouthTongue.Source      = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.MouthTongue);
        MaotaiV2FrontLeftUpper.Source   = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.FrontLeftUpper);
        MaotaiV2FrontLeftLower.Source   = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.FrontLeftLower);
        MaotaiV2FrontLeftPaw.Source     = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.FrontLeftPaw);
        MaotaiV2FrontRightUpper.Source  = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.FrontRightUpper);
        MaotaiV2FrontRightLower.Source  = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.FrontRightLower);
        MaotaiV2FrontRightPaw.Source    = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.FrontRightPaw);
        MaotaiV2HindLeftUpper.Source    = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.HindLeftUpper);
        MaotaiV2HindLeftLower.Source    = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.HindLeftLower);
        MaotaiV2HindLeftPaw.Source      = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.HindLeftPaw);
        MaotaiV2HindRightUpper.Source   = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.HindRightUpper);
        MaotaiV2HindRightLower.Source   = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.HindRightLower);
        MaotaiV2HindRightPaw.Source     = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.HindRightPaw);
        MaotaiV2TailBase.Source         = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.TailBase);
        MaotaiV2TailMid.Source          = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.TailMid);
        MaotaiV2TailTip.Source          = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.TailTip);
        MaotaiV2HeadphoneBand.Source    = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.HeadphoneBand);
        MaotaiV2HeadphoneLeft.Source    = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.HeadphoneLeft);
        MaotaiV2HeadphoneRight.Source   = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.HeadphoneRight);
        MaotaiV2Shadow.Source           = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.Shadow);
        MaotaiV2Laptop.Source           = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.Laptop);
        MaotaiV2Drink.Source            = MaotaiPetAssetLoader.LoadV2Part(MaotaiAssetManifest.Drink);
    }

    private void ConfigureMaotaiV2LayerVisibility()
    {
        MaotaiV2TorsoNeutral.Opacity    = 1.0;
        MaotaiV2TorsoCrouch.Opacity     = 0.0;
        MaotaiV2TorsoStretch.Opacity    = 0.0;
        MaotaiV2ChestFur.Opacity        = 1.0;
        MaotaiV2Head.Opacity            = 1.0;
        MaotaiV2EarLeft.Opacity         = 1.0;
        MaotaiV2EarRight.Opacity        = 1.0;
        MaotaiV2PupilLeft.Opacity       = 1.0;
        MaotaiV2PupilRight.Opacity      = 1.0;
        MaotaiV2BrowLeft.Opacity        = 1.0;
        MaotaiV2BrowRight.Opacity       = 1.0;
        MaotaiV2Muzzle.Opacity          = 1.0;
        MaotaiV2FrontLeftUpper.Opacity  = 1.0;
        MaotaiV2FrontLeftLower.Opacity  = 1.0;
        MaotaiV2FrontLeftPaw.Opacity    = 1.0;
        MaotaiV2FrontRightUpper.Opacity = 1.0;
        MaotaiV2FrontRightLower.Opacity = 1.0;
        MaotaiV2FrontRightPaw.Opacity   = 1.0;
        MaotaiV2HindLeftUpper.Opacity   = 1.0;
        MaotaiV2HindLeftLower.Opacity   = 1.0;
        MaotaiV2HindLeftPaw.Opacity     = 1.0;
        MaotaiV2HindRightUpper.Opacity  = 1.0;
        MaotaiV2HindRightLower.Opacity  = 1.0;
        MaotaiV2HindRightPaw.Opacity    = 1.0;
        MaotaiV2TailBase.Opacity        = 1.0;
        MaotaiV2TailMid.Opacity         = 1.0;
        MaotaiV2TailTip.Opacity         = 1.0;
        MaotaiV2HeadphoneBand.Opacity   = 1.0;
        MaotaiV2HeadphoneLeft.Opacity   = 1.0;
        MaotaiV2HeadphoneRight.Opacity  = 1.0;
        MaotaiV2Shadow.Opacity          = 1.0;
    }

    private MaotaiRasterVisuals BuildMaotaiRasterVisuals() => new()
    {
        RootTranslate       = MaotaiV2RootTranslate,
        FacingScale         = MaotaiV2FacingScale,
        Body                = new MaotaiRasterPart(MaotaiV2BodyBone, MaotaiV2BodyTranslate, MaotaiV2BodyRotate, MaotaiV2BodyScale),
        TorsoNeutral        = MaotaiV2TorsoNeutral,
        TorsoCrouch         = MaotaiV2TorsoCrouch,
        TorsoStretch        = MaotaiV2TorsoStretch,
        Chest               = new MaotaiRasterPart(MaotaiV2ChestFur, MaotaiAssetManifest.ChestFur),
        Head                = new MaotaiRasterPart(MaotaiV2HeadBone, MaotaiV2HeadTranslate, MaotaiV2HeadRotate, MaotaiV2HeadScale),
        LeftEar             = new MaotaiRasterPart(MaotaiV2EarLeft, MaotaiV2EarLeftTranslate, MaotaiV2EarLeftRotate),
        RightEar            = new MaotaiRasterPart(MaotaiV2EarRight, MaotaiV2EarRightTranslate, MaotaiV2EarRightRotate),
        LeftPupil           = new MaotaiRasterPart(MaotaiV2PupilLeft, MaotaiV2PupilLeftTranslate, MaotaiV2PupilLeftRotate),
        RightPupil          = new MaotaiRasterPart(MaotaiV2PupilRight, MaotaiV2PupilRightTranslate, MaotaiV2PupilRightRotate),
        FrontLeftUpper      = new MaotaiRasterPart(MaotaiV2FrontLeftUpper, MaotaiV2FrontLeftUpperTranslate, MaotaiV2FrontLeftUpperRotate),
        FrontLeftLower      = new MaotaiRasterPart(MaotaiV2FrontLeftLower, MaotaiV2FrontLeftLowerTranslate, MaotaiV2FrontLeftLowerRotate),
        FrontLeftPaw        = new MaotaiRasterPart(MaotaiV2FrontLeftPaw, MaotaiV2FrontLeftPawTranslate, MaotaiV2FrontLeftPawRotate),
        FrontRightUpper     = new MaotaiRasterPart(MaotaiV2FrontRightUpper, MaotaiV2FrontRightUpperTranslate, MaotaiV2FrontRightUpperRotate),
        FrontRightLower     = new MaotaiRasterPart(MaotaiV2FrontRightLower, MaotaiV2FrontRightLowerTranslate, MaotaiV2FrontRightLowerRotate),
        FrontRightPaw       = new MaotaiRasterPart(MaotaiV2FrontRightPaw, MaotaiV2FrontRightPawTranslate, MaotaiV2FrontRightPawRotate),
        HindLeftUpper       = new MaotaiRasterPart(MaotaiV2HindLeftUpper, MaotaiV2HindLeftUpperTranslate, MaotaiV2HindLeftUpperRotate),
        HindLeftLower       = new MaotaiRasterPart(MaotaiV2HindLeftLower, MaotaiV2HindLeftLowerTranslate, MaotaiV2HindLeftLowerRotate),
        HindLeftPaw         = new MaotaiRasterPart(MaotaiV2HindLeftPaw, MaotaiV2HindLeftPawTranslate, MaotaiV2HindLeftPawRotate),
        HindRightUpper      = new MaotaiRasterPart(MaotaiV2HindRightUpper, MaotaiV2HindRightUpperTranslate, MaotaiV2HindRightUpperRotate),
        HindRightLower      = new MaotaiRasterPart(MaotaiV2HindRightLower, MaotaiV2HindRightLowerTranslate, MaotaiV2HindRightLowerRotate),
        HindRightPaw        = new MaotaiRasterPart(MaotaiV2HindRightPaw, MaotaiV2HindRightPawTranslate, MaotaiV2HindRightPawRotate),
        TailBase            = new MaotaiRasterPart(MaotaiV2TailBase, MaotaiV2TailBaseTranslate, MaotaiV2TailBaseRotate),
        TailMid             = new MaotaiRasterPart(MaotaiV2TailMid, MaotaiV2TailMidTranslate, MaotaiV2TailMidRotate),
        TailTip             = new MaotaiRasterPart(MaotaiV2TailTip, MaotaiV2TailTipTranslate, MaotaiV2TailTipRotate),
        EyeLeftOpen         = MaotaiV2EyeLeftOpen,
        EyeRightOpen        = MaotaiV2EyeRightOpen,
        EyeLeftHalf         = MaotaiV2EyeLeftHalf,
        EyeRightHalf        = MaotaiV2EyeRightHalf,
        EyeLeftClosed       = MaotaiV2EyeLeftClosed,
        EyeRightClosed      = MaotaiV2EyeRightClosed,
        MouthSmile          = MaotaiV2MouthSmile,
        MouthTired          = MaotaiV2MouthTired,
        MouthAnnoyed        = MaotaiV2MouthAnnoyed,
        MouthYawn           = MaotaiV2MouthYawn,
        MouthTongue         = MaotaiV2MouthTongue,
        Laptop              = MaotaiV2Laptop,
        Drink               = MaotaiV2Drink,
    };

    /// <summary>帧输入只读取本控件已缓存状态；严禁在 Render Loop 访问磁盘/网络/Core API。</summary>
    private MaotaiMotionInput BuildMaotaiMotionInput()
    {
        var baseState = _activeMode switch
        {
            AssistantPetMode.Working => MaotaiBaseState.Working,
            AssistantPetMode.Waiting => MaotaiBaseState.Waiting,
            AssistantPetMode.Offline => MaotaiBaseState.Offline,
            AssistantPetMode.Error   => MaotaiBaseState.Error,
            _                        => MaotaiBaseState.Resting,
        };

        var interaction = _isDragging
            ? MaotaiInteractionKind.Drag
            : _maotaiInteraction;
        var targetX = baseState == MaotaiBaseState.Working
            ? MaotaiWorkingAnchorX
            : MaotaiRestingAnchorX;

        return new MaotaiMotionInput(
            baseState,
            _maotaiPointerX,
            _maotaiPointerY,
            _maotaiPointerInside,
            interaction,
            MaotaiStageMinX,
            MaotaiStageMaxX,
            targetX,
            WantsRun: false,
            WantsJump: _maotaiJumpRequested,
            WorkAnchorX: MaotaiWorkingAnchorX);
    }

    private void ExpireMaotaiInteraction(double now)
    {
        if (_maotaiInteraction == MaotaiInteractionKind.None ||
            now < _maotaiInteractionUntilSeconds)
        {
            return;
        }

        _maotaiInteraction             = MaotaiInteractionKind.None;
        _maotaiInteractionUntilSeconds = 0.0;
    }

    private void MaotaiPet_MouseMove(
        object sender,
        System.Windows.Input.MouseEventArgs e)
    {
        if (PetStage.ActualWidth <= 0.0 || PetStage.ActualHeight <= 0.0)
        {
            return;
        }

        var position         = e.GetPosition(PetStage);
        _maotaiPointerX      = Math.Clamp((position.X / PetStage.ActualWidth * 2.0) - 1.0, -1.0, 1.0);
        _maotaiPointerY      = Math.Clamp((position.Y / PetStage.ActualHeight * 2.0) - 1.0, -1.0, 1.0);
        _maotaiPointerInside = true;
    }

    private void MaotaiPet_MouseLeave(
        object sender,
        System.Windows.Input.MouseEventArgs e)
    {
        _maotaiPointerInside = false;
        _maotaiPointerX      = 0.0;
        _maotaiPointerY      = 0.0;
    }

    private void MaotaiPet_MouseLeftButtonUp(
        object sender,
        System.Windows.Input.MouseButtonEventArgs e)
    {
        if (_isDragging || PetStage.ActualHeight <= 0.0)
        {
            return;
        }

        var position = e.GetPosition(PetStage);
        var headHit  = position.Y <= PetStage.ActualHeight * 0.58;
        SetMaotaiInteraction(
            headHit ? MaotaiInteractionKind.Pat : MaotaiInteractionKind.Paw,
            durationSeconds: 0.55);
    }

    private void MaotaiPet_MouseDoubleClick(
        object sender,
        System.Windows.Input.MouseButtonEventArgs e)
    {
        SetMaotaiInteraction(
            MaotaiInteractionKind.Celebrate,
            durationSeconds: 0.80);
        _maotaiJumpRequested = true;
    }

    private void SetMaotaiInteraction(
        MaotaiInteractionKind interaction,
        double durationSeconds)
    {
        _maotaiInteraction             = interaction;
        _maotaiInteractionUntilSeconds = _maotaiClock.Elapsed.TotalSeconds +
            Math.Max(0.05, durationSeconds);
    }
}
