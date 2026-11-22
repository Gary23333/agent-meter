using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    void AddMiMoAccount(JsonElement account)
    {
        string state = GetString(account, "status", "disabled");
        if (state == "disabled") return;
        if (state == "loading") { AddCard("MIMO 平台", "正在读取账户", "通过应用内独立登录资料查询", null); return; }
        if (state is "available" or "partial")
        {
            var quota = GetValue(GetValue(account, "quota"), "value"); var rows = new List<QuotaRow>();
            if (quota.ValueKind == JsonValueKind.Array)
                foreach (var item in quota.EnumerateArray())
                    rows.Add(new QuotaRow("Token Plan · 月度额度", GetNumber(item, "remaining_percent"), QuotaResetClock.Read(item)));
            var details = AccountDetails.Read("MiMo", account);
            if (rows.Count > 0 || details.HasContent)
            {
                AddQuotaGroup("MIMO 平台", rows, details: details, gaugeAccount: account);
                if (state == "partial") AddCard("Token Plan", "部分数据暂不可用", "余额已读取，套餐额度请稍后刷新", null);
                return;
            }
        }
        string note = GetString(account, "reason", "") switch {
            "mimo_session_missing" => "请在托盘菜单登录小米 MiMo 平台",
            "mimo_runtime_missing" => "缺少 WebView2 Runtime，请安装后重试",
            "mimo_profile_unsafe" => "无法确认登录资料隔离，请检查 WebView2 系统策略",
            "mimo_not_authenticated" => "登录可能已过期，请重新登录",
            _ => "请检查登录状态和网络后刷新" };
        AddCard("MIMO 平台", "暂时无法获取账户", note, null);
    }
}
