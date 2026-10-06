using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 Web GPT 返回的有界传输语法；语义校验仍只属于 Mac Core。</summary>
internal static class GoalVideoReturnParserSmokeTests
{
    public static void Run()
    {
        AssertParsed("{\"goal_id\":\"goal-1\"}", "goal-1");
        AssertParsed(
            "Web GPT response\nPICOTOO_RETURN_JSON\n{\"goal_id\":\"goal-2\"}",
            "goal-2");
        AssertParsed(
            "PICOTOO_RETURN_JSON\n```json\n{\"goal_id\":\"goal-3\"}\n```",
            "goal-3");

        AssertRejected(
            "PICOTOO_RETURN_JSON\n{}\nPICOTOO_RETURN_JSON\n{}",
            "重复 marker 必须拒绝");
        AssertRejected("{broken", "畸形 JSON 必须拒绝");
        AssertRejected("[1,2,3]", "非对象根必须拒绝");
        AssertRejected(
            "{\"value\":\"" + new string('界', 180_000) + "\"}",
            "超过 512 KiB 的 UTF-8 输入必须拒绝");

        const string exact = "{\"text\":\"保留 大小写\\n与空格\",\"number\":1.2300,\"flag\":true}";
        var preserved = GoalVideoReturnParser.Parse(exact);
        SmokeAssert.Equal(
            "保留 大小写\n与空格",
            preserved.GetProperty("text").GetString(),
            "字符串值被解析器改写");
        SmokeAssert.Equal(
            "1.2300",
            preserved.GetProperty("number").GetRawText(),
            "数值表示被解析器改写");
        SmokeAssert.True(preserved.GetProperty("flag").GetBoolean(), "布尔值被解析器改写");
    }

    private static void AssertParsed(string text, string goalId)
    {
        var parsed = GoalVideoReturnParser.Parse(text);
        SmokeAssert.Equal(JsonValueKind.Object, parsed.ValueKind, "返回根不是 JSON 对象");
        SmokeAssert.Equal(goalId, parsed.GetProperty("goal_id").GetString(), "goal_id 未保留");
    }

    private static void AssertRejected(string text, string message)
    {
        try
        {
            _ = GoalVideoReturnParser.Parse(text);
            throw new InvalidOperationException(message);
        }
        catch (GoalVideoReturnParseException)
        {
        }
    }
}
