namespace PicotooPet.Desktop.Controls.PetMascot;

/// <summary>只根据宿主已经给出的展示事实选择短句，不访问 AI、网络、磁盘或业务服务。</summary>
internal static class PetMascotPromptPolicy
{
    public static string Select(
        PetMascotState state,
        int pendingReviewCount,
        int inProgressCount,
        int completedCount)
    {
        return state switch
        {
            PetMascotState.Working => "任务还在进行中，茅台帮你盯着。",
            PetMascotState.Success => "搞定啦！茅台已经帮你守到结果了。",
            PetMascotState.Away    => "茅台出去转一圈，有事回来再叫我。",
            PetMascotState.Bath    => "茅台正在补充一点精神值。",
            PetMascotState.Offline => "茅台先睡一会儿，有事再叫我。",
            _                      => SelectIdle(pendingReviewCount, inProgressCount, completedCount),
        };
    }

    private static string SelectIdle(
        int pendingReviewCount,
        int inProgressCount,
        int completedCount)
    {
        if (pendingReviewCount > 0)
        {
            return $"有 {pendingReviewCount} 件东西等你看看，茅台没有乱动它。";
        }

        if (inProgressCount > 0)
        {
            return $"还有 {inProgressCount} 个任务在跑，茅台继续帮你看着。";
        }

        if (completedCount > 0)
        {
            return "今天已经有成果啦，茅台现在待命中。";
        }

        return "茅台待命中，有事叫我就好。";
    }
}
