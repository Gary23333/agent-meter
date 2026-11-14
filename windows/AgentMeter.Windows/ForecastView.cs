using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    readonly System.Windows.Forms.Timer forecastClock = new();
    readonly List<(Label Label, ForecastWindow Window)> forecastClocks = [];
    readonly List<(Label Label, long? Epoch)> quotaResetLabels = [];
    long lastQuotaClockMinute = -1;
    bool allForecastHistory;
    static readonly DateTimeOffset ForecastDemoNow = new(2026, 11, 14, 15, 0, 0, TimeSpan.FromHours(8));
    DateTimeOffset ForecastNow => demo ? ForecastDemoNow : DateTimeOffset.UtcNow;

    void UpdateForecastClocks()
    {
        if (!Visible) return;
        if (view == View.Accounts)
        {
            long minute = ForecastNow.ToUnixTimeSeconds() / 60;
            if (lastQuotaClockMinute != minute)
            {
                lastQuotaClockMinute = minute;
                foreach (var (label, epoch) in quotaResetLabels)
                    if (!label.IsDisposed) label.Text = QuotaResetClock.Detail(epoch, ForecastNow);
                foreach (Control gauge in gauges.Controls) gauge.Invalidate();
                foreach (var update in accountClockUpdates) update(ForecastNow);
            }
        }
        if (view != View.Forecast) return;
        foreach (var (label, window) in forecastClocks)
            if (!label.IsDisposed) label.Text = window.Countdown(ForecastNow);
    }
    Label ForecastLabel(RoundedCard card, string text, int top, float size = 10, bool strong = false, Color? color = null)
    {
        var label = new Label { Text = text, AutoEllipsis = true, Location = new Point(16, top), Height = (int)(size * 2.3),
            ForeColor = color ?? Muted, Font = new Font(Font.FontFamily, size, strong ? FontStyle.Bold : FontStyle.Regular), BackColor = Color.Transparent };
        card.Controls.Add(label);
        card.Resize += (_, _) => label.Width = Math.Max(0, card.ClientSize.Width - 32);
        return label;
    }
    RoundedCard ForecastCard(int height)
    {
        var card = new RoundedCard(theme) { Height = height, Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        content.Controls.Add(card);
        return card;
    }
    void AddForecast(JsonElement forecast)
    {
        AddHeading("全局重置预测", "第三方独立统计 · 与个人额度周期无关");
        string state = GetString(forecast, "status", "disabled");
        if (state is "disabled" or "loading" or "error" or "unavailable")
        {
            var empty = ForecastCard(142);
            ForecastLabel(empty, "CODEX · 第三方预测", 14, strong: true);
            ForecastLabel(empty, state switch { "disabled" => "预测尚未开启", "loading" => "正在读取公开预测", _ => "暂时无法获取预测" }, 44, 17, true, Primary);
            ForecastLabel(empty, state == "disabled" ? "从托盘菜单开启第三方重置预测（联网）" : "不读取账户凭据或本机会话", 91, 9);
            ForecastLabel(empty, "WillReset · Tibo Radar · Reset Monitor", 116, 9);
            return;
        }
        var hero = ForecastCard(246);
        ForecastLabel(hero, "CODEX · 综合预测", 14, 10, true, Accent);
        var combined = GetValue(forecast, "ensemble");
        foreach (var (horizon, caption, index) in new[] { ("24h", "未来 24 小时", 0), ("48h", "未来 48 小时", 1) })
        {
            var range = ForecastRange.Read(GetValue(combined, horizon));
            var column = new Panel { Top = 46, Height = 135, BackColor = Color.Transparent };
            var title = new Label { Text = caption, Top = 0, Height = 22, Dock = DockStyle.None, ForeColor = Muted, BackColor = Color.Transparent };
            var amount = new Label { Text = range is null ? "—" : $"{range.Median:0.#}%", Top = 23, Height = 48,
                Font = new Font(Font.FontFamily, 27, FontStyle.Bold), ForeColor = Primary, BackColor = Color.Transparent };
            var note = new Label { Text = range is null ? "无可合并的来源" : $"{range.Sources} 站 · {range.Minimum:0.#}–{range.Maximum:0.#}%", Top = 95,
                Height = 24, ForeColor = Muted, BackColor = Color.Transparent, AutoEllipsis = true };
            column.Controls.AddRange([title, amount, note]);
            if (range is not null)
            {
                var band = new ForecastBand(theme, range) { Top = 75, Height = 14, BackColor = Card,
                    AccessibleName = $"{caption}加权中位数 {range.Median}%，站点范围 {range.Minimum}% 至 {range.Maximum}%" };
                column.Controls.Add(band);
                column.Resize += (_, _) => band.Width = column.Width - 8;
            }
            column.Resize += (_, _) => title.Width = amount.Width = note.Width = column.Width;
            hero.Controls.Add(column);
            hero.Resize += (_, _) => { column.Width = (hero.Width - 48) / 2; column.Left = 16 + index * (column.Width + 16); };
        }
        bool model = new[] { "24h", "48h" }.Any(key => ForecastRange.Read(GetValue(combined, key))?.HasModel == true);
        ForecastLabel(hero, model ? "加权中位数 · 含站点模型推算" : "加权中位数 · 采用站点公布值", 181, 9);
        ForecastLabel(hero, "色带为站点数值范围，不是置信区间", 205, 9);
        string cache = GetString(forecast, "cache_state", "");
        if (cache == "stale" || state is "partial" or "stale")
        {
            var note = ForecastCard(59);
            ForecastLabel(note, cache == "stale" ? "最新查询失败 · 正在展示旧缓存" : "部分来源不可用 · 仅合并有效数据", 9, 9, true, Accent);
            ForecastLabel(note, "超过 48 小时的来源不参加综合预测", 32, 9);
        }

        AddHeading("时间窗口", "仅对站点给出的明确时间计时");
        var targets = GetValue(forecast, "targets");
        var clocks = targets.ValueKind == JsonValueKind.Array ? targets.EnumerateArray().Select(ForecastWindow.Read).OfType<ForecastWindow>().Take(6).ToArray() : [];
        if (clocks.Length == 0)
        {
            var empty = ForecastCard(78);
            ForecastLabel(empty, "没有明确时间 · 不生成倒计时", 13, 11, true, Primary);
            ForecastLabel(empty, "概率、文字承诺和个人周期均不替代具体时间", 46, 9);
        }
        foreach (var window in clocks)
        {
            var card = ForecastCard(154);
            ForecastLabel(card, window.Typical ? "公告常见时段 · 统计规律" : "站点转述的重置时间", 13, 10, true, Accent);
            var clock = ForecastLabel(card, window.Countdown(ForecastNow), 42, 16, true, Primary);
            forecastClocks.Add((clock, window));
            string time = window.Open.HasValue ? window.Open.Value.LocalDateTime.ToString("MM-dd HH:mm") + " — " : "";
            ForecastLabel(card, time + window.Close.LocalDateTime.ToString("MM-dd HH:mm") + " · 本地时间", 85, 9);
            ForecastLabel(card, window.Sources, 108, 9);
            ForecastLabel(card, window.Typical ? "常见公告时段不代表届时一定重置" : "到点后仍需确认是否实际发生", 130, 9);
        }

        AddHeading("来源对照", "各站独立发布 · 不可用不记作 0%");
        var rows = GetValue(forecast, "sources");
        if (rows.ValueKind == JsonValueKind.Array)
            foreach (var row in rows.EnumerateArray().Take(3))
            {
                var card = ForecastCard(133);
                ForecastLabel(card, GetString(row, "name", "第三方"), 13, 11, true, Primary);
                bool available = GetString(row, "status", "") is "available" or "stale";
                string Value(string key) {
                    var value = GetNumber(row, key);
                    return !available || value is null || value < 0 || value > 100 ? "未提供" : $"{value:0.#}% · " +
                        (GetString(row, key + "_basis", "") == "cadence_model_fallback" ? "模型值" : "公布值");
                }
                ForecastLabel(card, available ? "24 小时   " + Value("24h") : "暂时不可用", 45, 10, color: available ? Accent : Muted);
                ForecastLabel(card, available ? "48 小时   " + Value("48h") : "此来源未返回可用预测", 72, 10);
                var updated = ForecastPresentation.Stamp(row, "updated_at");
                ForecastLabel(card, updated is null ? "站点未提供更新时间" : "更新 " + updated.Value.LocalDateTime.ToString("MM-dd HH:mm") +
                    (ForecastNow - updated.Value > TimeSpan.FromHours(48) ? " · 已过时" : " · 本地时间"), 105, 9);
            }

        AddHeading("历史事件", "第三方记录 · 公告与实际生效分别展示");
        var history = GetValue(forecast, "history");
        var events = history.ValueKind == JsonValueKind.Array ? history.EnumerateArray().Where(row => ForecastPresentation.Stamp(row, "announced_at") is not null).Take(40).ToArray() : [];
        if (events.Length == 0)
        {
            var empty = ForecastCard(77);
            ForecastLabel(empty, "暂无可用历史", 13, 11, true, Primary);
            ForecastLabel(empty, "来源未返回记录，不代表过去没有发生过重置", 45, 9);
        }
        foreach (var row in events.Take(allForecastHistory ? 40 : 3))
        {
            var card = ForecastCard(123);
            card.Name = "forecast-history-card";
            ForecastLabel(card, ForecastPresentation.Kind(GetString(row, "kind", "")), 12, 11, true, Primary);
            ForecastLabel(card, "公告 " + ForecastPresentation.Stamp(row, "announced_at")!.Value.LocalDateTime.ToString("yyyy-MM-dd HH:mm"), 42, 9);
            var effective = ForecastPresentation.Stamp(row, "effective_at");
            ForecastLabel(card, effective is null ? "实际生效时间未提供" : "站点记录生效 " + effective.Value.LocalDateTime.ToString("MM-dd HH:mm"), 66, 9);
            ForecastLabel(card, ForecastPresentation.Sources(row) + (GetValue(row, "confirmed").ValueKind == JsonValueKind.True ? " · 站点标为已确认" : " · 未标记确认"), 94, 8.5F);
        }
        if (events.Length > 3)
        {
            var toggle = new Button { Name = "forecast-history-toggle", Text = allForecastHistory ? "收起历史事件" : $"查看全部 {events.Length} 条事件", Height = 34,
                FlatStyle = FlatStyle.Flat, ForeColor = Accent, BackColor = Card, Margin = new Padding(0, 0, 0, 12) };
            toggle.FlatAppearance.BorderColor = theme.Border;
            toggle.Click += (_, _) => { allForecastHistory = !allForecastHistory; using var snapshot = JsonDocument.Parse(lastSnapshot!); Render(snapshot.RootElement); };
            content.Controls.Add(toggle);
        }
    }

    static JsonNode ForecastDemo()
    {
        var result = JsonNode.Parse("""{"status":"partial","cache_state":"fresh","sources":[{"name":"WillReset","status":"available","24h":35,"24h_basis":"published_answer","48h":55,"48h_basis":"cadence_model_fallback"},{"name":"Tibo Radar","status":"available","24h":28,"24h_basis":"published_answer","48h":49,"48h_basis":"published_answer"},{"name":"Reset Monitor","status":"unavailable"}],"ensemble":{"24h":{"weighted_median":35,"min":28,"max":35,"n":2,"has_model":false},"48h":{"weighted_median":55,"min":49,"max":55,"n":2,"has_model":true}}}""")!;
        long now = ForecastDemoNow.ToUnixTimeSeconds();
        result["sources"]![0]!["updated_at"] = now - 1800;
        result["sources"]![1]!["updated_at"] = now - 3600;
        result["targets"] = new JsonArray(new JsonObject { ["kind"] = "typical_window", ["open_at"] = now + 5400,
            ["close_at"] = now + 9000, ["sources"] = new JsonArray("WillReset", "Tibo Radar") });
        var history = new JsonArray();
        for (int i = 0; i < 7; i++) history.Add(new JsonObject { ["kind"] = i % 3 == 1 ? "preview" : "reset", ["announced_at"] = now - (i + 1) * 86400 * 3,
            ["effective_at"] = i % 3 == 1 ? null : now - (i + 1) * 86400 * 3 + 3600, ["confirmed"] = i % 3 != 1, ["sources"] = new JsonArray("WillReset", "Tibo Radar") });
        result["history"] = history;
        return result;
    }
}
