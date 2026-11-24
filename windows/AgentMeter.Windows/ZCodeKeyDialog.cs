using System.ComponentModel;

using static AgentMeter.Windows.UiScale;

namespace AgentMeter.Windows;

/// <summary>只接受用户主动输入的查询密钥，不回显已保存的凭据。</summary>
internal sealed class ZCodeKeyDialog : Form
{
    readonly TextBox secret = new();
    readonly Label message = new();
    public bool Deleted { get; private set; }
    public ZCodeKeyDialog()
    {
        Text = "智谱 GLM Coding Plan"; StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Microsoft YaHei UI", 10F); ClientSize = Sz(560, 250); MinimumSize = Sz(480, 250);
        var description = new Label { Dock = DockStyle.Top, Height = S(88), Padding = Pad(16, 12, 16, 0),
            Text = "只查询智谱 Coding Plan 额度，不发送提示词。\n密钥保存在 Windows 凭据管理器；保存后启用查询，已保存密钥不会回显。" };
        var fields = new Panel { Dock = DockStyle.Top, Height = S(60), Padding = Pad(16, 0, 16, 0) };
        var label = new Label { Text = "Coding Plan API 密钥", Dock = DockStyle.Top, Height = S(22)};
        secret.Dock = DockStyle.Top; secret.UseSystemPasswordChar = true; secret.MaxLength = 1280;
        secret.PlaceholderText = "输入智谱 Coding Plan 密钥"; fields.Controls.Add(secret); fields.Controls.Add(label);
        message.Dock = DockStyle.Top; message.Height = S(30); message.Padding = Pad(S(16), S(0), S(16), S(0)); message.ForeColor = Color.Firebrick;
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = S(58), FlowDirection = FlowDirection.RightToLeft, Padding = Pad(8) };
        var cancel = new Button { Text = "取消", AutoSize = true, DialogResult = DialogResult.Cancel };
        var remove = new Button { Text = "删除已保存密钥", AutoSize = true };
        var save = new Button { Text = "保存并启用", AutoSize = true };
        save.Click += (_, _) => {
            string key = secret.Text;
            if (!ZCodeKeyStore.IsValid(key)) { message.Text = "请输入有效密钥，不能包含空白字符。"; return; }
            try { ZCodeKeyStore.Save(key); secret.Clear(); DialogResult = DialogResult.OK; Close(); }
            catch (Exception ex) when (ex is Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException or ArgumentException)
            { message.Text = "无法保存密钥，请检查 Windows 凭据管理器。"; }
        };
        remove.Click += (_, _) => {
            try { ZCodeKeyStore.Delete(); secret.Clear(); Deleted = true; DialogResult = DialogResult.OK; Close(); }
            catch (Exception ex) when (ex is Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException)
            { message.Text = "无法删除密钥，请检查 Windows 凭据管理器。"; }
        };
        buttons.Controls.AddRange([cancel, remove, save]); Controls.Add(buttons); Controls.Add(message); Controls.Add(fields); Controls.Add(description);
        AcceptButton = save; CancelButton = cancel; FormClosed += (_, _) => secret.Clear();
    }
}
