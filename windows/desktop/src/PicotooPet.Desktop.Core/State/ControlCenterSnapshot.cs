using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.State;

/// <summary>连接状态仓库发布的不可变快照；REST 是可用性真相，WebSocket 只负责实时性。</summary>
public sealed record ConnectionSnapshot(
    ConnectionState State,
    string? LastError,
    bool CoreReachable = false,
    ConnectionState EventStreamState = ConnectionState.Offline,
    bool RealtimeDegraded = true);

/// <summary>能力状态仓库发布的不可变快照。</summary>
public sealed record CapabilitySnapshot(
    string SchemaVersion,
    ControlCenterCapabilities Features,
    ContractVersions ContractVersions,
    string CloudUpload)
{
    /// <summary>旧版 2.2 服务的保守能力快照。</summary>
    public static CapabilitySnapshot Legacy22 { get; } = new(
        "2.2.0",
        ControlCenterCapabilities.Legacy22,
        new ContractVersions("unavailable", "unavailable"),
        "manual_approval_only");
}

/// <summary>Worker 状态仓库发布的不可变快照。</summary>
public sealed record WorkerSnapshot(
    string SchemaVersion,
    bool Available,
    string State,
    string Reason,
    string? WorkerId,
    IReadOnlyList<string> SupportedTaskTypes,
    DateTimeOffset ObservedAt)
{
    /// <summary>旧服务或未部署执行器的保守状态。</summary>
    public static WorkerSnapshot NotDeployed { get; } = new(
        "2.3.0",
        Available: false,
        State: "not_deployed",
        Reason: "Mac 任务执行器尚未部署；Queued 任务不会自动执行。",
        WorkerId: null,
        SupportedTaskTypes: Array.Empty<string>(),
        ObservedAt: DateTimeOffset.UnixEpoch);
}

/// <summary>任务状态仓库发布的不可变快照。</summary>
public sealed record TaskStateSnapshot(
    IReadOnlyList<TaskRecord> Tasks,
    long LastSequence,
    bool TaskReset,
    TaskRecord? ChangedTask);

/// <summary>Control Center 可组合消费的完整状态快照。</summary>
public sealed record ControlCenterSnapshot(
    ConnectionSnapshot Connection,
    CapabilitySnapshot Capabilities,
    WorkerSnapshot Worker,
    TaskStateSnapshot Tasks);
