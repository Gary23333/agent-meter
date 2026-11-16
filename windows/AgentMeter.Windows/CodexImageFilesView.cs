using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    /// <summary>只展示本机目录里的 PNG 文件数量，不推断实际生图调用。</summary>
    void AddCodexImageFiles(JsonElement image)
    {
        string status = GetString(image, "status", "");
        if (status is not ("available" or "partial")) return;
        var periods = GetValue(GetValue(image, "value"), "periods");
        var selected = GetNumber(GetValue(periods, usagePeriod), "files");
        var all = GetNumber(GetValue(periods, "all"), "files");
        if (!selected.HasValue || !all.HasValue || selected < 0 || all < 0 || selected > all || all > 50000) return;
        string note = status == "partial" ? "部分文件未统计 · 按文件修改时间" : "按文件修改时间 · 不等于生成调用次数";
        AddCard("Codex 生图 · 本机 PNG 文件", $"{selected:0} 个 · {UsagePeriodLabel}", note, null,
                $"累计 {all:0} 个文件 · 不读取图片内容");
    }
}
