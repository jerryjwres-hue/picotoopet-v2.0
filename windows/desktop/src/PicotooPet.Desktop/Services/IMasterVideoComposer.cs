namespace PicotooPet.Desktop.Services;

public sealed record MasterVideoCompositionRequest(
    VerifiedMasterVisual Visual,
    IReadOnlyList<VerifiedMasterNarrationSegment> NarrationSegments,
    long TargetRuntimeMs,
    string OutputPath);

/// <summary>
/// 冻结的 C009B 边界：所有路径与媒体事实均由 C009A 内部选择并验证，
/// 实现只能生成指定的临时输出，不能接受调用方媒体参数。
/// </summary>
public interface IMasterVideoComposer
{
    Task ComposeAsync(
        MasterVideoCompositionRequest request,
        CancellationToken cancellationToken);
}
