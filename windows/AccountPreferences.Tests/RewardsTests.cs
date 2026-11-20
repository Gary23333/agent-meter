using AgentMeter.Windows;

internal static class RewardsTests
{
    static void Check(bool valid, string message) { if (!valid) throw new InvalidOperationException(message); }

    public static void Run(string parent)
    {
        string directory = Path.Combine(parent, "rewards");
        Check(!RewardPreferences.Load(directory).Enabled, "每日积分领取首次应默认关闭");
        Check(RewardPreferences.ValidClock("08:00") && RewardPreferences.ValidClock("00:05") &&
              RewardPreferences.ValidClock("23:30"), "合法领取时刻被拒绝");
        Check(!RewardPreferences.ValidClock("8:00") && !RewardPreferences.ValidClock("24:00") &&
              !RewardPreferences.ValidClock("08:60") && !RewardPreferences.ValidClock(null), "非法领取时刻被接受");
        RewardPreferences.Save(directory, new RewardSettings(true, "08:30"));
        Check(RewardPreferences.Load(directory) == new RewardSettings(true, "08:30"), "领取设置未正确保存");
        File.WriteAllText(Path.Combine(directory, "auto-claim.json"), "{\"schema\":1,\"enabled\":true}");
        Check(!RewardPreferences.Load(directory).Enabled, "缺字段的领取设置必须保持关闭");
        File.WriteAllText(Path.Combine(directory, "auto-claim.json"), "{\"schema\":1,\"enabled\":true,\"claim_time\":\"25:00\"}");
        Check(!RewardPreferences.Load(directory).Enabled, "非法时刻必须保持关闭");
        File.WriteAllText(Path.Combine(directory, "auto-claim.json"), "broken");
        Check(!RewardPreferences.Load(directory).Enabled, "损坏的领取设置必须保持关闭");

        var rows = RewardsReport.Read("""
        {"schema_version":1,"accounts":[
          {"id":"trae_cn","provider":"trae_cn","status":"available","claimed_credits_today":300,
           "streak_days":1,"claim_time":"08:30","next_claim_at":{"epoch_seconds":1},
           "today":{"kind":"daily_checkin","signed_in":false,"claimable":[{"item":"daily_checkin","credits":300}]},
           "checked_at":{"display":"2026-11-09 16:03"}},
          {"id":"workbuddy","provider":"workbuddy","status":"available","claimed_credits_today":0,"streak_days":3,
           "today":{"claimable":[{"credits":140,"title":"任务甲"},{"credits":60,"title":"任务乙"}]},
           "checked_at":{"display":"2026-11-09 16:04"}},
          {"id":"trae_cn#2","provider":"trae_cn","status":"not_connected","reason":"not_authenticated"}
        ],"unsupported":[
          {"provider":"qoder","reason":"qoder_desktop_credentials_macos_only"},
          {"provider":"minimax_code","reason":"minimax_code_not_supported"}
        ]}
        """);
        Check(rows.Count == 5, "应展示真实账户与暂不支持的来源");
        Check(rows[0].Title == "TRAE 每日签到" && rows[0].Today == "未签到" && rows[0].Claimed == "300 积分" &&
              rows[0].Checked == "2026-11-09 16:03" && rows[0].Detail.Contains("连续 1 天") &&
              rows[0].Detail.Contains("自动 08:30"), "TRAE 今日状态或领取结果错误");
        Check(rows[1].Title == "WorkBuddy 成长任务" && rows[1].Today == "2 项待领 · 200 积分" &&
              rows[1].Claimed == "—" && rows[1].Detail.Contains("连续 3 天"), "WorkBuddy 待领任务或积分错误");
        Check(rows[2].Title.EndsWith("账户 2", StringComparison.Ordinal) && rows[2].Today == "登录已失效", "未登录账户不应显示旧结果");
        Check(rows[3].Id == "unsupported:qoder" && rows[3].Today == "暂不支持" &&
              rows[3].Detail == "Windows 暂不支持桌面凭据", "Qoder 的 Windows 边界未说明");
        Check(rows[4].Detail == "暂无签到接口", "MiniMax Code 的不可用原因错误");
        Check(RewardsReport.Read("""{"request_error":"SECRET_MARKER"}""").Count == 0, "错误对象不应生成虚假账户行");
        Check(RewardsReport.Read("broken").Count == 0 && RewardsReport.Read(null).Count == 0, "损坏结果不应中断界面");
        var invalid = RewardsReport.Read("""{"accounts":[{"id":"trae_cn","provider":"trae_cn","status":"available","claimed_credits_today":"300","today":{"signed_in":false}}]}""");
        Check(invalid.Count == 1 && invalid[0].Claimed == "—" && invalid[0].Today == "未签到", "非法领取数量必须显示为未知");
        Console.WriteLine("每日积分领取设置与结果检查通过");
    }
}
