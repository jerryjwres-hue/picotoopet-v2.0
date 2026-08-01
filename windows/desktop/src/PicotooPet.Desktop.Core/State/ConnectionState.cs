namespace PicotooPet.Desktop.Core.State;

/// <summary>桌面端连接状态机。</summary>
public enum ConnectionState
{
    Offline,
    Connecting,
    Online,
    Reconnecting,
    AuthenticationFailed,
    Faulted,
}
