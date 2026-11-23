using AgentMeter.Windows;

internal static class RewardsTests
{
    static void Check(bool valid, string message) { if (!valid) throw new InvalidOperationException(message); }

    public static void Run(string parent)
    {
        var rows = RewardsReport.Read("""
        {"schema_version":1,"accounts":[
          {"id":"trae_cn","provider":"trae_cn","status":"available","claimed_credits_today":300,
           "claimed_now":["每日签到"],"claimed_credits_now":300,"streak_days":1,
           "today":{"kind":"daily_checkin","signed_in":true,"claimable":[]},
           "checked_at":{"display":"2026-11-09 16:03"}},
          {"id":"workbuddy","provider":"workbuddy","status":"available","claimed_credits_today":0,"claim_time":"08:30",
           "next_claim_at":{"epoch_seconds":1},"claimed_now":["任务甲","任务乙"],"claimed_credits_now":0,
           "today":{"claimable":[]},"checked_at":{"display":"2026-11-09 16:04"}},
          {"id":"trae_cn#2","provider":"trae_cn","status":"not_connected","reason":"not_authenticated"}
        ],"unsupported":[
          {"provider":"qoder","reason":"qoder_desktop_credentials_macos_only"},
          {"provider":"minimax_code","reason":"minimax_code_not_supported"}
        ]}
        """);
        Check(rows.Count == 5, "应展示真实账户与暂不支持的来源");
        Check(rows[0].Title == "TRAE 每日签到" && rows[0].Today == "已签到" && rows[0].Claimed == "300 积分" &&
              rows[0].Checked == "2026-11-09 16:03" && rows[0].Detail.Contains("连续 1 天"), "TRAE 今日状态或领取结果错误");
        Check(!rows[0].Detail.Contains("自动"), "手动领取不应再显示自动时刻");
        Check(rows[1].Title == "WorkBuddy 成长任务" && rows[1].Today == "暂无待领" &&
              rows[1].Claimed == "—" && !rows[1].Detail.Contains("自动"), "WorkBuddy 状态或自动标记错误");
        Check(rows[2].Title.EndsWith("账户 2", StringComparison.Ordinal) && rows[2].Today == "登录已失效", "未登录账户不应显示旧结果");
        Check(rows[3].Id == "unsupported:qoder" && rows[3].Today == "暂不支持" &&
              rows[3].Detail == "Windows 暂不支持桌面凭据", "Qoder 的 Windows 边界未说明");
        Check(rows[4].Detail == "暂无签到接口", "MiniMax Code 的不可用原因错误");

        var successes = RewardsReport.Successes("""
        {"accounts":[
          {"id":"trae_cn","provider":"trae_cn","status":"available","claimed_credits_today":300,
           "claimed_now":["每日签到"],"claimed_credits_now":300},
          {"id":"workbuddy","provider":"workbuddy","status":"available","claimed_credits_today":0,
           "claimed_now":[],"claimed_credits_now":0,"claim_time":"08:30"},
          {"id":"workbuddy#2","provider":"workbuddy","status":"available",
           "claimed_now":["任务甲","任务乙"],"claimed_credits_now":0}
        ]}
        """);
        Check(successes.Count == 2, "只应为本次真正新增的领取生成通知");
        Check(successes[0] == "TRAE 每日签到：+300 积分", "TRAE 成功通知内容错误");
        Check(successes[1] == "WorkBuddy 成长任务 · 账户 2：领取成功（2 项）", "WorkBuddy 成功通知内容错误");

        Check(RewardsReport.Read("""{"request_error":"SECRET_MARKER"}""").Count == 0, "错误对象不应生成虚假账户行");
        Check(RewardsReport.Read("broken").Count == 0 && RewardsReport.Read(null).Count == 0, "损坏结果不应中断界面");
        var invalid = RewardsReport.Read("""{"accounts":[{"id":"trae_cn","provider":"trae_cn","status":"available","claimed_credits_today":"300","today":{"signed_in":false}}]}""");
        Check(invalid.Count == 1 && invalid[0].Claimed == "—" && invalid[0].Today == "未签到", "非法领取数量必须显示为未知");
        Console.WriteLine("每日积分手动领取与成功通知检查通过");
    }
}
