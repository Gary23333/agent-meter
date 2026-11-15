using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    /// <summary>TRAE 账户权益与其他来源及本机账本分开显示。</summary>
    void AddTraeAccount(JsonElement account)
    {
        string status = GetString(account, "status", "");
        if (status == "loading") { AddCard("TRAE CN · 账户额度", "正在读取", "账户查询进行中", null); return; }
        if (status is "unavailable" or "error") { AddCard("TRAE CN · 账户额度", "暂时无法获取", Reason(account), null); return; }
        if (status is not ("available" or "partial")) return;
        var rows = new List<QuotaRow>();
        var quotas = GetValue(GetValue(account, "quota"), "value");
        if (quotas.ValueKind == JsonValueKind.Array)
            foreach (var item in quotas.EnumerateArray().Take(20))
                rows.Add(new QuotaRow("积分额度", GetNumber(item, "remaining_percent"), QuotaResetClock.Read(item)));
        var amounts = new List<AccountAmount>();
        var credits = GetValue(GetValue(account, "credits"), "value");
        string balance = GetString(credits, "balance", ""), total = GetString(credits, "total", "");
        if (balance.Length <= 40 && decimal.TryParse(balance, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var n) && n >= 0)
        {
            string? note = total.Length <= 40 && decimal.TryParse(total, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var t) && t >= 0
                ? "总额 " + t.ToString("0.########", CultureInfo.InvariantCulture) + " 积分" : null;
            amounts.Add(new AccountAmount("账户剩余", n.ToString("0.########", CultureInfo.InvariantCulture) + " 积分", note));
        }
        if (rows.Count > 0 || amounts.Count > 0)
            AddQuotaGroup("TRAE CN · 账户额度", rows, details: new AccountDetails(null, amounts, null));
        else AddCard("TRAE CN · 账户额度", "暂无额度数据", status == "partial" ? "部分额度未提供使用情况" : "服务未提供可用的账户额度", null);
    }
}
