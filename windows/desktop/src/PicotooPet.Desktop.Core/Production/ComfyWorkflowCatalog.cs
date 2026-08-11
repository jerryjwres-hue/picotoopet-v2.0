using System.Reflection;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>从 Desktop.Core 程序集读取冻结的 ComfyUI workflow；运行时不依赖 Git checkout 或任意磁盘模板路径。</summary>
public static class ComfyWorkflowCatalog
{
    private const string ResourcePrefix = "PicotooPet.Production.Workflows.";

    /// <summary>加载并验证已 allowlist 的 API-format workflow。</summary>
    public static string Load(string workflowId)
    {
        var resourceName = workflowId switch
        {
            ComfyWorkflowTemplateValidator.T2VWorkflowId =>
                ResourcePrefix + "wan22-ti2v5b-t2v-api-v1.json",
            ComfyWorkflowTemplateValidator.I2VWorkflowId =>
                ResourcePrefix + "wan22-ti2v5b-i2v-api-v1.json",
            _ => throw new InvalidDataException("COMFY_WORKFLOW_ID_FORBIDDEN"),
        };

        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(resourceName)
            ?? throw new InvalidDataException("COMFY_WORKFLOW_RESOURCE_MISSING");
        using var reader = new StreamReader(stream);
        var json = reader.ReadToEnd();
        ComfyWorkflowTemplateValidator.Validate(workflowId, json);
        return json;
    }
}
