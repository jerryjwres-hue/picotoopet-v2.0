using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>桌宠独立表情层；仅描述视觉情绪，不承载业务状态。</summary>
public enum PetEmotion
{
    Calm,
    Focused,
    Happy,
    Curious,
    Sleepy,
    Concerned,
}

/// <summary>可临时覆盖基础状态的微动作；结束后自动回到真实基础状态。</summary>
public enum PetMicroAction
{
    None,
    LookAround,
    Stretch,
    Yawn,
    LickNose,
    CuriousTilt,
    HappyBounce,
    FocusGlance,
}

/// <summary>一次纯展示行为帧；数值均为有界视觉提示，不写入 Session。</summary>
public sealed record PetBehaviorFrame(
    PetEmotion Emotion,
    PetMicroAction Action,
    double HeadTilt,
    double EarTilt,
    double TailEnergy,
    string? ReactionGlyph);

/// <summary>把基础宠物状态组合成低重复的表情与随机微动作，不拥有任何业务服务引用。</summary>
public sealed class PetBehaviorController
{
    private readonly Random _random;
    private readonly Queue<PetMicroAction> _recentActions = new();
    private AssistantPetMode? _lastMode;
    private int _ticksUntilAction;

    /// <summary>运行时使用随机种子；测试可传固定种子获得可重复序列。</summary>
    public PetBehaviorController(int? seed = null)
    {
        _random = seed is null
            ? new Random()
            : new Random(seed.Value);
        _ticksUntilAction = 6;
    }

    /// <summary>生成下一展示帧；pointer/drag 活跃时仅返回基础情绪，不抢占用户交互。</summary>
    public PetBehaviorFrame Next(
        AssistantPetMode mode,
        bool allowMicroAction)
    {
        if (_lastMode != mode)
        {
            _lastMode         = mode;
            _ticksUntilAction = InitialCooldown(mode);
            _recentActions.Clear();
        }

        var baseEmotion = BaseEmotion(mode);
        if (!allowMicroAction || mode is AssistantPetMode.Offline or AssistantPetMode.Error)
        {
            return BaseFrame(baseEmotion);
        }

        _ticksUntilAction--;
        if (_ticksUntilAction > 0)
        {
            return BaseFrame(baseEmotion);
        }

        var action = PickAction(mode);
        RememberAction(action);
        _ticksUntilAction = NextCooldown(mode);
        return FrameFor(action, baseEmotion);
    }

    private PetMicroAction PickAction(AssistantPetMode mode)
    {
        var choices = mode switch
        {
            AssistantPetMode.Working => WorkingActions,
            AssistantPetMode.Waiting => WaitingActions,
            _                        => RestingActions,
        };
        var available = choices
            .Where(action => !_recentActions.Contains(action))
            .ToArray();
        var candidates = available.Length > 0
            ? available
            : choices;
        return candidates[_random.Next(candidates.Length)];
    }

    private void RememberAction(PetMicroAction action)
    {
        _recentActions.Enqueue(action);
        while (_recentActions.Count > 2)
        {
            _recentActions.Dequeue();
        }
    }

    private int NextCooldown(AssistantPetMode mode) => mode switch
    {
        AssistantPetMode.Working => _random.Next(9, 17),
        AssistantPetMode.Waiting => _random.Next(7, 14),
        _                        => _random.Next(6, 15),
    };

    private static int InitialCooldown(AssistantPetMode mode) => mode switch
    {
        AssistantPetMode.Working => 8,
        AssistantPetMode.Waiting => 5,
        _                        => 4,
    };

    private static PetEmotion BaseEmotion(AssistantPetMode mode) => mode switch
    {
        AssistantPetMode.Working => PetEmotion.Focused,
        AssistantPetMode.Waiting => PetEmotion.Curious,
        AssistantPetMode.Offline => PetEmotion.Sleepy,
        AssistantPetMode.Error   => PetEmotion.Concerned,
        _                        => PetEmotion.Calm,
    };

    private static PetBehaviorFrame BaseFrame(PetEmotion emotion) =>
        new(emotion, PetMicroAction.None, 0, 0, 0.45, null);

    private static PetBehaviorFrame FrameFor(
        PetMicroAction action,
        PetEmotion fallbackEmotion) => action switch
    {
        PetMicroAction.LookAround =>
            new(PetEmotion.Curious, action, -5.5, 2.0, 0.55, "✦"),
        PetMicroAction.Stretch =>
            new(PetEmotion.Happy, action, 0, -2.0, 0.72, "♪"),
        PetMicroAction.Yawn =>
            new(PetEmotion.Sleepy, action, 1.5, -4.0, 0.25, "…"),
        PetMicroAction.LickNose =>
            new(PetEmotion.Happy, action, 2.0, 1.0, 0.58, "♥"),
        PetMicroAction.CuriousTilt =>
            new(PetEmotion.Curious, action, 8.0, 5.0, 0.50, "?"),
        PetMicroAction.HappyBounce =>
            new(PetEmotion.Happy, action, -2.0, 3.0, 1.00, "✨"),
        PetMicroAction.FocusGlance =>
            new(PetEmotion.Focused, action, -3.0, 0, 0.35, null),
        _ => BaseFrame(fallbackEmotion),
    };

    private static readonly PetMicroAction[] WorkingActions =
    {
        PetMicroAction.FocusGlance,
        PetMicroAction.FocusGlance,
        PetMicroAction.CuriousTilt,
        PetMicroAction.LickNose,
        PetMicroAction.LookAround,
    };

    private static readonly PetMicroAction[] WaitingActions =
    {
        PetMicroAction.CuriousTilt,
        PetMicroAction.LookAround,
        PetMicroAction.Yawn,
        PetMicroAction.LickNose,
    };

    private static readonly PetMicroAction[] RestingActions =
    {
        PetMicroAction.LookAround,
        PetMicroAction.Stretch,
        PetMicroAction.Yawn,
        PetMicroAction.LickNose,
        PetMicroAction.CuriousTilt,
        PetMicroAction.HappyBounce,
    };
}
