using System.ComponentModel;

namespace AgentMeter.Windows;

/// <summary>用户自行输入 API 密钥；窗口不读取或显示已保存的密钥。</summary>
internal sealed class DeepSeekKeyDialog : Form
{
    readonly TextBox secret = new();
    readonly Label message = new();
    public bool Deleted { get; private set; }

    public DeepSeekKeyDialog()
    {
        Text = "DeepSeek API 余额"; StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Microsoft YaHei UI", 10F); ClientSize = new Size(560, 250); MinimumSize = new Size(480, 250);
        var description = new Label { Dock = DockStyle.Top, Height = 88, Padding = new Padding(16, 12, 16, 0),
            Text = "只查询 DeepSeek API 余额，不发送提示词。\n密钥保存在 Windows 凭据管理器；保存后启用查询，已保存密钥不会回显。" };
        var fields = new Panel { Dock = DockStyle.Top, Height = 60, Padding = new Padding(16, 0, 16, 0) };
        var label = new Label { Text = "API 密钥", Dock = DockStyle.Top, Height = 22 };
        secret.Dock = DockStyle.Top; secret.UseSystemPasswordChar = true; secret.MaxLength = 1280;
        secret.PlaceholderText = "输入 DeepSeek API 密钥"; fields.Controls.Add(secret); fields.Controls.Add(label);
        message.Dock = DockStyle.Top; message.Height = 30; message.Padding = new Padding(16, 0, 16, 0); message.ForeColor = Color.Firebrick;
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 58, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        var cancel = new Button { Text = "取消", AutoSize = true, DialogResult = DialogResult.Cancel };
        var remove = new Button { Text = "删除已保存密钥", AutoSize = true };
        var save = new Button { Text = "保存并启用", AutoSize = true };
        save.Click += (_, _) => SaveKey(); remove.Click += (_, _) => RemoveKey();
        buttons.Controls.AddRange([cancel, remove, save]);
        Controls.Add(buttons); Controls.Add(message); Controls.Add(fields); Controls.Add(description);
        AcceptButton = save; CancelButton = cancel;
        FormClosed += (_, _) => secret.Clear();
    }

    void SaveKey()
    {
        string key = secret.Text;
        if (!DeepSeekKeyStore.IsValid(key)) { message.Text = "请输入有效密钥，不能包含空白字符。"; return; }
        try { DeepSeekKeyStore.Save(key); secret.Clear(); DialogResult = DialogResult.OK; Close(); }
        catch (Exception ex) when (ex is Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException or ArgumentException)
        { message.Text = "无法保存密钥，请检查 Windows 凭据管理器。"; }
    }

    void RemoveKey()
    {
        try { DeepSeekKeyStore.Delete(); secret.Clear(); Deleted = true; DialogResult = DialogResult.OK; Close(); }
        catch (Exception ex) when (ex is Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { message.Text = "无法删除密钥，请检查 Windows 凭据管理器。"; }
    }
}
