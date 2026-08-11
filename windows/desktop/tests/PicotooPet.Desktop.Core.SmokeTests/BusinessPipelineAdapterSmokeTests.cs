using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using PicotooPet.Desktop.Core.BusinessPipeline;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>锁定 Amazon/灵感 first-party adapter 的 Work Package v1 安全边界。</summary>
internal static class BusinessPipelineAdapterSmokeTests
{
    public static void Run()
    {
        var root = Path.Combine(Path.GetTempPath(), "picotoopet-adapter-smoke-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            VerifyAmazonCsv(root);
            VerifyInspirationJson(root);
            VerifyUnsupportedExtensionRejected(root);
            VerifyDirectoryPackagingDoesNotLeakSourcePaths(root);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static void VerifyAmazonCsv(string root)
    {
        var source = Path.Combine(root, "reviews.csv");
        File.WriteAllText(source, "review_id,rating,text\nr-1,5,quiet and fast\n");
        var output = Path.Combine(root, "amazon-out");
        var adapter = new AmazonReviewsAdapter();
        var result = adapter.BuildPackage(
            new BusinessAdapterBuildRequest(source, output, "pet-dryer-us", "Find supported customer problems."));

        Assert(File.Exists(result.PackagePath), "Amazon adapter 未生成 ZIP");
        Assert(result.Manifest.AnalysisProfile == "reviews.voice_of_customer.v1", "Amazon profile 漂移");
        Assert(result.Manifest.ProducerId == "picotoopet.amazon.reviews-adapter", "Amazon producer 漂移");
        Assert(result.Manifest.Inputs.Length == 1, "Amazon 单文件输入数量错误");
        Assert(result.Manifest.Inputs[0].Path.StartsWith("inputs/", StringComparison.Ordinal), "包内路径未受控");
        Assert(result.Manifest.Inputs[0].MediaType == "text/csv", "CSV media type 错误");
        VerifyPackage(result);
    }

    private static void VerifyInspirationJson(string root)
    {
        var source = Path.Combine(root, "ideas.json");
        File.WriteAllText(source, "[{\"idea\":\"quiet grooming demo\"}]");
        var output = Path.Combine(root, "ideas-out");
        var result = new InspirationIdeasAdapter().BuildPackage(
            new BusinessAdapterBuildRequest(source, output, "pet-dryer-us", "Find repeatable creative patterns."));
        Assert(result.Manifest.AnalysisProfile == "ideas.pattern_analysis.v1", "灵感 profile 漂移");
        Assert(result.Manifest.ProducerId == "picotoopet.inspiration.ideas-adapter", "灵感 producer 漂移");
        Assert(result.Manifest.Inputs[0].MediaType == "application/json", "JSON media type 错误");
        VerifyPackage(result);
    }

    private static void VerifyUnsupportedExtensionRejected(string root)
    {
        var source = Path.Combine(root, "payload.exe");
        File.WriteAllBytes(source, [0x4d, 0x5a]);
        var output = Path.Combine(root, "reject-out");
        try
        {
            _ = new AmazonReviewsAdapter().BuildPackage(
                new BusinessAdapterBuildRequest(source, output, "pet-dryer-us", "Reject executables."));
            throw new InvalidOperationException("Adapter 接受了可执行文件。");
        }
        catch (BusinessAdapterException exception) when (exception.Code == "unsupported_extension")
        {
            // expected
        }
    }

    private static void VerifyDirectoryPackagingDoesNotLeakSourcePaths(string root)
    {
        var sourceRoot = Path.Combine(root, "selected-directory");
        Directory.CreateDirectory(Path.Combine(sourceRoot, "nested"));
        File.WriteAllText(Path.Combine(sourceRoot, "reviews.jsonl"), "{\"review_id\":\"r-1\",\"text\":\"good\"}\n");
        File.WriteAllText(Path.Combine(sourceRoot, "nested", "more.txt"), "additional notes");
        var result = new AmazonReviewsAdapter().BuildPackage(
            new BusinessAdapterBuildRequest(sourceRoot, Path.Combine(root, "directory-out"), "pet-dryer-us", "Analyze reviews."));

        Assert(result.Manifest.Inputs.Length == 2, "目录输入没有完整打包");
        foreach (var input in result.Manifest.Inputs)
        {
            Assert(input.Path.StartsWith("inputs/", StringComparison.Ordinal), "目录输入未重写为受控路径");
            Assert(!input.Path.Contains("..", StringComparison.Ordinal), "包内路径存在 traversal");
            Assert(!input.Path.Contains(root, StringComparison.OrdinalIgnoreCase), "manifest 泄露本机绝对路径");
        }
        VerifyPackage(result);
    }

    private static void VerifyPackage(BusinessAdapterBuildResult result)
    {
        using var archive = ZipFile.OpenRead(result.PackagePath);
        var rootName = result.Manifest.PackageId;
        var manifestEntry = archive.GetEntry($"{rootName}/work-package.json")
            ?? throw new InvalidOperationException("Work Package manifest 缺失");
        using var manifestStream = manifestEntry.Open();
        var roundTrip = JsonSerializer.Deserialize<BusinessWorkPackageManifest>(manifestStream)
            ?? throw new InvalidOperationException("Work Package manifest 无法反序列化");
        Assert(roundTrip.PackageId == result.Manifest.PackageId, "manifest package id 漂移");
        foreach (var input in roundTrip.Inputs)
        {
            var entry = archive.GetEntry($"{rootName}/{input.Path}")
                ?? throw new InvalidOperationException("声明输入未进入 ZIP");
            using var stream = entry.Open();
            var digest = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
            Assert(digest == input.Sha256, "Work Package 输入 SHA 错误");
            Assert(entry.Length == input.SizeBytes, "Work Package 输入大小错误");
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
