using AgentMeter.Windows;
using System.Text.Json;
using System.Text.Json.Nodes;

internal static class AccountPresentationTests
{
    static void Check(bool valid, string message) { if (!valid) throw new InvalidOperationException(message); }
    static AccountDetails Details(string provider, string json) => AccountDetails.Read(provider, JsonSerializer.Deserialize<JsonElement>(json));

    public static void Run(string directory)
    {
        var now = DateTimeOffset.FromUnixTimeSeconds(1800000000);
        var details = Details("Codex", """
          {"status":"available","credits":{"value":[{"balance":"0"},{"balance":"-1.5"},{"unlimited":true}]},
          "reset_cards":{"value":{"available_count":3,"details_state":"returned","cards":[
            {"status":"available","expires_at":{"epoch_seconds":1800086400.0}},
            {"status":"available","expires_at":{"epoch_seconds":1799999999}},
            {"status":"available","expires_at":null}]}}}
          """);
        Check(details.Amounts.Count == 3 && details.Amounts[0].Value == "0" && details.Amounts[1].Value == "-1.5" && details.Amounts[2].Value == "不限额", "积分池不可相加，也不能把零或负余额丢失");
        var reset = details.ResetCredits!;
        Check(reset.Count == 3 && !reset.Incomplete && reset.Cards[0].State(now) == "已到期 · 待刷新" && reset.Cards[1].State(now) == "1 天内到期" && reset.Cards[2].Expires is null, "重置卡到期顺序或服务报告总数被修改");
        Check(reset.Cards[1].State(now.AddDays(2)) == "已到期 · 待刷新" && reset.Count == 3, "到期只更新提示，不应擅自减少账户总数");
        Check(new ResetCredit("redeeming", now.AddSeconds(-1)).State(now) == "兑换中", "兑换状态应保留");
        var incomplete = Details("Codex", """{"status":"partial","reset_cards":{"value":{"available_count":5,"details_state":"truncated","cards":[{"status":"available","expires_at":{"epoch_seconds":1e100}},{"status":"invalid"}]}}}""");
        Check(incomplete.ResetCredits is { Count: 5, Incomplete: true } && incomplete.ResetCredits.Cards.Count == 1 && incomplete.ResetCredits.Cards[0].Expires is null, "不完整或畸形重置明细应降级");
        Check(!Details("Codex", """{"status":"disabled","credits":{"value":[{"balance":"99"}]}}""").HasContent, "已关闭账户不应展示旧余额");
        Check(Details("Codex", """{"status":"available","reset_cards":{"value":{"available_count":0,"cards":[]}}}""").ResetCredits is { Count: 0, Incomplete: false }, "零张与未知必须区分");
        Check(Details("Codex", """{"status":"available","reset_cards":{"value":{"available_count":true}}}""").ResetCredits is null, "非法数量不可变为零");
        Check(Details("Claude Code", """{"status":"available","subscription":{"plan":"Max"}}""").Plan == "Max" &&
              Details("Claude Code", """{"status":"available","subscription":{"plan":"secret@example.com"}}""").Plan is null, "套餐只允许受限名称");
        Check(Details("Kimi Code", """{"status":"available","credits":{"value":{"amount":"0","unit":"CNY"}}}""").Amounts.Single().Value == "0 CNY", "钱包零余额应展示");
        Check(Details("Kimi Code", """{"status":"available","credits":{"value":{"amount":true,"unit":"CNY"}}}""").Amounts.Count == 0, "无效钱包不应展示");
        var balances = Details("DeepSeek API", """{"status":"available","credits":{"value":[{"total":"8","unit":"CNY","granted":"3","topped_up":"5"},{"total":"2","unit":"USD"}]}}""");
        Check(balances.Amounts.Count == 2 && balances.Amounts[0].Note == "赠金 3 · 充值 5" && balances.Amounts[1].Value == "2 USD", "不同币种必须分别展示");
        Check(Details("WorkBuddy", """{"status":"available","credits":{"value":{"balance":"25","total":"100","frozen":"2"}}}""").Amounts.Single().Note == "总额 100 · 冻结 2", "积分冻结信息遗漏");

        var sample = JsonNode.Parse("""
          {"observed_at":1800000000,"account":{"status":"available","quota":{"value":[
            {"bucket":"codex","window_minutes":300,"remaining_percent":75,"resets_at":{"epoch_seconds":1800003600.0}},
            {"bucket":"codex","window_minutes":10080,"remaining_percent":41,"resets_at":{"epoch_seconds":1800600000}}]}},
          "other_accounts":{"Claude Code":{"status":"partial","quota":{"value":[
            {"bucket":"five_hour","remaining_percent":80},{"bucket":"seven_day_opus","remaining_percent":12}]}},
          "Kimi Code":{"status":"disabled","quota":{"value":[{"remaining_percent":0}]}},
          "MiniMax Code":[{"label":"synthetic-private-alias","status":"available","quota":{"value":[{"bucket":"5h","remaining_percent":2}]}}],
          "DeepSeek API":{"status":"available","credits":{"value":[{"total":"0","unit":"USD"}]}}}}
          """)!;
        TrayIndicator Read(string mode = "lowest", DateTimeOffset? time = null, bool demo = false) => TrayIndicator.Build(JsonSerializer.Deserialize<JsonElement>(sample.ToJsonString()), mode, time ?? now, demo);
        var lowest = Read();
        Check(lowest.Reading is { Remaining: 2, Provider: "MiniMax · 多账户" } && !lowest.Tooltip.Contains("synthetic-private-alias") && lowest.Tooltip.Length <= 127, "自动托盘应选有效最低窗口，不泄露别名");
        Check(Read("codex").Reading is { Remaining: 41, Window: "7 天" }, "托盘应覆盖长期额度");
        Check(Read("claude").Reading is { Remaining: 12, Window: "7 天 Opus", Partial: true }, "模型专属窗口不可遗漏");
        Check(Read("kimi").Reading is null && Read("workbuddy").Reading is null && Read("brand").Reading is null && Read("invalid").Reading is null, "未知、关闭和品牌模式不能伪造额度");
        Check(Read(time: now.AddMinutes(31)).Reading is null && Read(time: now.AddMinutes(-6)).Reading is null, "过期或未来快照必须停止显示数字");
        Check(Read(time: now.AddMinutes(31), demo: true).Tooltip.Contains("演示数据"), "演示模式应明确标注");
        sample["account"]!["quota"]!["value"]![1]!["resets_at"]!["epoch_seconds"] = 1799999999;
        Check(Read("codex").Reading is { Remaining: 75 }, "已到重置时刻的旧窗口不参与选择");
        sample["account"]!["quota"]!["value"]![0]!["remaining_percent"] = 0;
        Check(Read("codex").Reading is { Remaining: 0 } && Read("codex").IconKey == "0:0", "真实零余量必须显示为零");
        sample["account"]!["quota"]!["value"]![0]!["remaining_percent"] = -1;
        Check(Read("codex").Reading is null, "负百分比不可参与选择");
        sample["observed_at"] = null;
        Check(Read().Reading is null, "缺少采集时间不能宣称数据新鲜");

        string prefs = Path.Combine(directory, "tray");
        Check(TrayIndicatorPreferences.Load(prefs) == "lowest", "首次托盘默认应为自动");
        TrayIndicatorPreferences.Save(prefs, "claude");
        Check(TrayIndicatorPreferences.Load(prefs) == "claude", "托盘来源设置未持久化");
        Check(JsonSerializer.Deserialize<JsonElement>(File.ReadAllText(Path.Combine(prefs, "tray-display.json"))).EnumerateObject().Count() == 1, "托盘设置只保存模式");
        File.WriteAllText(Path.Combine(prefs, "tray-display.json"), "bad json");
        Check(TrayIndicatorPreferences.Load(prefs) == "brand", "损坏设置应回退到品牌图标");
        foreach (int size in new[] { 16, 24, 32 })
            foreach (double remaining in new double[] { 0, 2, 19, 49, 73, 100 })
            {
                using var image = TrayIndicatorIcon.Render(remaining, size);
                Check(image.Width == size && image.Height == size && image.GetPixel(0, 0).A < 255 && image.GetPixel(size / 2, size / 2).A == 255, "托盘图像尺寸或透明圆角不正确");
            }
        // 只创建内存位图和图标句柄；不创建通知区域图标或桌面窗口。
        for (int index = 0; index < 64; index++)
        {
            using var icon = TrayIndicatorIcon.Create(index % 101);
            using var bitmap = icon.ToBitmap();
            Check(bitmap.Width == 32, "原生图标克隆在源句柄释放后应保持有效");
        }
        Console.WriteLine("账户附加信息、重置卡、托盘来源与图标检查通过");
    }
}
