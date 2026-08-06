namespace PicotooPet.Desktop.Core.DevBroker;

/// <summary>Broker 内部允许的固定动作；不存在字符串命令映射。</summary>
public enum BrokerAction
{
    RunMockProvider = 1,
}

/// <summary>拒绝所有未登记 Broker 动作。</summary>
public static class BrokerCommandPolicy
{
    /// <summary>只允许当前版本内置的 Mock Provider 动作。</summary>
    public static bool IsAllowed(BrokerAction action) =>
        action is BrokerAction.RunMockProvider;
}
