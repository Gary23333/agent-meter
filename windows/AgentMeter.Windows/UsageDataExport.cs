using System.Globalization;
using System.Text;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>从本机账本显式投影汇总数字，绝不复制原始快照、路径、会话或账户信息。</summary>
internal static class UsageDataExport
{
    static readonly string[] Sources = ["Codex", "Claude Code", "Gemini CLI", "WorkBuddy", "ZCode", "DeepSeek Harness",
        "Kimi Code", "Kimi CLI (旧版)", "OpenCode", "MiniMax Code", "MiMo Code", "DevECo"];
    static readonly string[] Periods = ["today", "7d", "30d", "all"];
    static readonly string[] Metrics = ["fresh_input", "output", "reasoning", "cache_read", "cache_write", "unclassified", "total_tokens"];
    internal sealed record Row(string Source, string Period, string Status, Dictionary<string, long?> Tokens);
    static JsonElement Field(JsonElement e, string key) => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(key, out var value) ? value : default;
    static string Text(JsonElement e, string key) => Field(e, key).ValueKind == JsonValueKind.String ? Field(e, key).GetString() ?? "" : "";
    static long? Number(JsonElement e, string key)
    {
        var v = Field(e, key);
        return v.ValueKind == JsonValueKind.Number && v.TryGetInt64(out long n) && n >= 0 ? n : null;
    }
    public static IReadOnlyList<Row> Read(JsonElement snapshot)
    {
        var history = Field(snapshot, "history");
        var rows = new List<Row>();
        foreach (string source in Sources)
        {
            var item = Field(history, source);
            string status = Text(item, "status");
            if (status is not ("available" or "partial")) continue;
            var periods = Field(Field(item, "value"), "periods");
            foreach (string period in Periods)
            {
                var totals = Field(Field(periods, period), "totals");
                var tokens = Metrics.ToDictionary(metric => metric, metric => Number(totals, metric));
                if (tokens.Values.Any(value => value.HasValue)) rows.Add(new Row(source, period, status, tokens));
            }
        }
        if (rows.Count == 0) throw new InvalidDataException("没有可导出的本机 Token 汇总");
        return rows;
    }
    public static string Json(JsonElement snapshot, bool demo)
    {
        var payload = new { schema_version = 1, demo, timezone = "Asia/Shanghai", scope = "local_device",
            note = "不同账本可能重叠；未知数值为 null；不等于账户总量或账单。", rows = Read(snapshot) };
        return JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower });
    }
    public static string Csv(JsonElement snapshot, bool demo)
    {
        var output = new StringBuilder();
        output.AppendLine("source,period,status,demo,timezone,fresh_input,output,reasoning,cache_read,cache_write,unclassified,total_tokens");
        foreach (var row in Read(snapshot))
        {
            // 名称取固定清单，仍使用 CSV 双引号转义，避免受系统地区设置影响。
            output.Append('"').Append(row.Source.Replace("\"", "\"\"")).Append("\",").Append(row.Period).Append(',')
                .Append(row.Status).Append(',').Append(demo ? "true" : "false").Append(",Asia/Shanghai");
            foreach (string key in Metrics) output.Append(',').Append(row.Tokens[key]?.ToString(CultureInfo.InvariantCulture) ?? "");
            output.AppendLine();
        }
        return output.ToString();
    }
}
