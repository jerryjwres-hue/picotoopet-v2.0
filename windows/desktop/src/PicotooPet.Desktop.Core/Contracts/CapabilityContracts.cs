using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Mac Core 返回的版本化 Control Center 能力快照。</summary>
public sealed record CapabilitiesResponse(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("features")] ControlCenterCapabilities Features,
    [property: JsonPropertyName("contract_versions")] ContractVersions ContractVersions,
    [property: JsonPropertyName("cloud_upload")] string CloudUpload);

/// <summary>服务端显式声明的页面和命令能力；客户端不得凭版本号猜测。</summary>
public sealed record ControlCenterCapabilities(
    [property: JsonPropertyName("local_agent")] bool LocalAgent,
    [property: JsonPropertyName("durable_queue")] bool DurableQueue,
    [property: JsonPropertyName("mcp_hub")] bool McpHub,
    [property: JsonPropertyName("dashboard")] bool Dashboard,
    [property: JsonPropertyName("task_detail")] bool TaskDetail,
    [property: JsonPropertyName("task_pause_resume")] bool TaskPauseResume,
    [property: JsonPropertyName("approval_list")] bool ApprovalList,
    [property: JsonPropertyName("approval_digest")] bool ApprovalDigest,
    [property: JsonPropertyName("result_list")] bool ResultList,
    [property: JsonPropertyName("result_preview")] bool ResultPreview,
    [property: JsonPropertyName("health_detailed")] bool HealthDetailed,
    [property: JsonPropertyName("logs_query")] bool LogsQuery,
    [property: JsonPropertyName("manual_goal")] bool ManualGoal,
    [property: JsonPropertyName("connector_contract_v1")] bool ConnectorContractV1,
    [property: JsonPropertyName("handoff_contract_v1")] bool HandoffContractV1,
    [property: JsonPropertyName("worker_status")] bool WorkerStatus,
    [property: JsonPropertyName("worker_execution")] bool WorkerExecution,
    [property: JsonPropertyName("windows_worker")] bool WindowsWorker)
{
    /// <summary>旧版 2.2 服务的保守能力集；未知功能一律关闭。</summary>
    public static ControlCenterCapabilities Legacy22 { get; } = new(
        LocalAgent: true,
        DurableQueue: true,
        McpHub: true,
        Dashboard: false,
        TaskDetail: false,
        TaskPauseResume: false,
        ApprovalList: false,
        ApprovalDigest: false,
        ResultList: false,
        ResultPreview: false,
        HealthDetailed: false,
        LogsQuery: false,
        ManualGoal: false,
        ConnectorContractV1: false,
        HandoffContractV1: false,
        WorkerStatus: false,
        WorkerExecution: false,
        WindowsWorker: false);
}

/// <summary>已冻结但不代表运行时已实现的合同版本。</summary>
public sealed record ContractVersions(
    [property: JsonPropertyName("connector")] string Connector,
    [property: JsonPropertyName("handoff_return")] string HandoffReturn);
