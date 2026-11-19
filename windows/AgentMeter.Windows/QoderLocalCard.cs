using System.Globalization;
using System.Text.Json;

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
            AddQuotaGroup("Qoder CN · 账户额度", rows, details: new AccountDetails(null, amounts, null));
        else AddCard("Qoder CN · 账户额度", "暂无额度数据", "服务未提供可用的账户额度", null);
    }

    /// <summary>Qoder 本机积分只表示本地日志消耗，不能冒充账户余额。</summary>
    void AddQoderLocalCredits(JsonElement localCredits)
    {
        var source = GetValue(localCredits, "Qoder CN");
        string status = GetString(source, "status", "");
        if (status is not ("available" or "partial")) return;
        var periods = GetValue(GetValue(source, "value"), "periods");
        string? Read(string period, string key)
        {
            var totals = GetValue(GetValue(periods, period), "totals");
            string raw = GetString(totals, key, "");
            return raw.Length <= 40 && decimal.TryParse(raw, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var n) && n >= 0
                ? n.ToString("0.########", CultureInfo.InvariantCulture) : null;
        }
        string? today = Read("today", "credits"), month = Read("30d", "credits"), all = Read("all", "credits");
        if (today is null && month is null && all is null) return;
        var identity = ProviderStyle.For("Qoder CN");
        var box = new RoundedCard(theme, identity.Color) { Name = "qoder-local-credits", Height = 181,
            Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        var heading = new Label { Text = identity.DisplayName, AutoEllipsis = true, Height = 25,
            Font = new Font(Font.FontFamily, 11F, FontStyle.Bold), ForeColor = Primary, Location = new Point(60, 14) };
        var caption = new Label { Text = "本机积分消耗 · 非账户余额", AutoEllipsis = true, Height = 21,
            Font = new Font(Font.FontFamily, 8.5F), ForeColor = Muted, Location = new Point(60, 39) };
        var todayLabel = new Label { Text = "今日 " + (today ?? "—"), AutoEllipsis = true, Height = 22,
            Font = new Font(Font.FontFamily, 10F, FontStyle.Bold), ForeColor = Primary, Location = new Point(16, 79) };
        var monthLabel = new Label { Text = "近 30 天 " + (month ?? "—") + "  ·  累计 " + (all ?? "—"), AutoEllipsis = true,
            Height = 22, ForeColor = Primary, Location = new Point(16, 111) };
        var note = new Label { Text = status == "partial" ? "部分本机记录未读取" : "仅统计此设备的本地记录",
            AutoEllipsis = true, Height = 20, Font = new Font(Font.FontFamily, 8F), ForeColor = Muted, Location = new Point(16, 145) };
        box.Controls.AddRange([new ProviderMark(identity) { Location = new Point(16, 13), Size = new Size(34, 34) }, heading, caption, todayLabel, monthLabel, note]);
        box.Resize += (_, _) =>
        {
            heading.Width = caption.Width = Math.Max(0, box.ClientSize.Width - 76);
            todayLabel.Width = monthLabel.Width = note.Width = Math.Max(0, box.ClientSize.Width - 32);
        };
        StyleCard(box); content.Controls.Add(box);
    }
}
