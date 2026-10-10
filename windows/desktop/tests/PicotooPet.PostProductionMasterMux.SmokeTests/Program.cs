namespace PicotooPet.PostProductionMasterMux.SmokeTests;

/// <summary>C009B 独立 smoke 入口；真实 Windows 验收缺环境时报告 UNVERIFIED，绝不伪造 PASS。</summary>
internal static class Program
{
    [STAThread]
    private static async Task<int> Main()
    {
        try
        {
            await UnitTests.RunAsync().ConfigureAwait(false);
            Console.WriteLine("MASTER_MUX_UNIT=PASS");
            var real = await RealWindowsAcceptance.RunAsync().ConfigureAwait(false);
            Console.WriteLine("MASTER_MUX_REAL_WINDOWS=" + real);
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine("MASTER_MUX_SMOKE=FAIL " + exception.GetType().Name + ": " + exception.Message);
            return 1;
        }
    }
}

internal static class Check
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

    public static async Task<MasterVideoComposerExceptionInfo> ThrowsAsync(Func<Task> action, string code, string message)
    {
        try
        {
            await action().ConfigureAwait(false);
        }
        catch (PicotooPet.Desktop.Services.MasterVideoComposerException exception)
        {
            Equal(code, exception.Code, message);
            return new MasterVideoComposerExceptionInfo(exception.Message);
        }
        throw new InvalidOperationException($"{message}（未抛出）");
    }
}

internal sealed record MasterVideoComposerExceptionInfo(string Message);
