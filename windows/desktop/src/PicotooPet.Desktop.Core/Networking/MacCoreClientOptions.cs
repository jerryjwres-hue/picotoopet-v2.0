namespace PicotooPet.Desktop.Core.Networking;

/// <summary>Mac Core REST 客户端固定参数。</summary>
public sealed record MacCoreClientOptions(
    Uri BaseUri,
    string Token,
    TimeSpan RequestTimeout,
    TimeSpan ConnectTimeout,
    TimeSpan PooledConnectionLifetime)
{
    /// <summary>创建适合局域网控制面的默认参数。</summary>
    public static MacCoreClientOptions CreateDefault(Uri baseUri, string token) => new(
        BaseUri: baseUri,
        Token: token,
        RequestTimeout: TimeSpan.FromSeconds(10),
        ConnectTimeout: TimeSpan.FromSeconds(5),
        PooledConnectionLifetime: TimeSpan.FromMinutes(5));
}
