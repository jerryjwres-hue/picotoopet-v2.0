using PicotooPet.Desktop.Views.Controls.MaotaiMotion;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>茅台 v2 自主行为只负责表现输入；不创建业务事实，也不引入第二个渲染时钟。</summary>
public partial class AssistantPetPanel
{
    private const double MaotaiFloatingStageMinX = 18.0;
    private const double MaotaiFloatingStageMaxX = 150.0;

    private readonly MaotaiAutonomousBehaviorController _maotaiAutonomy = new(seed: 73);

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
