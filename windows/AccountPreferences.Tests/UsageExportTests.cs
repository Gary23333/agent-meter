using AgentMeter.Windows;
using System.Text.Json;

internal static class UsageExportTests
{
    public static void Run()
    {
        using var sample = JsonDocument.Parse("""
        {"account":{"credential":"PRIVATE_SECRET"},"history":{
          "Codex":{"status":"partial","path":"PRIVATE_PATH","value":{"periods":{
            "today":{"totals":{"total_tokens":123,"fresh_input":120,"output":3}},
            "7d":{"totals":{"total_tokens":456,"output":-1}},"all":{"totals":{"total_tokens":0}}}}},
          "Claude Code":{"status":"error","value":{"periods":{"today":{"totals":{"total_tokens":999}}}}},
          "=PRIVATE_NAME":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":999}}}}}},
          "activity":{"sessions":[{"id":"PRIVATE_SESSION"}]}}
        """);
        var rows = UsageDataExport.Read(sample.RootElement);
        if (rows.Count != 3 || rows[0].Tokens["cache_read"] is not null || rows[1].Tokens["output"] is not null || rows[2].Tokens["total_tokens"] != 0 || rows.Any(row => row.Status != "partial"))
            throw new InvalidOperationException("导出必须保留部分状态、真实零值与未知值");
        string json = UsageDataExport.Json(sample.RootElement, true), csv = UsageDataExport.Csv(sample.RootElement, true);
        using var parsed = JsonDocument.Parse(json);
        if (!parsed.RootElement.GetProperty("demo").GetBoolean() || parsed.RootElement.GetProperty("rows").GetArrayLength() != 3 ||
            parsed.RootElement.GetProperty("rows")[0].GetProperty("tokens").GetProperty("cache_read").ValueKind != JsonValueKind.Null ||
            !csv.Contains("Codex\",today,partial,true,Asia/Shanghai,120,3") || json.Contains("PRIVATE") || csv.Contains("PRIVATE") || csv.Contains("999"))
            throw new InvalidOperationException("导出内容、演示标识或隐私过滤错误");
        using var empty = JsonDocument.Parse("{\"history\":{}}");
        try { UsageDataExport.Read(empty.RootElement); throw new InvalidOperationException("无汇总不应导出空文件"); }
        catch (InvalidDataException) { }
        Console.WriteLine("结构化本机汇总导出检查通过");
    }
}
