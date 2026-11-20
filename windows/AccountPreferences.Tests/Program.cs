using AgentMeter.Windows;
using System.Drawing;
using System.Text.Json;
using System.Text.Json.Nodes;

string parent = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "AgentMeterPreferencesTests"));
string directory = Path.GetFullPath(Path.Combine(parent, Guid.NewGuid().ToString("N")));
if (!directory.StartsWith(parent + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
    throw new InvalidOperationException("测试目录不在预期位置");

try
{
    AccountPresentationTests.Run(directory);
    UsageExportTests.Run();
    RewardsTests.Run(directory);
    var budgetDirectory = Path.Combine(directory, "budget");
    if (BudgetPreferences.Load(budgetDirectory).Enabled) throw new InvalidOperationException("预算默认应关闭");
    var budgetSettings = new BudgetSettings(true, true, 20.5m, 100m, 2m);
    BudgetPreferences.Save(budgetDirectory, budgetSettings);
    if (BudgetPreferences.Load(budgetDirectory) != budgetSettings || BudgetPreferences.TryAmount("-1", out _) ||
        BudgetPreferences.TryAmount("NaN", out _) || BudgetPreferences.TryAmount("1000000001", out _) ||
        BudgetPreferences.ValidMoney(0.001m) || BudgetPreferences.ValidMultiplier(0.0001m))
        throw new InvalidOperationException("预算设置或金额校验错误");
    var budgetNow = new DateTimeOffset(2026, 11, 9, 4, 0, 0, TimeSpan.Zero);
    using (var budget = JsonDocument.Parse("""{"status":"ok","alerts_enabled":true,"generated_at":{"epoch_seconds":1794196800},"daily":{"partial":true},"events":[{"id":"budget_daily_exceeded:2026-11-09","kind":"daily_exceeded","date":"2026-11-09","spent_cny":"25","budget_cny":"20"}]}"""))
    {
        var messages = BudgetAlerts.TakePending(budget.RootElement, budgetDirectory, budgetNow);
        if (messages.Count != 1 || !messages[0].Contains("至少") || BudgetAlerts.TakePending(budget.RootElement, budgetDirectory, budgetNow).Count != 0)
            throw new InvalidOperationException("预算提醒应标记部分数据并跨刷新去重");
        if (BudgetAlerts.TakePending(budget.RootElement, budgetDirectory, budgetNow.AddHours(1)).Count != 0)
            throw new InvalidOperationException("过期预算结果不应触发通知");
        string alertPath = Path.Combine(budgetDirectory, "budget-alerts.json");
        File.WriteAllText(alertPath, "invalid");
        try { BudgetAlerts.TakePending(budget.RootElement, budgetDirectory, budgetNow); throw new InvalidOperationException("损坏的提醒记录不应覆盖"); }
        catch (InvalidDataException) { if (File.ReadAllText(alertPath) != "invalid") throw new InvalidOperationException("提醒记录已被意外覆盖"); }
    }
    using (var budget = JsonDocument.Parse("""{"status":"ok","alerts_enabled":true,"generated_at":{"epoch_seconds":1794196800},"weekly":{"partial":false},"events":[{"id":"budget_weekly_exceeded:2026-11-09","kind":"weekly_exceeded","date":"2026-11-09","spent_cny":"125","budget_cny":"100"},{"id":"budget_anomaly:2026-11-09","kind":"anomaly","date":"2026-11-09","spent_cny":"25","rate_cny_per_hour":"2.5","multiplier":"2"},{"id":"budget_anomaly:2026-11-08","kind":"anomaly","date":"2026-11-08","spent_cny":"25","rate_cny_per_hour":"2.5","multiplier":"2"}]}"""))
    {
        var alertDirectory = Path.Combine(directory, "budget-other-alerts");
        var messages = BudgetAlerts.TakePending(budget.RootElement, alertDirectory, budgetNow);
        if (messages.Count != 2 || !messages.Any(text => text.Contains("本周")) || !messages.Any(text => text.Contains("小时")) ||
            BudgetAlerts.TakePending(budget.RootElement, alertDirectory, budgetNow).Count != 0)
            throw new InvalidOperationException("周预算与异常提醒应过滤过期事件并各自去重");
    }
    var budgetSnapshot = JsonNode.Parse("""{"budget":{"status":"ok","alerts_enabled":true,"config":{"daily_cny":"20.5","weekly_cny":"100","anomaly_multiplier":"2.0"}}}""")!.AsObject();
    BudgetPreferences.Save(budgetDirectory, budgetSettings with { AlertsEnabled = false });
    BudgetState.Apply(budgetSnapshot, budgetDirectory);
    if (budgetSnapshot["budget"]!["alerts_enabled"]!.GetValue<bool>()) throw new InvalidOperationException("关闭提醒后不得采用迟到通知");
    BudgetPreferences.Save(budgetDirectory, budgetSettings with { Daily = 30m });
    BudgetState.Apply(budgetSnapshot, budgetDirectory);
    if (budgetSnapshot["budget"]!["status"]!.GetValue<string>() != "loading") throw new InvalidOperationException("旧预算金额不应继续显示");
    BudgetPreferences.Save(budgetDirectory, budgetSettings with { Enabled = false });
    BudgetState.Apply(budgetSnapshot, budgetDirectory);
    if (budgetSnapshot["budget"]!["status"]!.GetValue<string>() != "disabled") throw new InvalidOperationException("关闭预算后应隐藏旧结果");
    File.WriteAllText(Path.Combine(budgetDirectory, "budget-windows.json"), "invalid");
    try { BudgetPreferences.Load(budgetDirectory); throw new InvalidOperationException("损坏预算设置不应当作默认值"); }
    catch (InvalidDataException) { }
    BudgetState.Apply(budgetSnapshot, budgetDirectory);
    if (budgetSnapshot["budget"]!["status"]!.GetValue<string>() != "invalid") throw new InvalidOperationException("损坏预算设置不应中断刷新");
    string signalName = "Local\\AgentMeterTest-" + Guid.NewGuid().ToString("N");
    using (var listener = new SingleInstanceSignal(signalName))
    using (var sender = new SingleInstanceSignal(signalName))
    using (var received = new ManualResetEventSlim())
    {
        sender.Notify(); // 先发信号，再开始监听，覆盖首次启动尚未完成的竞争情况。
        listener.Listen(() => received.Set());
        if (!received.Wait(TimeSpan.FromSeconds(5))) throw new InvalidOperationException("已有实例未收到唤起信号");
        received.Reset(); sender.Notify();
        if (!received.Wait(TimeSpan.FromSeconds(5))) throw new InvalidOperationException("已有实例无法再次收到唤起信号");
    }
    using (var totals = JsonDocument.Parse("""{"fresh_input":40,"output":10,"reasoning":5,"cache_read":30,"cache_write":15,"total_tokens":100}"""))
    {
        if (!UsageBreakdown.TryRead(totals.RootElement, 100, out var parts) || !parts.SequenceEqual(new double[] { 40, 15, 30, 15, 0 }) ||
            Math.Abs((UsageBreakdown.CacheHitRate(parts) ?? -1) - 30.0 / 85.0) > 0.00001)
            throw new InvalidOperationException("用量构成或缓存命中计算错误");
    }
    using (var unclassified = JsonDocument.Parse("""{"fresh_input":40,"cache_read":30,"unclassified":30}"""))
        if (!UsageBreakdown.TryRead(unclassified.RootElement, 100, out var parts) || UsageBreakdown.CacheHitRate(parts) is not null)
            throw new InvalidOperationException("未拆分数据不能推断缓存命中率");
    foreach (string json in new[] { "{\"fresh_input\":-1,\"cache_read\":11}", "{\"fresh_input\":null,\"cache_read\":10}", "{\"cache_read\":9}" })
    {
        using var invalid = JsonDocument.Parse(json);
        if (UsageBreakdown.TryRead(invalid.RootElement, 10, out _)) throw new InvalidOperationException("异常或不匹配的拆分不能显示为完整构成");
    }
    if (UsageBreakdown.CacheHitRate([0, 3, 0, 0, 0]) is not null) throw new InvalidOperationException("没有输入时缓存命中率应为未知");
    using (var costs = JsonDocument.Parse("""{"A":{"status":"available","value":{"periods":{"7d":{"totals":{"total_tokens":42}}}},"estimates":{"7d":{"amount_usd":"1.25","partial":false}}},"B":{"status":"partial","value":{"periods":{"7d":{"totals":{"total_tokens":9}}}}}}"""))
    {
        var totalCost = UsageCostSummary.Read(costs.RootElement, "7d");
        if (totalCost.Amount != 1.25m || !totalCost.Partial || totalCost.Display != "$1.25" || UsageCostSummary.Read(costs.RootElement, "today").Amount is not null)
            throw new InvalidOperationException("费用汇总应只统计同周期已知价格并提示不完整");
    }
    using (var costs = JsonDocument.Parse("""{"A":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":1}}}},"estimate":{"amount_usd":"0","partial":false}}}"""))
        if (UsageCostSummary.Read(costs.RootElement, "today") is not { Amount: 0, Partial: false }) throw new InvalidOperationException("免费价格估算不能误当未知");
    using (var costs = JsonDocument.Parse("""{"A":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":0}}}},"estimates":{"today":{"amount_usd":"0","partial":false}}},"B":{"status":"partial","value":{"periods":{"today":{"totals":{"total_tokens":0}}}},"estimates":{"today":{"amount_usd":"0","partial":true}}}}"""))
        if (UsageCostSummary.Read(costs.RootElement, "today") is not { Amount: 0, Partial: true, Display: "$0" }) throw new InvalidOperationException("零用量费用及不完整状态显示错误");
    using (var sources = JsonDocument.Parse("""{"Codex":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":10}},"7d":{"totals":{"total_tokens":90}}}},"estimates":{"today":{"amount_usd":"0.125","partial":false}}},"Claude Code":{"status":"partial","value":{"periods":{"today":{"totals":{"total_tokens":30}}}}},"Empty":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":0}}}}},"Bad":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":-10}}}}},"Unavailable":{"status":"error"}}"""))
    {
        var todayRows = UsageSource.Read(sources.RootElement, "today");
        if (todayRows.Count != 2 || todayRows[0].Name != "Claude Code" || todayRows[0].Cost is not null || !todayRows[0].Partial ||
            todayRows[1].Tokens != 10 || todayRows[1].CostDisplay != "$0.125" || todayRows[1].Partial)
            throw new InvalidOperationException("按应用对比应排序并区分缺失费用与部分记录");
        var weekRows = UsageSource.Read(sources.RootElement, "7d");
        if (weekRows.Count != 1 || weekRows[0].Tokens != 90 || weekRows[0].Cost is not null || UsageSource.Read(sources.RootElement, "bad").Count != 0)
            throw new InvalidOperationException("按应用对比应使用所选周期，不虚构金额");
    }
    using (var history = JsonDocument.Parse("""{"Codex":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":100},"groups":[{"model":"gpt-5.3-codex","total_tokens":100}],"model_costs":{"gpt-5.3-codex":{"amount_usd":"1.25","partial":false}}},"7d":{"totals":{"total_tokens":400},"groups":[{"model":"gpt-5.3-codex","total_tokens":400}]}}}},"OpenCode":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":200},"groups":[{"model":"gpt-5.3-codex","total_tokens":200}]},"7d":{"totals":{"total_tokens":0}}}}}}"""))
    {
        var today = ModelRanking.Read(history.RootElement, "today");
        if (today.Incomplete || today.Rows.Count != 2 || today.Rows[0].Source != "OpenCode" || today.Rows[0].Cost is not null ||
            today.Rows[1].Source != "Codex" || today.Rows[1].CostDisplay != "$1.25")
            throw new InvalidOperationException("同模型应按来源分别排行，缺失费用不能显示为零");
        var week = ModelRanking.Read(history.RootElement, "7d");
        if (week.Incomplete || week.Rows.Count != 1 || week.Rows[0].Tokens != 400 || week.Rows[0].Cost is not null)
            throw new InvalidOperationException("模型排行必须跟随所选周期");
    }
    using (var incomplete = JsonDocument.Parse("""{"Codex":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":100},"groups":[{"model":"未识别模型","total_tokens":80}],"groups_incomplete":true}}}}}"""))
        if (!ModelRanking.Read(incomplete.RootElement, "today").Incomplete) throw new InvalidOperationException("匿名或缺失模型必须提示不完整");
    StartupTests.Run();
    using (var comparison = JsonDocument.Parse("""{"comparable_days":3,"current_comparable_tokens":150,"previous_comparable_tokens":100}"""))
        if (ReportComparison.Read(comparison.RootElement)?.Change != "+50%") throw new InvalidOperationException("相同天数的报告对照错误");
    using (var zero = JsonDocument.Parse("""{"comparable_days":1,"current_comparable_tokens":5,"previous_comparable_tokens":0}"""))
        if (ReportComparison.Read(zero.RootElement)?.Change != "上期为 0 · 不计算增幅") throw new InvalidOperationException("上期为零不能计算增长率");
    using (var firstDay = JsonDocument.Parse("""{"comparable_days":0,"current_comparable_tokens":0,"previous_comparable_tokens":0}"""))
        if (ReportComparison.Read(firstDay.RootElement) is not null) throw new InvalidOperationException("首日不能显示虚假的对照");
    using (var invalidComparison = JsonDocument.Parse("""{"comparable_days":true,"current_comparable_tokens":3,"previous_comparable_tokens":2}"""))
        if (ReportComparison.Read(invalidComparison.RootElement) is not null) throw new InvalidOperationException("无效对照字段不应中断报告");
    using (var comparableReport = JsonDocument.Parse("""{"calendar_report":{"periods":{"week":{"previous_start":"2025-12-22","current_start":"2025-12-29","current_end":"2026-01-01","previous_tokens":50,"current_tokens":300,"comparable_days":3,"current_comparable_tokens":150,"previous_comparable_tokens":100},"month":{"previous_start":"2025-12-01","current_start":"2026-01-01","current_end":"2026-01-01","previous_tokens":180,"current_tokens":200}}}}"""))
        if (!CalendarReportExport.Create(comparableReport.RootElement).Contains("前 3 个自然日") || !CalendarReportExport.Create(comparableReport.RootElement).Contains("变化 +50%"))
            throw new InvalidOperationException("报告导出缺少可比口径");
    var usagePreferencesDirectory = Path.Combine(directory, "usage-period");
    if (UsagePeriodPreferences.Load(usagePreferencesDirectory) != "today") throw new InvalidOperationException("默认用量周期错误");
    UsagePeriodPreferences.Save(usagePreferencesDirectory, "30d");
    if (UsagePeriodPreferences.Load(usagePreferencesDirectory) != "30d") throw new InvalidOperationException("用量周期未保存");
    File.WriteAllText(Path.Combine(usagePreferencesDirectory, "usage-view.json"), "invalid");
    if (UsagePeriodPreferences.Load(usagePreferencesDirectory) != "today") throw new InvalidOperationException("损坏的周期设置应回退今日");
    var clock = DateTimeOffset.FromUnixTimeSeconds(1800000000);
    if (QuotaResetClock.Short(1800003660, clock) != "1 小时 1 分后" ||
        QuotaResetClock.Short(1800000000, clock) != "已到时间 · 待刷新" ||
        QuotaResetClock.Short(null, clock) != "重置时间未知") throw new InvalidOperationException("账户重置倒计时不正确");
    using (var forecast = JsonDocument.Parse("""{"kind":"typical_window","open_at":1800000060,"close_at":1800003660,"sources":["WillReset","unknown","WillReset"]}"""))
    {
        var window = ForecastWindow.Read(forecast.RootElement) ?? throw new InvalidOperationException("预测窗口未解析");
        if (window.Sources != "WillReset" || window.Countdown(clock) != "距时段开始 1 分 00 秒" ||
            window.Countdown(clock.AddSeconds(60)) != "时段内 · 距结束 1 小时 00 分" ||
            window.Countdown(clock.AddSeconds(3660)) != "时段已结束 · 等待更新")
            throw new InvalidOperationException("预测窗口倒计时边界错误");
        var promise = window with { Typical = false, Open = null };
        if (promise.Countdown(clock.AddSeconds(3661)) != "时间已过 · 尚待确认")
            throw new InvalidOperationException("不可把时间已过当作确认重置");
    }
    using (var invalid = JsonDocument.Parse("""{"kind":"promised_reset","close_at":true,"sources":["WillReset"]}"""))
        if (ForecastWindow.Read(invalid.RootElement) is not null) throw new InvalidOperationException("无效时钟不应生成倒计时");
    using (var invalidRange = JsonDocument.Parse("""{"weighted_median":95,"min":20,"max":40,"n":2}"""))
        if (ForecastRange.Read(invalidRange.RootElement) is not null) throw new InvalidOperationException("越界中位数不应展示");
    using (var validRange = JsonDocument.Parse("""{"weighted_median":35,"min":28,"max":35,"n":2,"has_model":true}"""))
        if (ForecastRange.Read(validRange.RootElement)?.HasModel != true) throw new InvalidOperationException("预测依据未保留");
    if (!ActivityRefreshPolicy.CanRefresh(false, true, true, false, false, true, clock.AddSeconds(-60), clock) ||
        ActivityRefreshPolicy.CanRefresh(false, false, true, false, false, true, clock.AddSeconds(-60), clock) ||
        ActivityRefreshPolicy.CanRefresh(false, true, false, false, false, true, clock.AddSeconds(-60), clock) ||
        ActivityRefreshPolicy.CanRefresh(false, true, true, true, false, true, clock.AddSeconds(-60), clock) ||
        ActivityRefreshPolicy.CanRefresh(false, true, true, false, true, true, clock.AddSeconds(-60), clock) ||
        ActivityRefreshPolicy.CanRefresh(true, true, true, false, false, true, clock.AddSeconds(-60), clock) ||
        ActivityRefreshPolicy.CanRefresh(false, true, true, false, false, false, clock.AddSeconds(-60), clock) ||
        ActivityRefreshPolicy.CanRefresh(false, true, true, false, false, true, clock.AddSeconds(-59), clock))
        throw new InvalidOperationException("本机活动刷新条件不正确");
    var namedProvider = ProviderStyle.For("MINIMAX CODE · 家庭账户");
    if (namedProvider.DisplayName != "MiniMax Code · 家庭账户" || namedProvider.Initial != "M" ||
        ProviderStyle.For("unknown service").DisplayName != "unknown service" ||
        ProviderStyle.For("CODEX").Color == ProviderStyle.For("CLAUDE CODE").Color)
        throw new InvalidOperationException("服务标识或账户别名显示不正确");
    var localDays = new JsonArray();
    for (int index = 0; index < 30; index++)
        localDays.Add(new JsonObject { ["date"] = new DateOnly(2026, 1, 1).AddDays(index).ToString("yyyy-MM-dd"), ["tokens"] = index });
    var localItem = new JsonObject { ["status"] = "partial", ["value"] = new JsonObject {
        ["periods"] = JsonNode.Parse("""{"today":{"totals":{"total_tokens":15}},"30d":{"totals":{"total_tokens":100}}}"""),
        ["daily_trend"] = new JsonObject { ["days"] = localDays, ["incomplete"] = false } } };
    using (var localDoc = JsonDocument.Parse(localItem.ToJsonString()))
    {
        var local = AccountLocalUsage.Read(localDoc.RootElement);
        if (local is null || local.Today != 15 || local.ThirtyDays != 100 || local.All is not null ||
            local.Trend?.Count != 30 || !local.Incomplete)
            throw new InvalidOperationException("账户卡片的本机用量或不完整状态不正确");
    }
    localDays[5]!["date"] = "2026-02-20";
    using (var invalidTrend = JsonDocument.Parse(localItem.ToJsonString()))
        if (AccountLocalUsage.Read(invalidTrend.RootElement)?.Trend is not null)
            throw new InvalidOperationException("非连续的本机逐日数据不应绘制为趋势");
    localItem["status"] = "unavailable";
    using (var unavailable = JsonDocument.Parse(localItem.ToJsonString()))
        if (AccountLocalUsage.Read(unavailable.RootElement) is not null)
            throw new InvalidOperationException("不可用的本机账本不应显示为已读取");
    using (var overview = JsonDocument.Parse("""
        {"account":{"status":"available","quota":{"value":[{"remaining_percent":50}]}},
         "other_accounts":{"Claude Code":{"status":"disabled"},"MiniMax Code":[{"status":"available","quota":{"value":[{}]}},{"status":"error"}]},
         "history":{"Codex":{"status":"partial","value":{"periods":{"today":{"totals":{"total_tokens":15}},"all":{"totals":{"total_tokens":80}}}}},
                    "Claude Code":{"status":"available","value":{"periods":{"all":{"totals":{"total_tokens":50}}}}},
                    "Gemini CLI":{"status":"unavailable","reason":"gemini_chats_not_found"}},
         "activity":{"sources":{"Codex":"available","Claude Code":"available","Gemini CLI":"not_found"},
           "apps":[{"name":"Codex","sessions":3,"recent_updates":2,"last_updated":1800000000}]}}
        """))
    {
        var rows = ApplicationOverview.Build(overview.RootElement);
        var codex = rows.First(row => row.Name == "Codex");
        var claude = rows.First(row => row.Name == "Claude Code");
        var minimaxOverview = rows.First(row => row.Name == "MiniMax Code");
        if (rows[0].Name != "Codex" || codex.Quota != "可用" || codex.Local != "部分可用" || codex.Today != 15 || codex.All != 80 || codex.RecentUpdates != 2 ||
            claude.Quota != "已关闭" || claude.Today is not null || claude.Activity != "近 24 小时无记录" || minimaxOverview.Quota != "部分可用" ||
            rows.Any(row => row.Name == "Gemini CLI"))
            throw new InvalidOperationException("应用概览混淆了额度、本机用量或活动状态");
    }
    var cardSnapshot = JsonNode.Parse("""{"account":{"status":"available","private":"SECRET_MARKER","quota":{"status":"available","unused":"SECRET_MARKER","value":[{"bucket":"codex","window_minutes":300,"remaining_percent":55,"resets_at":{"epoch_seconds":1800003600,"extra":"SECRET_MARKER"},"private":"SECRET_MARKER"}]}},"other_accounts":{"MiniMax Code":[{"label":"演示账户","status":"available","key":"SECRET_MARKER","quota":{"value":[{"bucket":"5h","remaining_percent":50,"resets_at":{"epoch_seconds":1800003600}}]}}],"unknown":{"secret":"SECRET_MARKER"}}}""")!.AsObject();
    string cardInput = CardInput.Create(cardSnapshot);
    if (cardInput.Contains("SECRET_MARKER", StringComparison.Ordinal)) throw new InvalidOperationException("卡册输入包含多余字段");
    using (var doc = JsonDocument.Parse(cardInput))
    {
        if (doc.RootElement.GetProperty("account").GetProperty("quota").GetProperty("value")[0].GetProperty("remaining_percent").GetInt32() != 55 ||
            doc.RootElement.GetProperty("other_accounts").GetProperty("MiniMax Code")[0].GetProperty("label").GetString() != "演示账户")
            throw new InvalidOperationException("卡册输入缺少额度或账户标识");
    }
    Guid credentialId = Guid.NewGuid();
    try
    {
        if (CredentialVault.Read("test", credentialId) is not null) throw new InvalidOperationException("随机测试凭据不应存在");
        CredentialVault.Write("test", credentialId, "模拟密钥-A");
        if (CredentialVault.Read("test", credentialId) != "模拟密钥-A") throw new InvalidOperationException("凭据读取失败");
        CredentialVault.Write("test", credentialId, "模拟密钥-B");
        if (CredentialVault.Read("test", credentialId) != "模拟密钥-B") throw new InvalidOperationException("凭据更新失败");
        CredentialVault.Delete("test", credentialId);
        if (CredentialVault.Read("test", credentialId) is not null) throw new InvalidOperationException("凭据删除失败");
        CredentialVault.Write("deepseek", credentialId, "synthetic-key");
        if (CredentialVault.Read("deepseek", credentialId) != "synthetic-key") throw new InvalidOperationException("DeepSeek 凭据读取失败");
    }
    finally { CredentialVault.Delete("test", credentialId); CredentialVault.Delete("deepseek", credentialId); }
    if (AccountPreferences.Load(directory) != AccountPreferences.Enabled)
        throw new InvalidOperationException("首次运行应启用账户查询");
    var changed = new AccountPreferences(false, true, false);
    changed.Save(directory);
    if (AccountPreferences.Load(directory) != changed)
        throw new InvalidOperationException("账户开关未正确保存或读取");
    File.WriteAllText(Path.Combine(directory, "preferences.json"), "not-json");
    if (AccountPreferences.Load(directory) != AccountPreferences.Disabled)
        throw new InvalidOperationException("损坏的设置应关闭账户查询");
    AccountPreferences.Enabled.Save(directory);
    if (AccountPreferences.Load(directory) != AccountPreferences.Enabled)
        throw new InvalidOperationException("账户开关未正确覆盖");
    File.WriteAllText(Path.Combine(directory, "preferences.json"), "{\"codex\":true,\"kimi\":false,\"claude\":true}");
    var oldPreferences = AccountPreferences.Load(directory);
    if (!oldPreferences.Codex || oldPreferences.Kimi || !oldPreferences.Claude || oldPreferences.MiniMax || oldPreferences.DeepSeek || oldPreferences.WorkBuddy || oldPreferences.ZCode || oldPreferences.Volcengine || oldPreferences.MiMo || oldPreferences.Qoder || oldPreferences.Trae)
        throw new InvalidOperationException("旧设置兼容或新增来源默认关闭失败");
    var deepseekPreferences = oldPreferences with { DeepSeek = true, WorkBuddy = true };
    deepseekPreferences.Save(directory);
    if (AccountPreferences.Load(directory) != deepseekPreferences) throw new InvalidOperationException("DeepSeek 开关保存失败");
    var zcodePreferences = deepseekPreferences with { ZCode = true }; zcodePreferences.Save(directory);
    if (AccountPreferences.Load(directory) != zcodePreferences) throw new InvalidOperationException("智谱账户开关保存失败");
    var volcPreferences = zcodePreferences with { Volcengine = true }; volcPreferences.Save(directory);
    if (AccountPreferences.Load(directory) != volcPreferences) throw new InvalidOperationException("火山方舟账户开关保存失败");
    var mimoPreferences = volcPreferences with { MiMo = true }; mimoPreferences.Save(directory);
    if (AccountPreferences.Load(directory) != mimoPreferences) throw new InvalidOperationException("MiMo 账户开关保存失败");
    var qoderPreferences = mimoPreferences with { Qoder = true }; qoderPreferences.Save(directory);
    if (AccountPreferences.Load(directory) != qoderPreferences) throw new InvalidOperationException("Qoder 账户开关保存失败");
    var traePreferences = qoderPreferences with { Trae = true }; traePreferences.Save(directory);
    if (AccountPreferences.Load(directory) != traePreferences) throw new InvalidOperationException("TRAE 账户开关保存失败");
    if (!VolcengineKeyStore.Valid(new VolcengineKeys("AK-synthetic", "synthetic-secret")) ||
        VolcengineKeyStore.Valid(new VolcengineKeys("model-api-key", "secret")) ||
        VolcengineKeyStore.Valid(new VolcengineKeys("AK-valid", "bad\nsecret")))
        throw new InvalidOperationException("火山方舟凭据格式校验失败");
    using (var input = JsonDocument.Parse(VolcengineKeyStore.Input(new VolcengineKeys("bad", "secret"))))
        if (input.RootElement.GetProperty("credentials").ValueKind != JsonValueKind.Null) throw new InvalidOperationException("无效凭据不能传给后端");
    if (!ZCodeKeyStore.IsValid("synthetic-key") || ZCodeKeyStore.IsValid("bad key") || ZCodeKeyStore.IsValid("bad\nkey"))
        throw new InvalidOperationException("智谱密钥格式校验失败");
    using (var input = JsonDocument.Parse(ZCodeKeyStore.Input("bad key")))
        if (input.RootElement.GetProperty("key").ValueKind != JsonValueKind.Null) throw new InvalidOperationException("无效密钥不能传给后端");
    if (!DeepSeekKeyStore.IsValid("sk-synthetic") || DeepSeekKeyStore.IsValid("bad key") || DeepSeekKeyStore.IsValid("bad\nkey"))
        throw new InvalidOperationException("DeepSeek 密钥格式校验失败");
    using (var secretInput = JsonDocument.Parse(DeepSeekKeyStore.Input("bad key")))
        if (secretInput.RootElement.GetProperty("key").ValueKind != JsonValueKind.Null) throw new InvalidOperationException("无效密钥不应传给后端");
    var browserCookies = new[] {
        new WebCookieFilter.Cookie("session", "synthetic-value", ".workbuddy.cn", "/"),
        new WebCookieFilter.Cookie("billing", "synthetic-billing", "www.workbuddy.cn", "/billing"),
        new WebCookieFilter.Cookie("foreign", "must-not-send", ".other.example", "/"),
        new WebCookieFilter.Cookie("wrongpath", "must-not-send", "www.workbuddy.cn", "/billing-other") };
    string? cookieHeader = WebCookieFilter.WorkBuddyHeader(browserCookies);
    if (cookieHeader != "session=synthetic-value; billing=synthetic-billing") throw new InvalidOperationException("登录 Cookie 的域或路径筛选不正确");
    if (WebCookieFilter.WorkBuddyHeader([new WebCookieFilter.Cookie("session", "bad\r\nvalue", ".workbuddy.cn", "/")]) is not null ||
        WebCookieFilter.WorkBuddyHeader([new WebCookieFilter.Cookie("session", "safe", ".evilworkbuddy.cn", "/")]) is not null)
        throw new InvalidOperationException("非法 Cookie 不应发送");
    WebCookieFilter.Cookie[] mimoCookies = [new("api-platform_serviceToken", "synthetic", ".xiaomimimo.com", "/api/v1"),
        new("userId", "42", "platform.xiaomimimo.com", "/"), new("unrelated", "private", ".xiaomimimo.com", "/"),
        new("api-platform_ph", "scoped", ".xiaomimimo.com", "/api/v1/balance")];
    string? mimoHeader = WebCookieFilter.MiMoHeader(mimoCookies);
    if (mimoHeader is null || !mimoHeader.Contains("userId=42") || mimoHeader.Contains("private") || mimoHeader.Contains("scoped") ||
        WebCookieFilter.MiMoHeader(mimoCookies.Append(mimoCookies[0])) is not null ||
        WebCookieFilter.MiMoHeader([new("userId", "42", ".xiaomimimo.com", "/")]) is not null ||
        WebCookieFilter.MiMoHeader([new("api-platform_serviceToken", "bad\r\nheader", ".xiaomimimo.com", "/"), new("userId", "42", ".xiaomimimo.com", "/")]) is not null ||
        WebCookieFilter.MiMoHeader([new("api-platform_serviceToken", "secret", ".evilxiaomimimo.com", "/"), new("userId", "42", ".xiaomimimo.com", "/")]) is not null)
        throw new InvalidOperationException("MiMo Cookie 必须过滤来源、路径和重复字段");
    if (!MiMoNavigation.IsPlatform("https://platform.xiaomimimo.com/#/console/balance") ||
        !MiMoNavigation.Allowed("https://account.xiaomi.com/") || MiMoNavigation.Allowed("https://xiaomimimo.com.evil.example/") ||
        MiMoNavigation.Allowed("https://user@platform.xiaomimimo.com/") || MiMoNavigation.Allowed("http://platform.xiaomimimo.com/"))
        throw new InvalidOperationException("MiMo 登录跳转域名过滤错误");
    WebCookieFilter.Cookie[] qoderCookies = [new("sid", "synthetic", ".qoder.com.cn", "/api"),
        new("other", "private", ".evilqoder.com.cn", "/"), new("wrong", "private", ".qoder.com.cn", "/account")];
    if (WebCookieFilter.QoderHeader(qoderCookies) != "sid=synthetic" ||
        WebCookieFilter.QoderHeader(qoderCookies.Append(qoderCookies[0])) is not null ||
        WebCookieFilter.QoderHeader([new("sid", "bad\r\nheader", ".qoder.com.cn", "/")]) is not null ||
        WebCookieFilter.QoderHeader([new("bad\\name", "value", ".qoder.com.cn", "/")]) is not null ||
        !QoderNavigation.IsQoder("https://qoder.com.cn/account/usage") ||
        QoderNavigation.Allowed("https://qoder.com.cn.evil.example/") || QoderNavigation.Allowed("http://qoder.com.cn/"))
        throw new InvalidOperationException("Qoder Cookie 或登录域名过滤错误");
    string syntheticJwt = "synthetic.jwt." + new string('a', 24);
    if (TraeHeaderFilter.Token("https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage", "Cloud-IDE-JWT " + syntheticJwt) != syntheticJwt ||
        TraeHeaderFilter.Token("https://api.trae.cn.evil.example/", "Cloud-IDE-JWT " + syntheticJwt) is not null ||
        TraeHeaderFilter.Token("http://api.trae.cn/", "Cloud-IDE-JWT " + syntheticJwt) is not null ||
        TraeHeaderFilter.Token("https://api.trae.cn/", "Cloud-IDE-JWT bad\r\nheader") is not null ||
        TraeHeaderFilter.Device("bad\r\nvalue") is not null ||
        !TraeNavigation.IsTrae("https://www.trae.cn/pricing") || TraeNavigation.Allowed("https://trae.cn.evil.example/"))
        throw new InvalidOperationException("TRAE 授权头和登录域名过滤错误");
    if (!WorkBuddyNavigation.Allowed("https://www.workbuddy.cn/profile/plans-usage") ||
        !WorkBuddyNavigation.Allowed("https://xui.ptlogin2.qq.com/") || !WorkBuddyNavigation.IsWorkBuddy("https://www.workbuddy.cn/"))
        throw new InvalidOperationException("合法登录网址应可访问");
    foreach (string unsafeUrl in new[] { "http://www.workbuddy.cn/", "https://workbuddy.cn.evil.example/", "https://user@www.workbuddy.cn/", "file:///C:/secret", "https://127.0.0.1/" })
        if (WorkBuddyNavigation.Allowed(unsafeUrl)) throw new InvalidOperationException("不允许未知登录网址");
    if (WebViewSafety.ContainsOverride([null, ""]) || !WebViewSafety.ContainsOverride([null, "--remote-debugging-port=1"]) ||
        !WebViewSafety.SameDirectory(directory, directory + Path.DirectorySeparatorChar) ||
        WebViewSafety.SameDirectory(directory, Path.Combine(directory, "different")))
        throw new InvalidOperationException("WebView2 资料隔离检查失败");
    string? previousOverride = Environment.GetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER");
    try
    {
        Environment.SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", Path.Combine(directory, "synthetic-profile"));
        try { WebViewSafety.EnsureNoOverrides(); throw new InvalidOperationException("应拒绝 WebView2 资料目录覆盖"); }
        catch (InvalidOperationException ex) when (ex.Message == "webview_override_configured") { }
    }
    finally { Environment.SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", previousOverride); }
    var fakeVault = new FakeMiniMaxVault();
    if (MiniMaxAccountInput.Build(directory, fakeVault) is not null)
        throw new InvalidOperationException("没有账户列表时应保留环境变量模式");
    var account = MiniMaxProfiles.Add(directory, "测试账户", "cn", "synthetic-secret", fakeVault);
    if (MiniMaxProfiles.Load(directory).Single() != account || fakeVault.Read(account.Id) != "synthetic-secret" ||
        File.ReadAllText(Path.Combine(directory, "minimax-accounts.json")).Contains("synthetic-secret"))
        throw new InvalidOperationException("账户信息与凭据未正确分离");
    using (var input = JsonDocument.Parse(MiniMaxAccountInput.Build(directory, fakeVault)!))
    {
        var item = input.RootElement.GetProperty("minimax_accounts")[0];
        if (item.GetProperty("label").GetString() != "测试账户" || item.GetProperty("key").GetString() != "synthetic-secret")
            throw new InvalidOperationException("账户标准输入内容不正确");
    }
    fakeVault.Write(account.Id, "bad\nvalue");
    using (var input = JsonDocument.Parse(MiniMaxAccountInput.Build(directory, fakeVault)!))
        if (input.RootElement.GetProperty("minimax_accounts")[0].GetProperty("key").ValueKind != JsonValueKind.Null)
            throw new InvalidOperationException("损坏的凭据不应传递给后端");
    fakeVault.Write(account.Id, "synthetic-secret");
    fakeVault.FailRead = true;
    using (var input = JsonDocument.Parse(MiniMaxAccountInput.Build(directory, fakeVault)!))
        if (input.RootElement.GetProperty("minimax_accounts")[0].GetProperty("key").ValueKind != JsonValueKind.Null)
            throw new InvalidOperationException("凭据读取失败应标为缺失");
    fakeVault.FailRead = false;
    try { MiniMaxProfiles.Add(directory, "测试账户", "cn", "synthetic-duplicate", fakeVault); throw new InvalidOperationException("重复账户名称应被拒绝"); }
    catch (InvalidDataException) { }
    fakeVault.FailWrite = true;
    try { MiniMaxProfiles.Add(directory, "另一个账户", "global", "synthetic-other", fakeVault); throw new InvalidOperationException("模拟保存失败未生效"); }
    catch (IOException) { }
    if (MiniMaxProfiles.Load(directory).Count != 1) throw new InvalidOperationException("凭据写入失败后应回滚账户列表");
    fakeVault.FailWrite = false; fakeVault.FailDelete = true;
    try { MiniMaxProfiles.Remove(directory, account.Id, fakeVault); throw new InvalidOperationException("模拟删除失败未生效"); }
    catch (IOException) { }
    if (MiniMaxProfiles.Load(directory).Count != 1) throw new InvalidOperationException("凭据删除失败时不能隐藏账户");
    fakeVault.FailDelete = false; MiniMaxProfiles.Remove(directory, account.Id, fakeVault);
    if (MiniMaxProfiles.Load(directory).Count != 0 || fakeVault.Read(account.Id) is not null)
        throw new InvalidOperationException("账户和凭据应同时删除");
    using (var input = JsonDocument.Parse(MiniMaxAccountInput.Build(directory, fakeVault)!))
        if (input.RootElement.GetProperty("minimax_accounts").GetArrayLength() != 0)
            throw new InvalidOperationException("清空账户后不应回退到环境变量");
    var firstAccount = MiniMaxProfiles.Add(directory, "甲", "cn", "synthetic-a", fakeVault);
    var secondAccount = MiniMaxProfiles.Add(directory, "乙", "global", "synthetic-b", fakeVault);
    using (var input = JsonDocument.Parse(MiniMaxAccountInput.Build(directory, fakeVault)!))
        if (input.RootElement.GetProperty("minimax_accounts").GetArrayLength() != 2)
            throw new InvalidOperationException("多个账户未正确隔离");
    MiniMaxProfiles.Remove(directory, firstAccount.Id, fakeVault);
    MiniMaxProfiles.Remove(directory, secondAccount.Id, fakeVault);
    if (VisualThemes.All.Count != 7 || VisualThemes.All.Select(t => t.Id).Distinct().Count() != 7)
        throw new InvalidOperationException("界面风格列表不完整");
    VisualThemes.Save(directory, VisualThemes.Find("porcelain"));
    if (VisualThemes.Load(directory).Id != "porcelain") throw new InvalidOperationException("界面风格未正确保存");
    File.WriteAllText(Path.Combine(directory, "appearance.json"), "not-json");
    if (VisualThemes.Load(directory).Id != "aurora") throw new InvalidOperationException("损坏的外观设置应回退默认风格");
    static double Luminance(Color color)
    {
        static double Linear(int channel) { double v = channel / 255.0; return v <= 0.04045 ? v / 12.92 : Math.Pow((v + 0.055) / 1.055, 2.4); }
        return 0.2126 * Linear(color.R) + 0.7152 * Linear(color.G) + 0.0722 * Linear(color.B);
    }
    static double Contrast(Color a, Color b)
    {
        double x = Luminance(a), y = Luminance(b);
        return (Math.Max(x, y) + 0.05) / (Math.Min(x, y) + 0.05);
    }
    foreach (var theme in VisualThemes.All)
    {
        foreach (var background in new[] { theme.Background, theme.Card, theme.CardEnd })
            if (Contrast(theme.Primary, background) < 4.5 || Contrast(theme.Secondary, background) < 4.5)
                throw new InvalidOperationException($"{theme.Name} 的文字对比度不足");
        if (Contrast(Color.White, theme.Selected) < 4.5) throw new InvalidOperationException($"{theme.Name} 的选中标签对比度不足");
        if (Contrast(theme.Accent, theme.Background) < 4.5 || Contrast(theme.Accent, theme.Card) < 4.5)
            throw new InvalidOperationException($"{theme.Name} 的强调文字对比度不足");
    }
    var prices = new[] { new PriceRow("sample-model", 1.25m, 0.2m, 0m, 3m) };
    PriceOverrides.Save(directory, prices);
    if (PriceOverrides.Load(directory).Single() != prices[0]) throw new InvalidOperationException("价格保存或读取失败");
    string oldPrices = File.ReadAllText(Path.Combine(directory, "prices.json"));
    try
    {
        PriceOverrides.Save(directory, new[] { prices[0], prices[0] with { Model = "SAMPLE.MODEL" } });
        throw new InvalidOperationException("不应接受重复的模型名称");
    }
    catch (InvalidDataException) { }
    if (File.ReadAllText(Path.Combine(directory, "prices.json")) != oldPrices)
        throw new InvalidOperationException("无效价格不能覆盖已有设置");
    File.WriteAllText(Path.Combine(directory, "prices.json"), "broken");
    try { PriceOverrides.Load(directory); throw new InvalidOperationException("损坏价格文件不应被当作空设置"); }
    catch (InvalidDataException) { }
    File.WriteAllText(Path.Combine(directory, "prices.json"), "{\"currency\":\"USD\",\"models\":{},\"future\":true}");
    try { PriceOverrides.Load(directory); throw new InvalidOperationException("未知字段不能被静默覆盖"); }
    catch (InvalidDataException) { }
    if (AlertPreferences.Load(directory)) throw new InvalidOperationException("额度提醒首次应默认关闭");
    AlertPreferences.Save(directory, true);
    if (!AlertPreferences.Load(directory)) throw new InvalidOperationException("额度提醒设置未保存");
    File.WriteAllText(Path.Combine(directory, "alerts.json"), "{\"enabled\":true}");
    if (AlertPreferences.LoadSettings(directory) != new AlertSettings(true, 20)) throw new InvalidOperationException("旧版提醒设置应保留开关并使用默认阈值");
    AlertPreferences.Save(directory, new AlertSettings(true, 30));
    if (AlertPreferences.LoadSettings(directory) != new AlertSettings(true, 30)) throw new InvalidOperationException("提醒阈值未保存");
    File.WriteAllText(Path.Combine(directory, "alerts.json"), "{\"enabled\":true,\"threshold\":40}");
    if (AlertPreferences.LoadSettings(directory) != new AlertSettings(false, 20)) throw new InvalidOperationException("损坏的提醒设置应安全关闭");
    try { AlertPreferences.Save(directory, new AlertSettings(true, 40)); throw new InvalidOperationException("不支持的阈值不能保存"); }
    catch (ArgumentException) { }
    AlertPreferences.Save(directory, new AlertSettings(false, 30, true));
    AlertPreferences.Save(directory, true);
    if (AlertPreferences.LoadSettings(directory) != new AlertSettings(true, 30, true)) throw new InvalidOperationException("额度开关不能覆盖到期提醒");
    File.WriteAllText(Path.Combine(directory, "alerts.json"), "{\"enabled\":true,\"threshold\":20,\"reset_cards_enabled\":\"bad\"}");
    if (AlertPreferences.LoadSettings(directory) != new AlertSettings(false, 20)) throw new InvalidOperationException("损坏的到期提醒设置应安全关闭");
    if (RefreshIntervalPreferences.Load(directory) != 15) throw new InvalidOperationException("默认刷新间隔应为 15 分钟");
    RefreshIntervalPreferences.Save(directory, 30);
    if (RefreshIntervalPreferences.Load(directory) != 30) throw new InvalidOperationException("刷新间隔未保存");
    try { RefreshIntervalPreferences.Save(directory, 7); throw new InvalidOperationException("不支持的刷新间隔不能保存"); }
    catch (ArgumentException) { }
    File.WriteAllText(Path.Combine(directory, "refresh.json"), "{\"minutes\":true}");
    if (RefreshIntervalPreferences.Load(directory) != 15) throw new InvalidOperationException("无效刷新设置应使用默认值");
    if (ForecastPreferences.Load(directory)) throw new InvalidOperationException("第三方预测首次应默认关闭");
    ForecastPreferences.Save(directory, true);
    if (!ForecastPreferences.Load(directory)) throw new InvalidOperationException("第三方预测设置未保存");
    File.WriteAllText(Path.Combine(directory, "forecast-preferences.json"), "{invalid");
    if (ForecastPreferences.Load(directory)) throw new InvalidOperationException("损坏的预测设置必须保持关闭");
    if (PetPreferences.Load(directory).Enabled) throw new InvalidOperationException("桌宠首次应默认隐藏");
    var petSettings = new PetPreferences(true, "bit", -1200, 200);
    petSettings.Save(directory);
    if (PetPreferences.Load(directory) != petSettings) throw new InvalidOperationException("桌宠设置未正确保存");
    var followPet = new PetPreferences(true, "cat", 10, 20, true);
    followPet.Save(directory);
    if (PetPreferences.Load(directory) != followPet) throw new InvalidOperationException("视线跟随设置未正确保存");
    File.WriteAllText(Path.Combine(directory, "pet-settings.json"), "{\"enabled\":true,\"pack\":\"cat\",\"follow_cursor\":\"invalid\"}");
    if (PetPreferences.Load(directory).FollowCursor) throw new InvalidOperationException("异常视线跟随设置必须默认关闭");
    File.WriteAllText(Path.Combine(directory, "pet-settings.json"), "{\"enabled\":true,\"pack\":\"cat\"}");
    if (PetPreferences.Load(directory).FollowCursor) throw new InvalidOperationException("旧版设置必须默认关闭视线跟随");
    foreach (string pack in new[] { "gauge", "cat", "bot", "tibo", "blob" })
    {
        var threePetSettings = new PetPreferences(true, pack, 30, 40);
        threePetSettings.Save(directory);
        if (PetPreferences.Load(directory) != threePetSettings) throw new InvalidOperationException("3D 桌宠形象未正确保存");
    }
    File.WriteAllText(Path.Combine(directory, "pet-settings.json"), "{\"enabled\":true,\"pack\":\"../other\"}");
    if (PetPreferences.Load(directory).Enabled) throw new InvalidOperationException("桌宠形象必须限制为内置选择");
    File.WriteAllText(Path.Combine(directory, "pet-settings.json"), "broken");
    if (PetPreferences.Load(directory).Enabled) throw new InvalidOperationException("损坏的桌宠设置应默认隐藏");
    var petActions = new PetInteractionQueue();
    petActions.Add("drag-start"); petActions.Add("drag-end"); petActions.Add("poke");
    if (petActions.Take() != "drag-start" || petActions.Take() != "drag-end" || petActions.Take() != "poke" || petActions.Take() is not null)
        throw new InvalidOperationException("桌宠动作队列顺序错误");
    for (int i = 0; i < 16; i++) petActions.Add("poke");
    petActions.Add("refresh");
    if (petActions.Take() != "drag-end" || petActions.Take() != "refresh" || petActions.Take() is not null)
        throw new InvalidOperationException("动作堆积时必须释放拖动状态并保留最新动作");
    for (int i = 0; i < 16; i++) petActions.Add("poke");
    petActions.Add("drag-end");
    if (petActions.Take() != "drag-end" || petActions.Take() is not null)
        throw new InvalidOperationException("动作堆积时的放下操作不能丢失或重复");
    var alerts = new QuotaAlerts();
    JsonElement Snapshot(double remaining, long reset, string status = "available", long observed = 1800000000) => JsonSerializer.SerializeToElement(new
    {
        observed_at = observed,
        account = new { status, quota = new { value = new[] { new { bucket = "primary", window_minutes = 300,
            remaining_percent = remaining, resets_at = new { epoch_seconds = reset } } } } }
    });
    var now = DateTimeOffset.FromUnixTimeSeconds(1800000000);
    if (alerts.Evaluate(Snapshot(20, 1800003600), now).Count != 0 || alerts.Evaluate(Snapshot(19, 1800003600), now).Count != 1 ||
        alerts.Evaluate(Snapshot(15, 1800003600), now).Count != 0 || alerts.Evaluate(Snapshot(15, 1800003601), now.AddMinutes(1)).Count != 0 ||
        alerts.Evaluate(Snapshot(15, 1800003601), now.AddMinutes(16)).Count != 1)
        throw new InvalidOperationException("低额度提醒阈值、去重或重置周期错误");
    if (alerts.Evaluate(Snapshot(35, 1800003601), now.AddMinutes(17)).Count != 0 || alerts.Evaluate(Snapshot(10, 1800003601), now.AddMinutes(17)).Count != 1 ||
        alerts.Evaluate(Snapshot(10, 1800003602, "disabled"), now.AddMinutes(17)).Count != 0)
        throw new InvalidOperationException("额度恢复或关闭来源后的提醒错误");
    var thresholdAlerts = new QuotaAlerts();
    if (thresholdAlerts.Evaluate(Snapshot(30, 1800003600), now, 30).Count != 0 ||
        thresholdAlerts.Evaluate(Snapshot(29, 1800003600), now, 30).Count != 1 ||
        thresholdAlerts.Evaluate(Snapshot(40, 1800003600), now, 30).Count != 0 ||
        thresholdAlerts.Evaluate(Snapshot(29, 1800003600), now, 30).Count != 1 ||
        new QuotaAlerts().Evaluate(Snapshot(9, 1800003600), now, 10).Count != 1 ||
        new QuotaAlerts().Evaluate(Snapshot(49, 1800003600), now, 50).Count != 1 ||
        new QuotaAlerts().Evaluate(Snapshot(9, 1800003600), now, 40).Count != 0)
        throw new InvalidOperationException("自定义阈值、边界或恢复后重新提醒错误");
    if (new QuotaAlerts().Evaluate(Snapshot(5, 1800003600, observed: 1799998199), now).Count != 0 ||
        new QuotaAlerts().Evaluate(Snapshot(5, 1800003600, observed: 1800000301), now).Count != 0 ||
        new QuotaAlerts().Evaluate(Snapshot(5, 1800000000), now).Count != 0 ||
        new QuotaAlerts().Evaluate(JsonSerializer.SerializeToElement(new { account = new { status = "available" } }), now).Count != 0)
        throw new InvalidOperationException("过期、未来、缺失或已重置的快照不能提醒");
    JsonElement CardSnapshot(long observed, params (string Status, long Expiry)[] cards) => JsonSerializer.SerializeToElement(new
    {
        observed_at = observed, account = new { status = "available", reset_cards = new { status = "available", value = new {
            available_count = cards.Length, cards = cards.Select(c => new { status = c.Status, expires_at = new { epoch_seconds = c.Expiry } }).ToArray()
        } } }
    });
    var cardAlerts = new ResetCardAlerts();
    var expiry = now.ToUnixTimeSeconds() + 2 * 86400;
    var cardData = CardSnapshot(now.ToUnixTimeSeconds(), ("available", expiry), ("available", expiry),
                                ("redeemed", expiry), ("available", now.ToUnixTimeSeconds() - 1));
    if (!cardAlerts.Evaluate(cardData, now).Single().Contains("2 张") || cardAlerts.Evaluate(cardData, now).Count != 0 ||
        !cardAlerts.Evaluate(CardSnapshot(now.AddDays(1).ToUnixTimeSeconds(), ("available", expiry)), now.AddDays(1)).Single().Contains("1 天") ||
        cardAlerts.Evaluate(CardSnapshot(now.AddDays(2).ToUnixTimeSeconds(), ("available", expiry)), now.AddDays(2)).Count != 0 ||
        new ResetCardAlerts().Evaluate(CardSnapshot(now.ToUnixTimeSeconds() - 1801, ("available", expiry)), now).Count != 0)
        throw new InvalidOperationException("重置卡到期阶段、去重、状态或快照时效错误");
    var fallbackCard = JsonSerializer.SerializeToElement(new { observed_at = now.ToUnixTimeSeconds(), account = new { status = "available", reset_cards = new { value = new {
        available_count = 5, next_known_expiry = new { epoch_seconds = expiry }
    } } } });
    if (!new ResetCardAlerts().Evaluate(fallbackCard, now).Single().Contains("有重置卡"))
        throw new InvalidOperationException("仅有最近到期时间时不能推断到期张数");
    using var disabledCard = JsonDocument.Parse("""{"observed_at":1800000000,"account":{"status":"disabled","reset_cards":{"value":{"available_count":1,"cards":[{"status":"available","expires_at":{"epoch_seconds":1800003600}}]}}}}""");
    using var failedCards = JsonDocument.Parse("""{"observed_at":1800000000,"account":{"status":"available","reset_cards":{"status":"error","value":{"available_count":1,"cards":[{"status":"available","expires_at":{"epoch_seconds":1800003600}}]}}}}""");
    if (new ResetCardAlerts().Evaluate(disabledCard.RootElement, now).Count != 0 ||
        new ResetCardAlerts().Evaluate(failedCards.RootElement, now).Count != 0 ||
        new ResetCardAlerts().Evaluate(CardSnapshot(now.ToUnixTimeSeconds() + 301, ("available", expiry)), now).Count != 0)
        throw new InvalidOperationException("关闭账户、读取失败或未来快照不能触发到期提醒");
    var kimi = JsonSerializer.SerializeToElement(new { observed_at = 1800000000L, other_accounts = new Dictionary<string, object> {
        ["Kimi Code"] = new { status = "available", quota = new { value = new[] { new { bucket = "monthTotal", remaining_percent = 10 } } } }
    } });
    if (!new QuotaAlerts().Evaluate(kimi, now).Single().Contains("月度总额"))
        throw new InvalidOperationException("Kimi 月度额度提醒应显示中文名称");
    var minimax = JsonSerializer.SerializeToElement(new { observed_at = 1800000000L, other_accounts = new Dictionary<string, object> {
        ["MiniMax Code"] = new { status = "available", quota = new { value = new[] { new { bucket = "5h", remaining_percent = 10 } } } }
    } });
    if (!new QuotaAlerts().Evaluate(minimax, now).Single().Contains("5 小时"))
        throw new InvalidOperationException("MiniMax 额度提醒应显示中文周期");
    var workbuddy = JsonSerializer.SerializeToElement(new { observed_at = 1800000000L, other_accounts = new Dictionary<string, object> {
        ["WorkBuddy"] = new { status = "available", quota = new { value = new[] { new { bucket = "credits", remaining_percent = 10 } } } }
    } });
    if (!new QuotaAlerts().Evaluate(workbuddy, now).Single().Contains("积分额度"))
        throw new InvalidOperationException("WorkBuddy 提醒应显示积分额度");
    using var qoderAlert = JsonDocument.Parse("""{"observed_at":1800000000,"other_accounts":{"Qoder CN":{"status":"available","quota":{"value":[{"bucket":"totalQuota","remaining_percent":10}]}}}}""");
    if (!new QuotaAlerts().Evaluate(qoderAlert.RootElement, now).Single().Contains("账户额度"))
        throw new InvalidOperationException("Qoder 提醒应显示账户额度");
    using var traeAlert = JsonDocument.Parse("""{"observed_at":1800000000,"other_accounts":{"TRAE CN":{"status":"available","quota":{"value":[{"bucket":"credits","remaining_percent":10}]}}}}""");
    if (!new QuotaAlerts().Evaluate(traeAlert.RootElement, now).Single().Contains("TRAE CN 积分额度"))
        throw new InvalidOperationException("TRAE 提醒应显示积分额度");
    using var zcodeAlert = JsonDocument.Parse("""{"observed_at":1800000000,"other_accounts":{"ZCode":{"status":"available","quota":{"value":[{"bucket":"quota","limit_type":"TOKENS_LIMIT","window_minutes":300,"remaining_percent":10},{"bucket":"quota","limit_type":"CREDIT_LIMIT","window_minutes":300,"remaining_percent":15},{"bucket":"mcp","limit_type":"TIME_LIMIT","remaining_percent":5}]}}}}""");
    var zcodeMessages = new QuotaAlerts().Evaluate(zcodeAlert.RootElement, now);
    if (zcodeMessages.Count != 3 || !zcodeMessages.Any(text => text.Contains("MCP 调用")) || !zcodeMessages.Any(text => text.Contains("Token")))
        throw new InvalidOperationException("智谱不同额度类型的提醒不能互相覆盖");
    var multiMiniMax = JsonSerializer.SerializeToElement(new { observed_at = 1800000000L, other_accounts = new Dictionary<string, object> {
        ["MiniMax Code"] = new[] {
            new { label = "甲", status = "available", quota = new { value = new[] { new { bucket = "5h", remaining_percent = 10 } } } },
            new { label = "乙", status = "available", quota = new { value = new[] { new { bucket = "5h", remaining_percent = 15 } } } }
        }
    } });
    if (new QuotaAlerts().Evaluate(multiMiniMax, now).Count != 2)
        throw new InvalidOperationException("不同 MiniMax 账户的提醒应独立计数");
    using var quotaData = JsonDocument.Parse("""
    {"quota":{"value":[{"bucket":"seven_day_opus","window_minutes":10080,"remaining_percent":5},
      {"bucket":"seven_day","window_minutes":10080,"remaining_percent":46},
      {"bucket":"five_hour","window_minutes":300,"remaining_percent":73}]}}
    """);
    var pair = QuotaWindows.Select(quotaData.RootElement);
    if (pair?.Primary.Remaining != 73 || pair.Secondary?.Remaining != 46 || pair.Secondary.Label != "7 天")
        throw new InvalidOperationException("额度仪表应配对通用短周期和七天周期");
    using var singleQuota = JsonDocument.Parse("""
    {"quota":{"value":[{"bucket":"seven_day_opus","window_minutes":10080,"remaining_percent":15},
      {"bucket":"bad","remaining_percent":120}]}}
    """);
    var single = QuotaWindows.Select(singleQuota.RootElement);
    if (single?.Primary.Label != "7 天 Opus" || single.Secondary is not null)
        throw new InvalidOperationException("单独额度或异常百分比处理错误");
    using var kimiPair = JsonDocument.Parse("""
    {"quota":{"value":[{"bucket":"monthTotal","remaining_percent":80},
      {"bucket":"limit7d","remaining_percent":42}, {"bucket":"limit5h","remaining_percent":64}]}}
    """);
    var kimiWindows = QuotaWindows.Select(kimiPair.RootElement);
    if (kimiWindows?.Primary.Remaining != 64 || kimiWindows.Secondary?.Remaining != 42)
        throw new InvalidOperationException("Kimi 月度额度不应代替短周期或七天周期");
    using var reportData = JsonDocument.Parse("""
    {"account":{"credential":"synthetic-secret"},"history":{"message":"synthetic-private-text"},"calendar_report":{"incomplete":true,"periods":{
      "week":{"previous_start":"2025-12-22","current_start":"2025-12-29","current_end":"2026-01-01","previous_tokens":50,"current_tokens":300},
      "month":{"previous_start":"2025-12-01","current_start":"2026-01-01","current_end":"2026-01-01","previous_tokens":180,"current_tokens":200}}}}
    """);
    string exported = CalendarReportExport.Create(reportData.RootElement, demo: true);
    if (!exported.Contains("虚构演示数据") || !exported.Contains("2025-12-28") || !exported.Contains("300 Token") ||
        !exported.Contains("部分来源") || exported.Contains("synthetic-secret") || exported.Contains("synthetic-private-text"))
        throw new InvalidOperationException("报告导出内容或隐私边界不正确");
    var originalCulture = System.Globalization.CultureInfo.CurrentCulture;
    try
    {
        System.Globalization.CultureInfo.CurrentCulture = System.Globalization.CultureInfo.GetCultureInfo("ar-SA");
        if (!CalendarReportExport.Create(reportData.RootElement).Contains("2025-12-28"))
            throw new InvalidOperationException("报告日期不应随系统区域设置改变");
    }
    finally { System.Globalization.CultureInfo.CurrentCulture = originalCulture; }
    using var share = ShareCardRenderer.Render(reportData.RootElement, VisualThemes.Find("aurora"), demo: true);
    using var lightShare = ShareCardRenderer.Render(reportData.RootElement, VisualThemes.Find("porcelain"), demo: true);
    if (share.Width != 1200 || share.Height != 860 || share.GetPixel(5, 5) == lightShare.GetPixel(5, 5))
        throw new InvalidOperationException("分享图尺寸或主题配色不正确");
    if (args.Length == 2 && args[0] == "--render-demo")
        share.Save(args[1], System.Drawing.Imaging.ImageFormat.Png);
    if (args.Length == 2 && args[0] == "--render-demo-light")
        lightShare.Save(args[1], System.Drawing.Imaging.ImageFormat.Png);
    using var mochi = new SpritePet("mochi");
    using var bit = new SpritePet("bit");
    var idlePet = mochi.Frame("idle", 0, 240);
    if (mochi.FrameCount("idle") != 4 || bit.FrameCount("working") != 4 ||
        bit.FrameCount("unknown") != bit.FrameCount("idle") || idlePet.GetPixel(0, 0).A != 0)
        throw new InvalidOperationException("桌宠动画清单或透明背景不正确");
    int opaquePixels = 0;
    for (int y = 0; y < idlePet.Height; y++)
        for (int x = 0; x < idlePet.Width; x++)
            if (idlePet.GetPixel(x, y).A > 0) opaquePixels++;
    if (opaquePixels == 0 || opaquePixels >= idlePet.Width * idlePet.Height / 2)
        throw new InvalidOperationException("桌宠图像应有可见角色和透明区域");
    foreach (var sprite in new[] { mochi, bit })
        foreach (string animation in new[] { "idle", "working", "tired", "alarm", "sleeping", "celebrate", "offline", "waiting" })
        {
            var image = sprite.Frame(animation, sprite.FrameCount(animation) - 1, 240);
            if (image.Width != 240 || image.Height != 240 || image.GetPixel(0, 0).A != 0)
                throw new InvalidOperationException("桌宠动画资源尺寸或透明度不正确");
        }
    if (args.Length == 2 && args[0] == "--render-pet") idlePet.Save(args[1], System.Drawing.Imaging.ImageFormat.Png);
    using var noPetData = JsonDocument.Parse("{}");
    if (PetState.Select(noPetData.RootElement, 10000).Animation != "idle") throw new InvalidOperationException("缺失额度不能显示耗尽");
    using var lowPetData = JsonDocument.Parse("""
    {"observed_at":10000,"other_accounts":{"MiniMax Code":[{"status":"available","quota":{"value":[{"remaining_percent":10,"resets_at":{"epoch_seconds":11000}}]}}]}}
    """);
    if (PetState.Select(lowPetData.RootElement, 10030).Animation != "alarm" || PetState.Select(lowPetData.RootElement, 11001).Animation != "idle" ||
        PetState.Select(lowPetData.RootElement, 11201).Animation != "idle")
        throw new InvalidOperationException("桌宠应识别低额度，并忽略过期快照");
    if (PetState.Select(lowPetData.RootElement, 10030).Remaining != 10 || PetState.Select(lowPetData.RootElement, 11001).Remaining is not null ||
        PetState.Select(noPetData.RootElement, 10000).Remaining is not null)
        throw new InvalidOperationException("桌宠额度应只使用新鲜且未重置的真实数据");
    using var multiplePetData = JsonDocument.Parse("""
    {"observed_at":10000,"account":{"status":"available","quota":{"value":[{"remaining_percent":87},{"remaining_percent":101}]}},"other_accounts":{"A":{"status":"available","quota":{"value":[{"remaining_percent":42},{"remaining_percent":-1}]}}}}
    """);
    if (PetState.Select(multiplePetData.RootElement, 10001).Remaining != 42 || PetState.Select(multiplePetData.RootElement, 11201).Remaining is not null)
        throw new InvalidOperationException("桌宠应使用有效额度的最小值并忽略异常及过期数据");
    using var activePetData = JsonDocument.Parse("""
    {"activity":{"status":"available","apps":[{"last_updated":9500}]}}
    """);
    if (PetState.Select(activePetData.RootElement, 10000).Animation != "working" ||
        PetState.Select(activePetData.RootElement, 10401).Animation != "idle")
        throw new InvalidOperationException("桌宠近期活动状态应随时间失效");
    if (Environment.GetEnvironmentVariable("AGENT_METER_TEST_PET_WINDOW") == "1")
    {
        Exception? windowError = null;
        var thread = new Thread(() =>
        {
            try
            {
                using var petWindow = new PetWindow("mochi", new Point(-32000, -32000));
                bool failed = false;
                petWindow.RenderingFailed += () => failed = true;
                petWindow.Show(); Application.DoEvents();
                if (failed || !petWindow.IsHandleCreated) throw new InvalidOperationException("桌宠悬浮窗初始化失败");
                petWindow.Close();
            }
            catch (Exception ex) { windowError = ex; }
        });
        thread.SetApartmentState(ApartmentState.STA); thread.Start();
        if (!thread.Join(TimeSpan.FromSeconds(15)) || windowError is not null)
            throw new InvalidOperationException("桌宠悬浮窗检查失败", windowError);
    }
    var screen = new Rectangle(0, 0, 1920, 1080);
    var panel = new Size(500, 700);
    void Position(Rectangle bounds, Rectangle work, Point cursor, Point expected)
    {
        Point actual = PanelPlacement.Find(bounds, work, panel, cursor, true);
        if (actual != expected) throw new InvalidOperationException($"面板位置错误：{actual}，应为 {expected}");
    }
    Position(screen, new Rectangle(0, 0, 1920, 1040), new Point(1900, 1060), new Point(1408, 328));
    Position(screen, new Rectangle(0, 40, 1920, 1040), new Point(100, 5), new Point(12, 52));
    Position(screen, new Rectangle(40, 0, 1880, 1080), new Point(5, 500), new Point(52, 150));
    Position(screen, new Rectangle(0, 0, 1880, 1080), new Point(1910, 500), new Point(1368, 150));
    Position(new Rectangle(-1920, 0, 1920, 1080), new Rectangle(-1920, 0, 1920, 1040),
             new Point(-10, 1060), new Point(-512, 328));
    foreach (var (edge, cursor, expected) in new[] {
        (TaskbarEdge.Left, new Point(1, 500), new Point(12, 150)),
        (TaskbarEdge.Right, new Point(1918, 500), new Point(1408, 150)),
        (TaskbarEdge.Top, new Point(500, 1), new Point(250, 12)),
        (TaskbarEdge.Bottom, new Point(1900, 1078), new Point(1408, 368)) })
        if (PanelPlacement.Find(screen, screen, panel, cursor, true, edge) != expected)
            throw new InvalidOperationException("自动隐藏任务栏方向定位错误：" + edge);
    var secondScreen = new Rectangle(-1920, 0, 1920, 1080);
    if (PanelPlacement.Find(secondScreen, secondScreen, panel, new Point(-1, 500), true, TaskbarEdge.Right) != new Point(-512, 150))
        throw new InvalidOperationException("负坐标屏幕的自动隐藏任务栏定位错误");
    int queried = 0;
    var detected = TaskbarLocation.ResolveAutoHide(secondScreen, (edge, bounds) => {
        if (bounds != secondScreen) throw new InvalidOperationException("任务栏查询屏幕错误");
        queried++; return edge is TaskbarEdge.Left or TaskbarEdge.Right ? new IntPtr((int)edge + 1) : IntPtr.Zero;
    }, handle => handle == new IntPtr(1) ? "ThirdPartyBar" : "Shell_SecondaryTrayWnd");
    if (detected != TaskbarEdge.Right || queried != 3) throw new InvalidOperationException("应忽略第三方自动隐藏工具栏并识别副屏任务栏");
    if (TaskbarLocation.ResolveAutoHide(screen, (_, _) => IntPtr.Zero, _ => "") is not null)
        throw new InvalidOperationException("无自动隐藏任务栏时应使用工作区定位");
    if (TaskbarLocation.ResolvePrimary(screen, new Rectangle(0, -38, 1920, 40), TaskbarEdge.Top) != TaskbarEdge.Top ||
        TaskbarLocation.ResolvePrimary(secondScreen, new Rectangle(0, 1040, 1920, 40), TaskbarEdge.Bottom) is not null ||
        TaskbarLocation.ResolvePrimary(screen, Rectangle.Empty, TaskbarEdge.Bottom) is not null)
        throw new InvalidOperationException("主屏任务栏回退定位的屏幕判断错误");
    Point oversized = PanelPlacement.Find(screen, new Rectangle(0, 0, 300, 200), new Size(500, 700), Point.Empty, true);
    if (oversized != Point.Empty) throw new InvalidOperationException("超大面板应从工作区左上角开始");
    if (PanelPlacement.Fit(new Size(500, 760), new Rectangle(0, 0, 300, 200)) != new Size(276, 176))
        throw new InvalidOperationException("面板应适应较小工作区");
    if (PanelPlacement.Fit(new Size(500, 760), new Rectangle(0, 0, 1920, 1040)) != new Size(500, 760))
        throw new InvalidOperationException("足够大的工作区不应改变面板尺寸");
    Console.WriteLine("账户、面板、主题、价格、提醒、报告和桌宠基础检查通过");
}
finally
{
    if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
}

internal sealed class FakeMiniMaxVault : IMiniMaxVault
{
    readonly Dictionary<Guid, string> values = new();
    public bool FailWrite { get; set; }
    public bool FailDelete { get; set; }
    public bool FailRead { get; set; }
    public void Write(Guid id, string secret) { if (FailWrite) throw new IOException("synthetic write failure"); values[id] = secret; }
    public string? Read(Guid id) { if (FailRead) throw new IOException("synthetic read failure"); return values.GetValueOrDefault(id); }
    public void Delete(Guid id) { if (FailDelete) throw new IOException("synthetic delete failure"); values.Remove(id); }
}
