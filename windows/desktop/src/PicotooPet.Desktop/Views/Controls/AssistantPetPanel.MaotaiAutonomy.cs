using PicotooPet.Desktop.Views.Controls.MaotaiMotion;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>茅台 v2 自主行为只负责表现输入；不创建业务事实，也不引入第二个渲染时钟。</summary>
public partial class AssistantPetPanel
{
    private const double MaotaiFloatingStageMinX = 18.0;
    private const double MaotaiFloatingStageMaxX = 150.0;
    private const double MaotaiFloatingReleaseSettleSeconds = 0.28;
    private const double MaotaiFloatingSnapSettleSeconds = 0.42;

    private readonly MaotaiAutonomousBehaviorController _maotaiAutonomy = new(seed: 73);
    private double _maotaiFloatingSettleSeconds;

    /// <summary>悬浮窗真正进入 Window.DragMove 前冻结内部 locomotion；窗口位置仍由 Window 自己管理。</summary>
    internal void BeginFloatingWindowDrag()
    {
        if (!IsFloatingMode)
        {
            return;
        }

        _maotaiFloatingSettleSeconds = 0.0;
        _isDragging = true;
    }

    /// <summary>悬浮窗松手后先短暂站稳；发生边缘吸附时给更长 settle，避免吸附结束立刻自主走跑。</summary>
    internal void EndFloatingWindowDrag(bool edgeSnapped)
    {
        if (!IsFloatingMode || !_isDragging)
        {
            return;
        }

        _isDragging = false;
        _maotaiFloatingSettleSeconds = edgeSnapped
            ? MaotaiFloatingSnapSettleSeconds
            : MaotaiFloatingReleaseSettleSeconds;
    }

    /// <summary>
    /// 在唯一 CompositionTarget.Rendering 时钟中推进自主意图。强状态、指针观察、点击和拖动都会暂停自主行为；
    /// 恢复 Resting 后重新选择且不会连续重复上一个动作。
    /// </summary>
    private MaotaiMotionInput BuildMaotaiMotionInput(double deltaTime)
    {
        var baseInput = BuildMaotaiMotionInput();
        var stageMinX = IsFloatingMode
            ? MaotaiFloatingStageMinX
            : baseInput.StageMinX;
        var stageMaxX = IsFloatingMode
            ? MaotaiFloatingStageMaxX
            : baseInput.StageMaxX;
        var currentX = _maotaiMotionEngine?.PositionX ??
            Math.Clamp(baseInput.TargetX, stageMinX, stageMaxX);

        // Real system states always outrank cosmetic settle from a previous window drag.
        if (baseInput.BaseState != MaotaiBaseState.Resting)
        {
            _maotaiFloatingSettleSeconds = 0.0;
        }

        var settleActive = IsFloatingMode &&
            !_isDragging &&
            baseInput.BaseState == MaotaiBaseState.Resting &&
            baseInput.Interaction == MaotaiInteractionKind.None &&
            _maotaiFloatingSettleSeconds > 0.0;
        if (settleActive)
        {
            var dt = double.IsFinite(deltaTime)
                ? Math.Clamp(deltaTime, 0.0, 0.05)
                : 0.0;
            _maotaiFloatingSettleSeconds = Math.Max(
                0.0,
                _maotaiFloatingSettleSeconds - dt);

            _ = _maotaiAutonomy.Update(
                dt,
                currentX,
                stageMinX,
                stageMaxX,
                IsFloatingMode,
                enabled: false);

            return baseInput with
            {
                StageMinX = stageMinX,
                StageMaxX = stageMaxX,
                TargetX = currentX,
                WantsRun = false,
                AutonomousState = MaotaiMotionState.Land,
            };
        }

        var autonomyEnabled = baseInput.BaseState == MaotaiBaseState.Resting &&
            baseInput.Interaction == MaotaiInteractionKind.None &&
            !baseInput.PointerInside;
        var intent = _maotaiAutonomy.Update(
            deltaTime,
            currentX,
            stageMinX,
            stageMaxX,
            IsFloatingMode,
            autonomyEnabled);

        if (autonomyEnabled)
        {
            return baseInput with
            {
                StageMinX = stageMinX,
                StageMaxX = stageMaxX,
                TargetX = intent.TargetX,
                WantsRun = intent.WantsRun,
                AutonomousState = intent.AutonomousState,
            };
        }

        var controlledTarget = baseInput.BaseState == MaotaiBaseState.Working
            ? baseInput.WorkAnchorX
            : currentX;
        return baseInput with
        {
            StageMinX = stageMinX,
            StageMaxX = stageMaxX,
            TargetX = Math.Clamp(controlledTarget, stageMinX, stageMaxX),
            WantsRun = false,
            AutonomousState = null,
        };
    }
}
