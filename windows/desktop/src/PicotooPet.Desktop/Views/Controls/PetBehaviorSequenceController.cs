using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>单个桌宠动作步骤；所有值均为有界展示参数。</summary>
public sealed record PetSequenceStep(
    TimeSpan Duration,
    double HeadAngle,
    double LeftPawY,
    double RightPawY,
    string EyesKey,
    string BrowsKey,
    string MouthKey);

/// <summary>短时展示序列；结束后必须回到当时最新的真实基础状态。</summary>
public sealed record PetBehaviorSequence(
    string Name,
    IReadOnlyList<PetSequenceStep> Steps,
    bool ReturnsToLatestBaseState);

/// <summary>茅台的展示序列调度器；不持有 Session、任务服务或任何业务写入能力。</summary>
public sealed class PetBehaviorSequenceController
{
    private readonly Random _random;

    /// <summary>运行时使用随机种子；测试可传固定种子获得可重复选择。</summary>
    public PetBehaviorSequenceController(int? seed = null)
    {
        _random = seed is null
            ? new Random()
            : new Random(seed.Value);
    }

    /// <summary>根据当前真实基础状态和展示情绪选择一个短序列。</summary>
    public PetBehaviorSequence NextSequence(
        AssistantPetMode mode,
        PetEmotion emotion)
    {
        return mode switch
        {
            AssistantPetMode.Working => PickWorkingSequence(emotion),
            AssistantPetMode.Resting => RestBubble(),
            AssistantPetMode.Offline => OfflineBreath(),
            AssistantPetMode.Waiting => WaitingAttention(),
            AssistantPetMode.Error   => ErrorConcern(),
            _                        => Blink(),
        };
    }

    private PetBehaviorSequence PickWorkingSequence(PetEmotion emotion)
    {
        if (emotion == PetEmotion.Sleepy)
        {
            return WorkingTired();
        }
        if (emotion == PetEmotion.Concerned)
        {
            return WorkingAnnoyed();
        }

        var roll = _random.Next(0, 10);
        return roll switch
        {
            0 => WorkingTired(),
            1 => WorkingAnnoyed(),
            _ => WorkingType(),
        };
    }

    private static PetBehaviorSequence WorkingType() => new(
        "WorkingType",
        new[]
        {
            Step(180, -1.0, -2.0,  1.0, "open", "focused", "happy"),
            Step(180,  0.8,  1.0, -2.5, "open", "focused", "happy"),
            Step(130,  0.0, -1.0,  0.0, "closed", "focused", "happy"),
            Step(190, -0.6,  0.0, -1.0, "open", "focused", "happy"),
        },
        true);

    private static PetBehaviorSequence WorkingTired() => new(
        "WorkingTired",
        new[]
        {
            Step(420,  3.5, -0.5, -0.5, "half", "focused", "tired"),
            Step(520,  5.0,  0.0,  0.0, "half", "focused", "tired"),
            Step(260,  2.5, -1.0,  0.0, "closed", "focused", "tired"),
            Step(360,  1.0,  0.0, -1.0, "open", "focused", "happy"),
        },
        true);

    private static PetBehaviorSequence WorkingAnnoyed() => new(
        "WorkingAnnoyed",
        new[]
        {
            Step(120, -2.0, -3.0,  2.0, "open", "annoyed", "annoyed"),
            Step(120,  2.0,  2.0, -3.0, "open", "annoyed", "annoyed"),
            Step(120, -1.5, -3.0,  2.0, "open", "annoyed", "annoyed"),
            Step(220,  0.0,  0.0,  0.0, "open", "focused", "happy"),
        },
        true);

    private static PetBehaviorSequence Blink() => new(
        "Blink",
        new[]
        {
            Step(80, 0, 0, 0, "open", "focused", "happy"),
            Step(90, 0, 0, 0, "closed", "focused", "happy"),
            Step(90, 0, 0, 0, "open", "focused", "happy"),
        },
        true);

    private static PetBehaviorSequence RestBubble() => new(
        "RestBubble",
        new[]
        {
            Step(460, -1.0, 0, 0, "open", "focused", "happy"),
            Step(180,  1.0, 0, 0, "closed", "focused", "happy"),
            Step(460,  0.0, 0, 0, "open", "focused", "happy"),
        },
        true);

    private static PetBehaviorSequence OfflineBreath() => new(
        "OfflineBreath",
        new[]
        {
            Step(900, 2.0, 0, 0, "closed", "focused", "happy"),
            Step(900, 3.0, 0, 0, "closed", "focused", "happy"),
        },
        true);

    private static PetBehaviorSequence WaitingAttention() => new(
        "WaitingAttention",
        new[]
        {
            Step(260, -5.0, 0, 0, "open", "focused", "happy"),
            Step(320,  5.0, 0, 0, "open", "focused", "happy"),
            Step(260,  0.0, 0, 0, "open", "focused", "happy"),
        },
        true);

    private static PetBehaviorSequence ErrorConcern() => new(
        "ErrorConcern",
        new[]
        {
            Step(160, -3.0, 0, 0, "open", "annoyed", "annoyed"),
            Step(160,  3.0, 0, 0, "open", "annoyed", "annoyed"),
            Step(220,  0.0, 0, 0, "open", "focused", "happy"),
        },
        true);

    private static PetSequenceStep Step(
        int milliseconds,
        double headAngle,
        double leftPawY,
        double rightPawY,
        string eyes,
        string brows,
        string mouth) => new(
            TimeSpan.FromMilliseconds(milliseconds),
            headAngle,
            leftPawY,
            rightPawY,
            eyes,
            brows,
            mouth);
}
