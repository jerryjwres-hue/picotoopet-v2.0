using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Control Center 能力协商 JSON 的兼容反序列化。</summary>
internal static class CapabilitySmokeTests
{
    /// <summary>未实现能力必须保持关闭，冻结合同能力必须明确可见。</summary>
    public static void Run()
    {
        const string json = """
        {
          "schema_version": "2.3.0",
          "features": {
            "local_agent": true,
            "durable_queue": true,
            "mcp_hub": true,
            "dashboard": false,
            "task_detail": false,
            "task_pause_resume": false,
            "approval_list": false,
            "approval_digest": false,
            "result_list": false,
            "result_preview": false,
            "health_detailed": false,
            "logs_query": false,
            "manual_goal": false,
            "connector_contract_v1": true,
            "handoff_contract_v1": true,
            "windows_worker": false
          },
          "contract_versions": {
            "connector": "1.0.0",
            "handoff_return": "1.0.0"
          },
          "cloud_upload": "manual_approval_only"
        }
        """;

        var response = JsonSerializer.Deserialize<CapabilitiesResponse>(json);
        SmokeAssert.True(response is not null, "能力响应反序列化失败");
        SmokeAssert.True(
            response!.Features.ConnectorContractV1,
            "Connector 合同能力缺失");
        SmokeAssert.True(
            response.Features.HandoffContractV1,
            "Handoff 合同能力缺失");
        SmokeAssert.True(
            !response.Features.Dashboard,
            "未实现 Dashboard 不得标记可用");
    }
}
