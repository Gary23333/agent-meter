using System.Globalization;
using System.Text.Json;

using static AgentMeter.Windows.UiScale;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    /// <summary>账户余额只来自用户授权的 Qoder 网站接口，与本机记录分开。</summary>
    void AddQoderAccount(JsonElement account)
    {
        string status = GetString(account, "status", "");
        if (status == "loading") { AddCard("Qoder CN · 账户额度", "正在读取", "账户查询进行中", null); return; }
        if (status is "unavailable" or "error") { AddCard("Qoder CN · 账户额度", "暂时无法获取", Reason(account), null); return; }
        if (status is not ("available" or "partial")) return;
        var rows = new List<QuotaRow>();
        var quotas = GetValue(GetValue(account, "quota"), "value");
        if (quotas.ValueKind == JsonValueKind.Array)
            foreach (var item in quotas.EnumerateArray().Take(20))
            {
                string label = GetString(item, "bucket", "") switch { "totalQuota" => "账户额度", "sharedQuota" => "共享额度", _ => "额度" };
                rows.Add(new QuotaRow(label, GetNumber(item, "remaining_percent"), QuotaResetClock.Read(item)));
            }
        var amounts = new List<AccountAmount>();
        var credits = GetValue(GetValue(account, "credits"), "value");
        if (credits.ValueKind == JsonValueKind.Array)
            foreach (var item in credits.EnumerateArray().Take(20))
            {
                string raw = GetString(item, "remaining", "");
                if (raw.Length > 40 || !decimal.TryParse(raw, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var n) || n < 0) continue;
                string label = GetString(item, "bucket", "") == "sharedQuota" ? "共享剩余" : "账户剩余";
                amounts.Add(new AccountAmount(label, n.ToString("0.########", CultureInfo.InvariantCulture) + " 积分"));
            }
        if (rows.Count > 0 || amounts.Count > 0)
            AddQuotaGroup("Qoder CN · 账户额度", rows, details: new AccountDetails(null, amounts, null), gaugeAccount: account);
        else AddCard("Qoder CN · 账户额度", "暂无额度数据", "服务未提供可用的账户额度", null);
    }

}
