// 独立入口链接原始 upstream tests；不修改任何 C008/C009 所有者文件。
namespace PicotooPet.FinalVideoQa.UpstreamRegression
{
    internal static class Program
    {
        [STAThread]
        private static async Task Main(string[] args)
        {
            if (!args.Contains("--c008-only", StringComparer.Ordinal))
            {
                await PicotooPet.PostProductionMasterMux.SmokeTests.UnitTests.RunAsync();
                Console.WriteLine("LINKED_C009B_UNIT=PASS");
            }
            await PicotooPet.CaptionOverlay.SmokeTests.ContractAndClientTests.RunAsync();
            PicotooPet.CaptionOverlay.SmokeTests.FontPolicyTests.Run();
            await PicotooPet.CaptionOverlay.SmokeTests.RendererAndArtifactTests.RunAsync();
            await PicotooPet.CaptionOverlay.SmokeTests.RealFfmpegTests.RunAsync();
            Console.WriteLine("LINKED_C008B_SMOKE=PASS");
        }
    }
}
namespace PicotooPet.PostProductionMasterMux.SmokeTests
{
    internal static class Check
    {
        public static void True(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
        public static void Equal<T>(T expected, T actual, string message)
        { if (!EqualityComparer<T>.Default.Equals(expected, actual)) throw new InvalidOperationException(message); }
        public static async Task<MasterVideoComposerExceptionInfo> ThrowsAsync(Func<Task> action, string code, string message)
        {
            try { await action(); }
            catch (PicotooPet.Desktop.Services.MasterVideoComposerException e)
            { Equal(code, e.Code, message); return new(e.Message); }
            throw new InvalidOperationException(message);
        }
    }
    internal sealed record MasterVideoComposerExceptionInfo(string Message);
}
