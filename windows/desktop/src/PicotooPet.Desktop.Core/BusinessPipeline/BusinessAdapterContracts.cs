using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.BusinessPipeline;

/// <summary>First-party adapter 的唯一用户输入面；不包含模型、endpoint、workflow 或命令。</summary>
public sealed record BusinessAdapterBuildRequest(
    string SourcePath,
    string OutputDirectory,
    string ProjectKey,
    string Objective);

/// <summary>本地生成的严格 Work Package v1 与完整 ZIP 身份。</summary>
public sealed record BusinessAdapterBuildResult(
    string PackagePath,
    BusinessWorkPackageManifest Manifest,
    string SourceDigest,
    long SizeBytes);

/// <summary>可机器判定的 adapter 安全拒绝。</summary>
public sealed class BusinessAdapterException : Exception
{
    public BusinessAdapterException(string code)
        : base(code)
    {
        Code = code;
    }

    public string Code { get; }
}
