using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.State;

/// <summary>连接状态仓库发布的不可变快照。</summary>
public sealed record ConnectionSnapshot(
    ConnectionState State,
    string? LastError);

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
    TaskStateSnapshot Tasks);
