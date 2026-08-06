using System.Collections.Concurrent;
using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using System.Threading.Channels;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结冷启动历史事件重放不得误触发 Pong 超时。</summary>
internal static class EventStreamColdStartSmokeTests
{
    /// <summary>验证事件积压时延后心跳判定，积压清空后仍保留真实超时。</summary>
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

        await channel.Writer.WriteAsync(CreateEvent(sequence: 1)).ConfigureAwait(false);
        pending["cold-start-replay"] = 0;
        InvokeWithoutTimeout(
            timeoutCheck,
            client,
            "冷启动历史事件仍在有界队列中时，不得把排在事件后的 Pong 误判为超时。");

        SmokeAssert.True(channel.Reader.TryRead(out _), "未能清空冷启动事件积压夹具");
        pending["real-timeout"] = 0;
        SmokeAssert.True(
            InvokeExpectingTimeout(timeoutCheck, client),
            "事件积压清空后必须继续检测真实 Pong 超时");
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
