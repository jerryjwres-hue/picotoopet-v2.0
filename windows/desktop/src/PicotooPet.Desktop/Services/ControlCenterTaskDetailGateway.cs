using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Services;

/// <summary>从唯一 Session 快照解析任务并创建统一任务详情模型；不复制任务状态。</summary>
public sealed class ControlCenterTaskDetailGateway
{
    private readonly ControlCenterSession _session;

    public ControlCenterTaskDetailGateway(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    public TaskDetailViewModel Create(string taskId)
    {
        if (string.IsNullOrWhiteSpace(taskId))
        {
            throw new ArgumentException("任务 ID 不能为空。", nameof(taskId));
        }

        var task = _session.Snapshot.State.Tasks.Tasks.FirstOrDefault(candidate =>
            string.Equals(candidate.TaskId, taskId, StringComparison.Ordinal));
        if (task is null)
        {
            throw new InvalidOperationException("该任务已从当前快照移除，请刷新列表后重试。");
        }

        return new TaskDetailViewModel(_session, task);
    }
}
