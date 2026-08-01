namespace PicotooPet.Desktop.Core.Networking;

/// <summary>保留服务端错误码、Trace ID 和重试语义的 API 异常。</summary>
public sealed class ApiException : Exception
{
    /// <summary>初始化统一 API 异常。</summary>
    public ApiException(
        string code,
        string message,
        bool retryable,
        string? traceId,
        int statusCode,
        Exception? innerException = null)
        : base(message, innerException)
    {
        Code       = code;
        Retryable  = retryable;
        TraceId    = traceId;
        StatusCode = statusCode;
    }

    public string Code { get; }
    public bool Retryable { get; }
    public string? TraceId { get; }
    public int StatusCode { get; }
}
