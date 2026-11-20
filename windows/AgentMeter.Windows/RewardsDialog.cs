using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>每日积分领取设置与结果；只使用本应用自己的登录会话。</summary>
internal sealed class RewardsDialog : Form
{
    readonly MeterWindow owner;
    readonly CheckBox enabled = new() { Name = "rewards-enabled", Text = "自动领取每日积分", AutoSize = true, Margin = new Padding(0, 6, 0, 0) };
    readonly ComboBox clock = new() { Name = "rewards-clock", DropDownStyle = ComboBoxStyle.DropDownList, Width = 86 };
    readonly ListView list = new() { Name = "rewards-status", View = View.Details, FullRowSelect = true, MultiSelect = false, HideSelection = false };
    readonly Label message = new() { Name = "rewards-message", ForeColor = Color.DimGray, AutoSize = false, Height = 42, Dock = DockStyle.Bottom, Padding = new Padding(16, 2, 16, 0) };
    readonly Label note = new() { Name = "rewards-note", ForeColor = Color.DimGray, AutoSize = false, Height = 34, Dock = DockStyle.Bottom, Padding = new Padding(16, 0, 16, 0) };
    readonly Button claim = new() { Name = "rewards-claim", Text = "立即领取", AutoSize = true };
    readonly Button save = new() { Name = "rewards-save", Text = "保存", AutoSize = true };
    bool working;

    public RewardsDialog(MeterWindow owner)
    {
        this.owner = owner;
        Text = "每日积分领取"; StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
        Font = new Font("Microsoft YaHei UI", 10F); ClientSize = new Size(760, 520); MinimumSize = new Size(700, 460);
        var description = new Label
        {
            Dock = DockStyle.Top, Height = 96, Padding = new Padding(16, 10, 16, 0),
            Text = "每天在设定时刻尝试领取一次：TRAE 每日签到、WorkBuddy 已完成的成长任务。\n" +
                   "只使用本应用已登录的账户会话；会话只在内存中交给后台进程，不落盘、不进入日志。\n" +
                   "Qoder 每日活动只认 macOS 桌面客户端凭据，Windows 暂不支持，也不会拿网页 Cookie 假装领取。"
        };
        var settings = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 40, Padding = new Padding(16, 4, 16, 0), WrapContents = false };
        var clockLabel = new Label { Text = "领取时刻", AutoSize = true, Margin = new Padding(18, 7, 6, 0) };
        settings.Controls.AddRange([enabled, clockLabel, clock]);
        list.Columns.Add("账户", 190);
        list.Columns.Add("今日", 150);
        list.Columns.Add("今日已领", 90);
        list.Columns.Add("上次检查", 150);
        list.Columns.Add("说明", 160);
        var listHost = new Panel { Dock = DockStyle.Fill, Padding = new Padding(16, 6, 16, 0) };
        listHost.Controls.Add(list);
        note.Text = "状态优先读自本机账本；点「立即领取」才会请求账户。今天尚未结束时不会伪造领取结果。";
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 56, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        var cancel = new Button { Text = "关闭", AutoSize = true, DialogResult = DialogResult.Cancel };
        claim.Click += async (_, _) => await RefreshAsync(claimNow: true);
        save.Click += (_, _) => SaveSettings();
        buttons.Controls.AddRange([cancel, save, claim]);
        Controls.Add(listHost); Controls.Add(settings); Controls.Add(description); Controls.Add(note); Controls.Add(message); Controls.Add(buttons);
        AcceptButton = save; CancelButton = cancel;
        Shown += async (_, _) => await RefreshAsync(claimNow: false);
        try
        {
            var saved = RewardPreferences.Load(AccountPreferences.DefaultDirectory);
            enabled.Checked = saved.Enabled;
            clock.Items.AddRange(RewardPreferences.Choices.Cast<object>().ToArray());
            if (!RewardPreferences.Choices.Contains(saved.ClaimTime)) clock.Items.Add(saved.ClaimTime);
            clock.SelectedItem = saved.ClaimTime;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            message.Text = "领取设置无法读取；本次保持关闭。";
            enabled.Checked = false;
        }
    }

    RewardSettings? ReadSettings()
    {
        if (clock.SelectedItem is not string time || !RewardPreferences.ValidClock(time))
        {
            message.Text = "领取时刻格式应为 HH:MM。";
            return null;
        }
        return new RewardSettings(enabled.Checked, time);
    }

    async Task RefreshAsync(bool claimNow)
    {
        if (working) return;
        var settings = ReadSettings();
        if (settings is null) return;
        working = true; SetWorking(true);
        message.Text = claimNow ? "正在领取…" : "正在读取本机账本…";
        try
        {
            string json = claimNow ? await owner.ClaimRewardsAsync(settings, claimAll: true) : await owner.RewardStatusAsync(settings);
            Fill(json);
            message.Text = claimNow ? ClaimMessage(json) : "状态只读自本机账本；点「立即领取」才会请求账户。";
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or JsonException or
            System.ComponentModel.Win32Exception or OperationCanceledException or ObjectDisposedException)
        { message.Text = "无法读取领取状态，请稍后重试。"; }
        finally { working = false; SetWorking(false); }
    }

    void Fill(string json)
    {
        var rows = RewardsReport.Read(json);
        list.BeginUpdate();
        try
        {
            list.Items.Clear();
            if (rows.Count == 0)
            {
                var empty = new ListViewItem("暂无领取记录");
                for (int index = 0; index < 4; index++) empty.SubItems.Add("—");
                list.Items.Add(empty);
                return;
            }
            foreach (var row in rows)
            {
                var item = new ListViewItem(row.Title);
                item.SubItems.Add(row.Today); item.SubItems.Add(row.Claimed);
                item.SubItems.Add(row.Checked); item.SubItems.Add(row.Detail);
                if (row.Id.StartsWith("unsupported:", StringComparison.Ordinal)) item.ForeColor = Color.DimGray;
                list.Items.Add(item);
            }
        }
        finally { list.EndUpdate(); }
    }

    static string ClaimMessage(string json)
    {
        int total = 0;
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            string status = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("status", out var state) &&
                state.ValueKind == JsonValueKind.String ? state.GetString() ?? "" : "";
            string reason = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("reason", out var why) &&
                why.ValueKind == JsonValueKind.String ? why.GetString() ?? "" : "";
            if (status == "error" && reason == "rewards_session_unavailable")
                return "没有可用的 TRAE / WorkBuddy 登录会话；请先在账户查询里登录。";
            var accounts = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("accounts", out var value) ? value : default;
            if (accounts.ValueKind == JsonValueKind.Array)
                foreach (var account in accounts.EnumerateArray())
                    if (account.ValueKind == JsonValueKind.Object && account.TryGetProperty("claimed_credits_today", out var credits) &&
                        credits.ValueKind == JsonValueKind.Number && credits.TryGetInt32(out int amount) && amount > 0)
                        total += amount;
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException or OverflowException) { }
        return total > 0 ? $"今日累计已领取 {total} 积分。" : "本次没有可领取的项目（今天可能已经领过，或账户尚未登录）。";
    }

    void SetWorking(bool active)
    {
        enabled.Enabled = clock.Enabled = claim.Enabled = save.Enabled = !active;
        UseWaitCursor = active;
    }

    void SaveSettings()
    {
        var settings = ReadSettings();
        if (settings is null) return;
        try
        {
            RewardPreferences.Save(AccountPreferences.DefaultDirectory, settings);
            owner.ReloadRewardSettings();
            DialogResult = DialogResult.OK; Close();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException or ArgumentException)
        { message.Text = "无法保存领取设置，请检查本地设置目录权限。"; }
    }
}
