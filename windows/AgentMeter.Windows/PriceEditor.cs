using System.Globalization;

namespace AgentMeter.Windows;

/// <summary>编辑覆盖内置快照的本机美元价格，不连接网络。</summary>
internal sealed class PriceEditor : Form
{
    readonly DataGridView grid = new();
    readonly string directory;
    public PriceEditor(string directory)
    {
        this.directory = directory;
        Text = "自定义模型价格"; StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Microsoft YaHei UI", 10F); ClientSize = new Size(760, 450); MinimumSize = new Size(620, 350);
        var note = new Label { Dock = DockStyle.Top, Height = 76, Padding = new Padding(14, 10, 14, 0),
            Text = "每百万 Token 的美元价格。条目覆盖内置快照；选中行头按 Delete 删除，可恢复内置价格。\n价格必须完整填写；未知价格不要填零。估算不代表实际账单。" };
        grid.Dock = DockStyle.Fill; grid.AllowUserToAddRows = true; grid.AllowUserToDeleteRows = true;
        grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill; grid.RowHeadersWidth = 36;
        grid.Columns.Add("model", "模型名称"); grid.Columns.Add("input", "输入"); grid.Columns.Add("cache_read", "缓存读取");
        grid.Columns.Add("cache_write", "缓存写入"); grid.Columns.Add("output", "输出");
        grid.Columns[0].FillWeight = 180;
        var footer = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 54, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        var save = new Button { Text = "保存", AutoSize = true }; var cancel = new Button { Text = "取消", AutoSize = true, DialogResult = DialogResult.Cancel };
        footer.Controls.Add(save); footer.Controls.Add(cancel); CancelButton = cancel;
        Controls.Add(grid); Controls.Add(footer); Controls.Add(note);
        try
        {
            foreach (var row in PriceOverrides.Load(directory))
                grid.Rows.Add(row.Model, Format(row.Input), Format(row.CacheRead), Format(row.CacheWrite), Format(row.Output));
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            note.Text = "自定义价格文件无法读取，未进行任何修改。请先备份并检查该文件。";
            grid.Enabled = false; save.Enabled = false;
        }
        save.Click += (_, _) => SaveRows();
    }
    static string Format(decimal value) => value.ToString("0.############################", CultureInfo.InvariantCulture);
    void SaveRows()
    {
        try
        {
            grid.EndEdit();
            var rows = new List<PriceRow>();
            foreach (DataGridViewRow row in grid.Rows)
            {
                if (row.IsNewRow) continue;
                string model = Convert.ToString(row.Cells[0].Value)?.Trim() ?? "";
                decimal Rate(int column)
                {
                    string text = Convert.ToString(row.Cells[column].Value)?.Trim() ?? "";
                    if (!decimal.TryParse(text, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var value))
                        throw new InvalidDataException("请为每一项输入非负数字，小数使用英文句点。");
                    return value;
                }
                rows.Add(new PriceRow(model, Rate(1), Rate(2), Rate(3), Rate(4)));
            }
            PriceOverrides.Save(directory, rows);
            DialogResult = DialogResult.OK; Close();
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            MessageBox.Show(this, ex is InvalidDataException ? ex.Message : "无法保存价格，请检查设置目录权限。",
                "价格未保存", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }
}
