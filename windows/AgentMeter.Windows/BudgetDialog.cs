using System.Globalization;

namespace AgentMeter.Windows;

/// <summary>日／周预算均为人民币 API 等价估算，不代表实际账单。</summary>
internal sealed class BudgetDialog : Form
{
    readonly string directory;
    readonly CheckBox enabled = new() { Name = "budget-enabled", Text = "启用预算进度", AutoSize = true };
    readonly CheckBox alerts = new() { Name = "budget-alerts", Text = "启用预算与异常速度通知", AutoSize = true };
    readonly TextBox daily = new() { Name = "budget-daily", PlaceholderText = "留空表示不设置" };
    readonly TextBox weekly = new() { Name = "budget-weekly", PlaceholderText = "留空表示不设置" };
    readonly TextBox multiplier = new() { Name = "budget-multiplier", Text = "2" };
    readonly Label message = new() { Name = "budget-message", ForeColor = Color.Firebrick, AutoSize = false, Height = 35, Dock = DockStyle.Bottom };
    readonly Button save = new() { Name = "budget-save", Text = "保存", AutoSize = true };

    public BudgetDialog(string directory)
    {
        this.directory = directory;
        Text = "预算与异常提醒"; StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Microsoft YaHei UI", 10F); ClientSize = new Size(540, 420); MinimumSize = new Size(500, 420);
        var description = new Label { Dock = DockStyle.Top, Height = 110, Padding = new Padding(16, 10, 16, 0),
            Text = "预算基于本机 Token 与价格表计算的 API 等价估算，并非实际账单。\n按北京时间自然日、自然周统计；美元按固定汇率 1:7.25 换算。\n异常速度与近期日均比较；当日不足 2 小时或数据不完整时不提醒。" };
        var form = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 5, Padding = new Padding(16, 0, 16, 0) };
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 145)); form.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        for (int i = 0; i < 5; i++) form.RowStyles.Add(new RowStyle(SizeType.Absolute, 39));
        form.Controls.Add(enabled, 0, 0); form.SetColumnSpan(enabled, 2);
        form.Controls.Add(new Label { Text = "日预算（元）", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1); form.Controls.Add(daily, 1, 1);
        form.Controls.Add(new Label { Text = "周预算（元）", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 2); form.Controls.Add(weekly, 1, 2);
        form.Controls.Add(new Label { Text = "异常速度倍率", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 3); form.Controls.Add(multiplier, 1, 3);
        form.Controls.Add(alerts, 0, 4); form.SetColumnSpan(alerts, 2);
        daily.Dock = weekly.Dock = multiplier.Dock = DockStyle.Fill;
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 54, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        var cancel = new Button { Text = "取消", AutoSize = true, DialogResult = DialogResult.Cancel };
        save.Click += (_, _) => SaveSettings(); buttons.Controls.AddRange([cancel, save]);
        Controls.Add(form); Controls.Add(message); Controls.Add(buttons); Controls.Add(description);
        AcceptButton = save; CancelButton = cancel;
        enabled.CheckedChanged += (_, _) => alerts.Enabled = enabled.Checked;
        try
        {
            var saved = BudgetPreferences.Load(directory);
            enabled.Checked = saved.Enabled; alerts.Checked = saved.AlertsEnabled;
            daily.Text = saved.Daily?.ToString(CultureInfo.InvariantCulture) ?? "";
            weekly.Text = saved.Weekly?.ToString(CultureInfo.InvariantCulture) ?? "";
            multiplier.Text = saved.Multiplier.ToString(CultureInfo.InvariantCulture);
            alerts.Enabled = saved.Enabled;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { message.Text = "预算设置无法读取；请备份并检查本地设置文件。"; save.Enabled = false; }
    }
    void SaveSettings()
    {
        decimal? ReadOptional(TextBox input)
        {
            if (string.IsNullOrWhiteSpace(input.Text)) return null;
            if (!BudgetPreferences.TryAmount(input.Text, out decimal value)) throw new InvalidDataException();
            return value;
        }
        try
        {
            var day = ReadOptional(daily); var week = ReadOptional(weekly);
            if (!BudgetPreferences.TryAmount(multiplier.Text, out decimal factor) || factor <= 0 || factor > 100)
                throw new InvalidDataException();
            BudgetPreferences.Save(directory, new BudgetSettings(enabled.Checked, alerts.Checked, day, week, factor));
            DialogResult = DialogResult.OK; Close();
        }
        catch (InvalidDataException) { message.Text = "预算须为非负数字，异常倍率须大于 0 且不超过 100。"; }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { message.Text = "无法保存预算设置，请检查本地设置目录权限。"; }
    }
}
