using System.Globalization;
using System.Text;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>只导出本机自然周期汇总，不包含账户凭据、会话或项目内容。</summary>
internal static class CalendarReportExport
{
    public static string Create(JsonElement snapshot, bool demo = false)
    {
        var report = Field(snapshot, "calendar_report");
        var periods = Field(report, "periods");
        if (periods.ValueKind != JsonValueKind.Object) throw new InvalidDataException("没有可导出的报告");
        var output = new StringBuilder();
        output.AppendLine("# Agent Meter 本机用量报告").AppendLine();
        if (demo) output.AppendLine("此报告使用虚构演示数据，不代表真实用量。").AppendLine();
        output.AppendLine("统计时区：北京时间（Asia/Shanghai）。");
        output.AppendLine("本机账本相加，可能存在重叠；不等于账户总量或账单。").AppendLine();
        foreach (var (key, current, previous) in new[] { ("week", "本周", "上周"), ("month", "本月", "上月") })
        {
            var period = Field(periods, key);
            DateOnly currentStart = ReadDate(period, "current_start"), currentEnd = ReadDate(period, "current_end"),
                     previousStart = ReadDate(period, "previous_start");
            if (previousStart >= currentStart || currentEnd < currentStart) throw new InvalidDataException("报告日期不正确");
            long currentTokens = ReadTokens(period, "current_tokens"), previousTokens = ReadTokens(period, "previous_tokens");
            output.AppendLine($"## {current}与{previous}").AppendLine();
            static string FormatDate(DateOnly date) => date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
            output.AppendLine($"- {current}（{FormatDate(currentStart)} 至 {FormatDate(currentEnd)}，截至当前日期）：{currentTokens.ToString("N0", CultureInfo.InvariantCulture)} Token");
            output.AppendLine($"- {previous}（{FormatDate(previousStart)} 至 {FormatDate(currentStart.AddDays(-1))}，完整周期）：{previousTokens.ToString("N0", CultureInfo.InvariantCulture)} Token").AppendLine();
            if (ReportComparison.Read(period) is { } comparable)
                output.AppendLine($"已结束的前 {comparable.Days} 个自然日：{current} {comparable.Current.ToString("N0", CultureInfo.InvariantCulture)} Token；{previous} {comparable.Previous.ToString("N0", CultureInfo.InvariantCulture)} Token；变化 {comparable.Change}。当前日期未计入。").AppendLine();
        }
        if (Field(report, "incomplete").ValueKind == JsonValueKind.True)
            output.AppendLine("部分来源或逐日记录不完整，汇总可能偏低。").AppendLine();
        output.AppendLine("当前周期尚未结束，不能直接与完整上期作等长比较。");
        return output.ToString();
    }
    static JsonElement Field(JsonElement element, string key) => element.ValueKind == JsonValueKind.Object && element.TryGetProperty(key, out var value) ? value : default;
    static DateOnly ReadDate(JsonElement period, string key)
    {
        var value = Field(period, key);
        if (value.ValueKind != JsonValueKind.String || !DateOnly.TryParseExact(value.GetString(), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date))
            throw new InvalidDataException("报告日期不正确");
        return date;
    }
    static long ReadTokens(JsonElement period, string key)
    {
        var value = Field(period, key);
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt64(out long count) || count < 0)
            throw new InvalidDataException("报告用量不正确");
        return count;
    }
}
