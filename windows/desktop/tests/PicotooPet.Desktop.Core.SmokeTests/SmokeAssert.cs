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

    /// <summary>两个确定性值不相等时抛出带业务语义的异常。</summary>
    public static void Equal<T>(T expected, T actual, string message)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
        {
            throw new InvalidOperationException($"{message}；expected={expected} actual={actual}");
        }
    }
}
