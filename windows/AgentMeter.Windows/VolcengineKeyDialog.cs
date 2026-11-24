using System.ComponentModel;

using static AgentMeter.Windows.UiScale;

namespace AgentMeter.Windows;

internal sealed class VolcengineKeyDialog : Form
{
    readonly TextBox access = new(), secret = new();
    readonly Label message = new();
    public bool Deleted { get; private set; }
    public VolcengineKeyDialog()
    {
        Text = "火山方舟 Coding Plan"; StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Microsoft YaHei UI", 10F); ClientSize = Sz(580, 320); MinimumSize = Sz(500, 320);
        var description = new Label { Dock = DockStyle.Top, Height = S(100), Padding = Pad(16, 12, 16, 0),
            Text = "使用火山引擎访问控制的 AccessKey 对查询 Coding Plan 额度，不调用模型。\n请使用有相应只读权限的凭据；模型 API 密钥不能用于此查询。\n凭据保存在 Windows 凭据管理器，已保存的内容不会回显。" };
        var fields = new TableLayoutPanel { Dock = DockStyle.Top, Height = S(104), Padding = Pad(16, 0, 16, 0), ColumnCount = 1, RowCount = 4 };
        fields.RowStyles.Add(new RowStyle(SizeType.Absolute, 22)); fields.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        fields.RowStyles.Add(new RowStyle(SizeType.Absolute, 22)); fields.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        fields.Controls.Add(new Label { Text = "AccessKey ID", Dock = DockStyle.Fill }, 0, 0);
        access.Dock = DockStyle.Fill; access.MaxLength = 240; fields.Controls.Add(access, 0, 1);
        fields.Controls.Add(new Label { Text = "SecretAccessKey", Dock = DockStyle.Fill }, 0, 2);
        secret.Dock = DockStyle.Fill; secret.MaxLength = 512; secret.UseSystemPasswordChar = true; fields.Controls.Add(secret, 0, 3);
        message.Dock = DockStyle.Top; message.Height = S(26); message.Padding = Pad(S(16), S(0), S(16), S(0)); message.ForeColor = Color.Firebrick;
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = S(58), FlowDirection = FlowDirection.RightToLeft, Padding = Pad(8) };
        var cancel = new Button { Text = "取消", AutoSize = true, DialogResult = DialogResult.Cancel };
        var remove = new Button { Text = "删除已保存凭据", AutoSize = true };
        var save = new Button { Text = "保存并启用", AutoSize = true };
        save.Click += (_, _) => {
            var keys = new VolcengineKeys(access.Text, secret.Text);
            if (!VolcengineKeyStore.Valid(keys)) { message.Text = "请填写有效的 AccessKey ID 和 SecretAccessKey。"; return; }
            try { VolcengineKeyStore.Save(keys); access.Clear(); secret.Clear(); DialogResult = DialogResult.OK; Close(); }
            catch (Exception ex) when (ex is Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException or ArgumentException)
            { message.Text = "无法保存凭据，请检查 Windows 凭据管理器。"; }
        };
        remove.Click += (_, _) => {
            try { VolcengineKeyStore.Delete(); access.Clear(); secret.Clear(); Deleted = true; DialogResult = DialogResult.OK; Close(); }
            catch (Exception ex) when (ex is Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException)
            { message.Text = "无法删除凭据，请检查 Windows 凭据管理器。"; }
        };
        buttons.Controls.AddRange([cancel, remove, save]); Controls.Add(buttons); Controls.Add(message); Controls.Add(fields); Controls.Add(description);
        AcceptButton = save; CancelButton = cancel; FormClosed += (_, _) => { access.Clear(); secret.Clear(); };
    }
}
