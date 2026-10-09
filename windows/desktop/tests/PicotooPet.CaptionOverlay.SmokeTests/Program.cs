using PicotooPet.CaptionOverlay.SmokeTests;

namespace PicotooPet.CaptionOverlay.SmokeTests;

/// <summary>C008B 独立 smoke 入口；任何断言失败返回非零退出码。</summary>
internal static class Program
{
    [STAThread]
    private static async Task<int> Main()
    {
        try
        {
            await ContractAndClientTests.RunAsync().ConfigureAwait(false);
            Console.WriteLine("CAPTION_OVERLAY_CONTRACT_CLIENT=PASS");
            FontPolicyTests.Run();
            Console.WriteLine("CAPTION_OVERLAY_FONT_POLICY=PASS");
            await RendererAndArtifactTests.RunAsync().ConfigureAwait(false);
            Console.WriteLine("CAPTION_OVERLAY_RENDERER_ARTIFACT=PASS");
            await RealFfmpegTests.RunAsync().ConfigureAwait(false);
            Console.WriteLine("CAPTION_OVERLAY_SMOKE=PASS");
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine("CAPTION_OVERLAY_SMOKE=FAIL " + exception.GetType().Name + ": " + exception.Message);
            return 1;
        }
    }
}

internal static class SmokeAssert
{
    public static void True(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    public static void Equal<T>(T expected, T actual, string message)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
        {
            throw new InvalidOperationException($"{message}；expected={expected} actual={actual}");
        }
    }

    public static async Task<TextOverlayFailure> ThrowsCodeAsync(Func<Task> action, string code, string message)
    {
        try
        {
            await action().ConfigureAwait(false);
        }
        catch (PicotooPet.Desktop.Core.Contracts.TextOverlayException exception)
        {
            Equal(code, exception.Code, message);
            return new TextOverlayFailure(exception.Message);
        }
        throw new InvalidOperationException($"{message}（未抛出）");
    }
}

internal sealed record TextOverlayFailure(string Message);
