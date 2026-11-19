using System.ComponentModel;

namespace AgentMeter.Windows;

/// <summary>用户主动输入密钥；密钥由 Windows 凭据管理器保存。</summary>
internal sealed class MiniMaxAccountsDialog : Form
{
    readonly string directory;
    readonly IMiniMaxVault vault = new WindowsMiniMaxVault();
    readonly ListView list = new();
    readonly Label message = new();
    readonly Button add = new(), update = new(), remove = new();
    public bool Changed { get; private set; }

    public MiniMaxAccountsDialog(string directory)
    {
        this.directory = directory;
        Text = "管理 MiniMax 账户"; StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Microsoft YaHei UI", 10F); ClientSize = new Size(610, 410); MinimumSize = new Size(500, 340);
        message.Dock = DockStyle.Top; message.Height = 76; message.Padding = new Padding(14, 10, 14, 0);
        message.Text = "最多添加 5 个账户。密钥保存在 Windows 凭据管理器，不写入账户列表。\n添加后请在托盘菜单开启 MiniMax 账户查询。";
        list.Dock = DockStyle.Fill; list.View = System.Windows.Forms.View.Details; list.FullRowSelect = true; list.MultiSelect = false;
        list.Columns.Add("账户名称", 290); list.Columns.Add("区域", 150);
        var footer = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 58, FlowDirection = FlowDirection.LeftToRight, Padding = new Padding(8) };
        add.Text = "添加账户"; update.Text = "更新密钥"; remove.Text = "删除账户";
        foreach (var button in new[] { add, update, remove }) { button.AutoSize = true; footer.Controls.Add(button); }
        var close = new Button { Text = "关闭", AutoSize = true, DialogResult = DialogResult.Cancel };
        footer.Controls.Add(close); CancelButton = close;
        Controls.Add(list); Controls.Add(footer); Controls.Add(message);
        add.Click += (_, _) => AddAccount(); update.Click += (_, _) => UpdateSecret(); remove.Click += (_, _) => RemoveAccount();
        Reload();
    }
    void Reload()
    {
        try
        {
            var profiles = MiniMaxProfiles.Load(directory);
            list.Items.Clear();
            foreach (var profile in profiles)
            {
                var item = new ListViewItem(profile.Label) { Tag = profile.Id };
                item.SubItems.Add(profile.Region == "cn" ? "中国区" : "国际区"); list.Items.Add(item);
            }
            add.Enabled = profiles.Count < 5; update.Enabled = remove.Enabled = true;
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            message.Text = "账户列表无法读取，未进行修改。请先备份并检查本地账户文件。";
            add.Enabled = update.Enabled = remove.Enabled = false;
        }
    }
    Guid? SelectedId() => list.SelectedItems.Count == 1 && list.SelectedItems[0].Tag is Guid id ? id : null;
    void AddAccount()
    {
        using var editor = new MiniMaxAccountEntry(false);
        if (editor.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            MiniMaxProfiles.Add(directory, editor.AccountLabel, editor.ServiceRegion, editor.Secret, vault);
            Changed = true; Reload();
        }
        catch (Exception ex) when (IsExpected(ex)) { ShowError(ex); Reload(); }
    }
    void UpdateSecret()
    {
        var id = SelectedId(); if (!id.HasValue) { message.Text = "请先选择一个账户。"; return; }
        using var editor = new MiniMaxAccountEntry(true);
        if (editor.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            if (MiniMaxProfiles.Load(directory).All(profile => profile.Id != id.Value)) throw new InvalidDataException("账户不存在");
            vault.Write(id.Value, editor.Secret); Changed = true;
        }
        catch (Exception ex) when (IsExpected(ex)) { ShowError(ex); }
    }
    void RemoveAccount()
    {
        var id = SelectedId(); if (!id.HasValue) { message.Text = "请先选择一个账户。"; return; }
        if (MessageBox.Show(this, "删除该账户及保存在 Windows 凭据管理器中的密钥？以后需要重新输入。",
            "删除账户", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        try { MiniMaxProfiles.Remove(directory, id.Value, vault); Changed = true; Reload(); }
        catch (Exception ex) when (IsExpected(ex)) { ShowError(ex); Reload(); }
    }
    static bool IsExpected(Exception ex) => ex is InvalidDataException or IOException or UnauthorizedAccessException or
        System.Security.SecurityException or Win32Exception or ArgumentException;
    void ShowError(Exception ex)
    {
        string text = ex is InvalidDataException or ArgumentException ? ex.Message : "无法更新账户或 Windows 凭据，请检查系统权限。";
        MessageBox.Show(this, text, "账户未更新", MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }
}

internal sealed class MiniMaxAccountEntry : Form
{
    readonly TextBox label = new(), secret = new();
    readonly ComboBox region = new();
    readonly bool secretOnly;
    public string AccountLabel => label.Text.Trim();
    public string ServiceRegion => region.SelectedIndex == 1 ? "global" : "cn";
    public string Secret => secret.Text;
    public MiniMaxAccountEntry(bool secretOnly)
    {
        this.secretOnly = secretOnly;
        Text = secretOnly ? "更新 MiniMax 密钥" : "添加 MiniMax 账户";
        Font = new Font("Microsoft YaHei UI", 10F); StartPosition = FormStartPosition.CenterParent;
        ClientSize = new Size(470, secretOnly ? 205 : 310); FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = MinimizeBox = false; ShowInTaskbar = false;
        var panel = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(16), ColumnCount = 1, RowCount = secretOnly ? 4 : 8 };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        if (!secretOnly)
        {
            panel.Controls.Add(new Label { Text = "账户名称", AutoSize = true }); label.MaxLength = 32; label.Dock = DockStyle.Top; panel.Controls.Add(label);
            panel.Controls.Add(new Label { Text = "服务区域", AutoSize = true });
            region.DropDownStyle = ComboBoxStyle.DropDownList; region.Items.AddRange(["中国区", "国际区"]); region.SelectedIndex = 0; region.Dock = DockStyle.Top; panel.Controls.Add(region);
        }
        panel.Controls.Add(new Label { Text = "订阅密钥", AutoSize = true }); secret.UseSystemPasswordChar = true; secret.MaxLength = 1280; secret.Dock = DockStyle.Top; panel.Controls.Add(secret);
        panel.Controls.Add(new Label { Text = "密钥仅用于向所选区域的 MiniMax 查询额度。", AutoSize = true });
        var footer = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 52, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        var save = new Button { Text = "保存", AutoSize = true }; var cancel = new Button { Text = "取消", AutoSize = true, DialogResult = DialogResult.Cancel };
        footer.Controls.Add(save); footer.Controls.Add(cancel); CancelButton = cancel;
        Controls.Add(panel); Controls.Add(footer);
        save.Click += (_, _) =>
        {
            if ((!this.secretOnly && string.IsNullOrWhiteSpace(label.Text)) || string.IsNullOrWhiteSpace(secret.Text))
            { MessageBox.Show(this, this.secretOnly ? "请填写密钥。" : "请填写账户名称和密钥。", "信息不完整", MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
            DialogResult = DialogResult.OK; Hide();
        };
    }
    protected override void Dispose(bool disposing) { if (disposing && !secret.IsDisposed) secret.Clear(); base.Dispose(disposing); }
}
