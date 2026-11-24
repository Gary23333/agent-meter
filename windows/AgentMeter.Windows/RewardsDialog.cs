using System.Text.Json;

using static AgentMeter.Windows.UiScale;

namespace AgentMeter.Windows;

/// <summary>每日积分领取：只响应用户点击，不使用自动或定时触发。</summary>
internal sealed class RewardsDialog : Form
{
    readonly MeterWindow owner;
    readonly ListView list = new() { Name = "rewards-status", View = View.Details, FullRowSelect = true, MultiSelect = false, HideSelection = false };
    readonly Label message = new() { Name = "rewards-message", ForeColor = Color.DimGray, AutoSize = false, Height = S(42), Dock = DockStyle.Bottom, Padding = Pad(16, 2, 16, 0) };
    readonly Label note = new() { Name = "rewards-note", ForeColor = Color.DimGray, AutoSize = false, Height = S(34), Dock = DockStyle.Bottom, Padding = Pad(16, 0, 16, 0) };
    readonly Button claim = new() { Name = "rewards-claim", Text = "立即领取", AutoSize = true };
    bool working;

    public RewardsDialog(MeterWindow owner)
    {
        this.owner = owner;
        Text = "每日积分领取"; StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
        Font = new Font("Microsoft YaHei UI", 10F); ClientSize = Sz(760, 500); MinimumSize = Sz(700, 440);
        var description = new Label
        {
            Dock = DockStyle.Top, Height = S(110), Padding = Pad(16, 10, 16, 0),
            Text = "点「立即领取」时才会请求：TRAE 每日签到、WorkBuddy 已完成的成长任务。\n" +
                   "不会自动或定时领取，也不会因为打开窗口就请求账户。\n" +
                   "只使用本应用已登录的账户会话；会话只在内存中交给后台进程，不落盘、不进入日志。\n" +
                   "Qoder 每日活动只认 macOS 桌面客户端凭据，Windows 暂不支持，也不会拿网页 Cookie 假装领取。"
        };
        list.Columns.Add("账户", 190);
        list.Columns.Add("今日", 150);
        list.Columns.Add("今日已领", 90);
        list.Columns.Add("上次检查", 150);
        list.Columns.Add("说明", 160);
        var listHost = new Panel { Dock = DockStyle.Fill, Padding = Pad(16, 6, 16, 0) };
        listHost.Controls.Add(list);
        note.Text = "状态优先读自本机账本；点「立即领取」才会请求账户。领取成功后会在 Windows 通知区提示。";
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = S(56), FlowDirection = FlowDirection.RightToLeft, Padding = Pad(8) };
        var cancel = new Button { Text = "关闭", AutoSize = true, DialogResult = DialogResult.Cancel };
        claim.Click += async (_, _) => await RefreshAsync(claimNow: true);
        buttons.Controls.AddRange([cancel, claim]);
        Controls.Add(listHost); Controls.Add(description); Controls.Add(note); Controls.Add(message); Controls.Add(buttons);
        AcceptButton = claim; CancelButton = cancel;
        Shown += async (_, _) => await RefreshAsync(claimNow: false);
    }

    async Task RefreshAsync(bool claimNow)
    {
        if (working) return;
        working = true; SetWorking(true);
        message.Text = claimNow ? "正在领取…" : "正在读取本机账本…";
        try
        {
            string json = claimNow ? await owner.ClaimRewardsAsync(claimAll: true) : await owner.RewardStatusAsync();
            if (IsDisposed || Disposing) return;
            Fill(json);
            message.Text = claimNow ? ClaimMessage(json) : "状态只读自本机账本；点「立即领取」才会请求账户。";
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or JsonException or
            System.ComponentModel.Win32Exception or OperationCanceledException or ObjectDisposedException)
        {
            if (!IsDisposed && !Disposing) message.Text = "无法读取领取状态，请稍后重试。";
        }
        finally
        {
            working = false;
            if (!IsDisposed && !Disposing) SetWorking(false);
        }
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
        int total = 0, count = 0;
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            string status = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("status", out var state) &&
                state.ValueKind == JsonValueKind.String ? state.GetString() ?? "" : "";
            string reason = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("reason", out var why) &&
                why.ValueKind == JsonValueKind.String ? why.GetString() ?? "" : "";
            if (status == "error") return reason switch
            {
                "rewards_session_unavailable" => "没有可用的 TRAE / WorkBuddy 登录会话；请先在账户查询里登录。",
                "refresh_in_progress" => "正在刷新账户数据，请稍后再领取。",
                "rewards_in_progress" => "已有领取正在进行，请稍后再试。",
                "demo_rewards_disabled" => "演示模式不执行领取。",
                _ => "领取失败，请稍后重试。"
            };
            var accounts = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("accounts", out var value) ? value : default;
            if (accounts.ValueKind == JsonValueKind.Array)
                foreach (var account in accounts.EnumerateArray())
                {
                    if (account.ValueKind != JsonValueKind.Object) continue;
                    var fresh = account.TryGetProperty("claimed_now", out var claimed) && claimed.ValueKind == JsonValueKind.Array
                        ? claimed.GetArrayLength() : 0;
                    count += fresh;
                    if (account.TryGetProperty("claimed_credits_now", out var credits) &&
                        credits.ValueKind == JsonValueKind.Number && credits.TryGetInt32(out int amount) && amount > 0)
                        total += amount;
                }
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException or OverflowException) { }
        if (count > 0) return total > 0 ? $"本次已领取 {total} 积分。" : "本次领取成功，服务未返回积分。";
        return "本次没有新增可领取项目（今天可能已经领过，或账户尚未登录）。";
    }

    void SetWorking(bool active)
    {
        claim.Enabled = !active;
        UseWaitCursor = active;
    }
}
