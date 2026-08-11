using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证正式发布程序集内置的 Wan2.2 workflow 资源与静态安全边界。</summary>
internal static class ComfyWorkflowTemplateSmokeTests
{
    public static void Run()
    {
        var t2v = ComfyWorkflowCatalog.Load(ComfyWorkflowTemplateValidator.T2VWorkflowId);
        var i2v = ComfyWorkflowCatalog.Load(ComfyWorkflowTemplateValidator.I2VWorkflowId);

        Assert(t2v.Contains("Wan22ImageToVideoLatent", StringComparison.Ordinal), "T2V 模板缺失 Wan22 latent node");
        Assert(!t2v.Contains("LoadImage", StringComparison.Ordinal), "T2V 模板不允许 LoadImage");
        Assert(i2v.Contains("LoadImage", StringComparison.Ordinal), "I2V 模板缺失 LoadImage");
        Assert(i2v.Contains(ComfyWorkflowTemplateValidator.TrustedInputPlaceholder, StringComparison.Ordinal), "I2V 模板缺失受控输入槽位");

        var badModel = t2v.Replace(
            "wan2.2_ti2v_5B_fp16.safetensors",
            "untrusted-model.safetensors",
            StringComparison.Ordinal);
        ExpectInvalid(
            () => ComfyWorkflowTemplateValidator.Validate(ComfyWorkflowTemplateValidator.T2VWorkflowId, badModel),
            "模型替换必须被拒绝");

        var badClass = t2v.Replace("SaveWEBM", "CloudVideoProvider", StringComparison.Ordinal);
        ExpectInvalid(
            () => ComfyWorkflowTemplateValidator.Validate(ComfyWorkflowTemplateValidator.T2VWorkflowId, badClass),
            "Cloud/Provider node 必须被拒绝");
    }

    private static void ExpectInvalid(Action action, string message)
    {
        try
        {
            action();
        }
        catch (InvalidDataException)
        {
            return;
        }
        throw new InvalidOperationException(message);
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
