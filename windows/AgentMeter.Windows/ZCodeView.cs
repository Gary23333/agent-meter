using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    void AddZCodeAccount(JsonElement account, JsonElement localHistory)
    {
        string state = GetString(account, "status", "disabled");
        if (state == "disabled") return;
        if (state == "loading") { AddCard("ZCODE", "正在读取账户", "使用主动提供的 Coding Plan 密钥", null); return; }
        if (state is "available" or "partial")
        {
            var quota = GetValue(GetValue(account, "quota"), "value");
            var rows = new List<QuotaRow>();
            if (quota.ValueKind == JsonValueKind.Array)
                foreach (var item in quota.EnumerateArray())
                {
                    var type = GetString(item, "limit_type", "");
                    string label = type switch { "TIME_LIMIT" => "MCP 调用额度", "TOKENS_LIMIT" => "Token 额度", "CREDIT_LIMIT" => "Coding Plan 额度", _ => "额度" };
                    double? minutes = GetNumber(item, "window_minutes");
                    if (minutes == 300) label += " · 5 小时";
                    else if (minutes == 10080) label += " · 7 天";
                    else if (minutes.HasValue && minutes > 0 && minutes <= 100000) label += $" · {minutes:0} 分钟";
                    rows.Add(new QuotaRow(label, GetNumber(item, "remaining_percent"), QuotaResetClock.Read(item)));
                }
            var details = AccountDetails.Read("ZCode", account);
            if (rows.Count > 0 || details.HasContent) { AddQuotaGroup("ZCODE", rows, localHistory, details, account); return; }
        }
        string note = GetString(account, "reason", "") switch {
            "zcode_credential_not_connected" => "请在托盘菜单设置 Coding Plan 密钥",
            "zcode_credential_invalid" => "密钥格式无效，请重新设置",
            "not_authenticated" => "密钥可能已失效，请重新设置",
            _ => "请检查网络、密钥和账户状态后刷新" };
        AddCard("ZCODE", "暂时无法获取额度", note, null);
    }
}
