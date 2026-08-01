namespace PicotooPet.Desktop.Services;

/// <summary>暴露系统托盘的三个显式用户命令，并统一释放原生句柄。</summary>
public interface ITrayService : IDisposable
{
    /// <summary>请求显示并激活 Control Center。</summary>
    event EventHandler? OpenRequested;

    /// <summary>请求打开审批说明或审批列表。</summary>
    event EventHandler? PendingApprovalsRequested;

    /// <summary>请求显式退出桌面 UI。</summary>
    event EventHandler? ExitRequested;
}
