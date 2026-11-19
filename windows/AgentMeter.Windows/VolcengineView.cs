using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    void AddVolcengineAccount(JsonElement account)
    {
        string state = GetString(account, "status", "disabled");
        if (state == "disabled") return;
        if (state == "loading") { AddCard("火山方舟", "正在读取账户", "使用主动提供的 AccessKey 对", null); return; }
        if (state is "available" or "partial")
        {
            var quota = GetValue(GetValue(account, "quota"), "value");
            var rows = new List<QuotaRow>();
            if (quota.ValueKind == JsonValueKind.Array)
                foreach (var item in quota.EnumerateArray())
                {
                    double? minutes = GetNumber(item, "window_minutes");
                    string label = minutes switch { 300 => "5 小时", 10080 => "7 天", 43200 => "月度额度", _ => "Coding Plan 额度" };
                    rows.Add(new QuotaRow(label, GetNumber(item, "remaining_percent"), QuotaResetClock.Read(item)));
                }
            var details = AccountDetails.Read("Volcengine", account);
            if (rows.Count > 0 || details.HasContent) { AddQuotaGroup("火山方舟", rows, details: details); return; }
        }
        string note = GetString(account, "reason", "") switch {
            "volcengine_credential_not_connected" => "请在托盘菜单设置 AccessKey 对",
            "volcengine_credential_invalid" or "volcengine_ark_key_not_supported" => "请使用访问控制的 AccessKey 对，不是模型 API 密钥",
            "not_authenticated" => "凭据或权限不可用，请检查后重试",
            "volcengine_no_coding_plan" => "账户未提供 Coding Plan 额度",
            _ => "请检查网络、凭据和账户状态后刷新" };
        AddCard("火山方舟", "暂时无法获取额度", note, null);
    }
}
