namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>零第三方依赖的确定性 smoke 断言。</summary>
internal static class SmokeAssert
{
    /// <summary>条件不成立时抛出带业务语义的异常。</summary>
    public static void True(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
