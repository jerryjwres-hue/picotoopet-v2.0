using System.Collections.Concurrent;
using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using System.Threading.Channels;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结冷启动历史重放和正常业务入站都不得误触发 Pong 超时。</summary>
internal static class EventStreamColdStartSmokeTests
{
    /// <summary>验证事件积压/业务入站可证明链路存活，同时持续无入站仍会触发真实超时。</summary>
    public static async Task RunAsync()
    {
        await using var client = new EventStreamClient(
            new Uri("http://127.0.0.1:8766/"),
            "fixture-token-0123456789",
            channelCapacity: 16,
            pongTimeout: TimeSpan.FromMilliseconds(50),
            pingInterval: TimeSpan.FromMilliseconds(10));

        var channel = ReadPrivateField<Channel<EventEnvelope>>(client, "_channel");
        var pending = ReadPrivateField<ConcurrentDictionary<string, long>>(
            client,
            "_pendingPings");
        var timeoutCheck = typeof(EventStreamClient).GetMethod(
            "ThrowIfPongExpired",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("缺少 EventStreamClient Pong 超时检查入口。");
        var recordInbound = typeof(EventStreamClient).GetMethod(
            "RecordInboundActivity",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("缺少 EventStreamClient 入站存活记录入口。");

        await channel.Writer.WriteAsync(CreateEvent(sequence: 1)).ConfigureAwait(false);
        pending["cold-start-replay"] = 0;
        InvokeWithoutTimeout(
            timeoutCheck,
            client,
            "冷启动历史事件仍在有界队列中时，不得把排在事件后的 Pong 误判为超时。");

        SmokeAssert.True(channel.Reader.TryRead(out _), "未能清空冷启动事件积压夹具");

        // A valid business message is stronger liveness evidence than one delayed application-level Pong.
        pending["delayed-pong-with-business-traffic"] = 0;
        recordInbound.Invoke(client, parameters: null);
        InvokeWithoutTimeout(
            timeoutCheck,
            client,
            "收到有效业务消息后不得因之前的延迟 Pong 误判断线。");
        SmokeAssert.True(
            pending.IsEmpty,
            "收到有效入站业务消息后应清除已失效的 Ping 延迟样本");

        pending["real-timeout"] = 0;
        SmokeAssert.True(
            InvokeExpectingTimeout(timeoutCheck, client),
            "持续无入站时必须继续检测真实 Pong 超时");
    }

    private static EventEnvelope CreateEvent(long sequence) => new(
        "2.3.0",
        sequence,
        $"event-{sequence}",
        "task.updated",
        "trace-cold-start",
        DateTimeOffset.UtcNow,
        JsonSerializer.SerializeToElement(new { }));

    private static T ReadPrivateField<T>(object instance, string name)
        where T : class
    {
        var field = instance.GetType().GetField(
            name,
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException($"缺少私有字段：{name}");
        return field.GetValue(instance) as T
            ?? throw new InvalidOperationException($"私有字段类型错误：{name}");
    }

    private static void InvokeWithoutTimeout(
        MethodInfo method,
        object instance,
        string failureMessage)
    {
        try
        {
            method.Invoke(instance, parameters: null);
        }
        catch (TargetInvocationException exception)
            when (exception.InnerException is TimeoutException)
        {
            throw new InvalidOperationException(failureMessage, exception.InnerException);
        }
    }

    private static bool InvokeExpectingTimeout(MethodInfo method, object instance)
    {
        try
        {
            method.Invoke(instance, parameters: null);
            return false;
        }
        catch (TargetInvocationException exception)
            when (exception.InnerException is TimeoutException)
        {
            return true;
        }
    }
}
