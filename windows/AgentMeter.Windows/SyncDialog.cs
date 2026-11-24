using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentMeter.Windows;

/// <summary>多机同步：创建空间、短码配对、设备列表与手动同步。</summary>
internal sealed class SyncDialog : Form
{
    readonly MeterWindow owner;
    readonly TextBox baseUrl = new() { Name = "sync-base-url", Width = 390 };
    readonly TextBox code = new() { Name = "sync-pair-code", Width = 92, MaxLength = 9 };
    readonly Button create = new() { Name = "sync-create", Text = "创建新空间", AutoSize = true };
    readonly Button join = new() { Name = "sync-join", Text = "用短码加入", AutoSize = true };
    readonly Button pairNew = new() { Name = "sync-pair-new", Text = "配对另一台设备", AutoSize = true };
    readonly Button syncNow = new() { Name = "sync-now", Text = "立即同步", AutoSize = true };
    readonly Button disconnect = new() { Name = "sync-disconnect", Text = "断开本机", AutoSize = true };
    readonly Button remove = new() { Name = "sync-device-remove", Text = "移除选中设备", AutoSize = true };
    readonly Button refresh = new() { Name = "sync-refresh", Text = "刷新", AutoSize = true };
    readonly ListView list = new() { Name = "sync-devices", View = View.Details, FullRowSelect = true, MultiSelect = false, HideSelection = false };
    readonly Label spaceText = new() { AutoSize = true, ForeColor = Color.DimGray };
    readonly Label deviceText = new() { AutoSize = true, ForeColor = Color.DimGray };
    readonly Label message = new() { Name = "sync-message", AutoSize = false, Height = 38, ForeColor = Color.DimGray, Dock = DockStyle.Fill, Padding = new Padding(2, 6, 0, 0) };
    readonly Label pairCode = new() { Name = "sync-pair-display", AutoSize = true, Font = new Font("Consolas", 18F, FontStyle.Bold) };
    readonly Label pairHint = new() { AutoSize = false, Height = 44, ForeColor = Color.DimGray };
    readonly Label pairSas = new() { AutoSize = true, Font = new Font("Consolas", 14F, FontStyle.Bold) };
    readonly Button cancelPair = new() { Name = "sync-pair-cancel", Text = "取消", AutoSize = true };
    readonly Panel disconnected = new() { Dock = DockStyle.Fill };
    readonly Panel connected = new() { Dock = DockStyle.Fill };
    readonly Panel pairing = new() { Dock = DockStyle.Fill, Visible = false };
    SyncPreferences? config;
    byte[]? master;
    CancellationTokenSource? pairingCancellation;
    bool working;
    bool pairDone;

    public SyncDialog(MeterWindow owner)
    {
        this.owner = owner;
        Text = "多机同步"; StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
        Font = new Font("Microsoft YaHei UI", 10F); ClientSize = new Size(820, 620);
        MinimumSize = new Size(780, 580);

        var description = new Label
        {
            Dock = DockStyle.Fill, Padding = new Padding(2, 8, 0, 0),
            Text = "两台设备填同一个同步服务地址，用一次六位短码配对。\n" +
                   "上传的只有按日汇总的用量、额度和不随设备变化的设置；会话内容、路径与凭据不会离开本机。\n" +
                   "同步服务只保存密文，主密钥在 Windows 凭据管理器里。"
        };

        baseUrl.PlaceholderText = "https://sync.example.com 或 http://127.0.0.1:8899";
        var urlRow = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 42, WrapContents = false, Padding = new Padding(0, 6, 0, 0) };
        urlRow.Controls.Add(new Label { Text = "服务地址", AutoSize = true, Margin = new Padding(0, 8, 8, 0) });
        urlRow.Controls.Add(baseUrl);
        create.Margin = new Padding(10, 3, 4, 0); join.Margin = new Padding(4, 3, 4, 0);
        urlRow.Controls.Add(create);
        var joinRow = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 42, WrapContents = false, Padding = new Padding(0, 3, 0, 0) };
        joinRow.Controls.Add(new Label { Text = "六位配对码", AutoSize = true, Margin = new Padding(0, 8, 8, 0) });
        joinRow.Controls.Add(code);
        joinRow.Controls.Add(join);
        joinRow.Controls.Add(new Label { Text = "由已加入空间的那台设备生成", AutoSize = true, ForeColor = Color.DimGray, Margin = new Padding(10, 8, 0, 0) });
        disconnected.Controls.Add(joinRow); disconnected.Controls.Add(urlRow);

        var connectedTop = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 38, WrapContents = false, Padding = new Padding(0, 5, 0, 0) };
        connectedTop.Controls.Add(spaceText); connectedTop.Controls.Add(deviceText);
        var connectedButtons = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 42, WrapContents = false, Padding = new Padding(0, 3, 0, 0) };
        connectedButtons.Controls.Add(pairNew); connectedButtons.Controls.Add(syncNow); connectedButtons.Controls.Add(refresh);
        connectedButtons.Controls.Add(disconnect);
        connected.Controls.Add(connectedButtons); connected.Controls.Add(connectedTop);

        list.Columns.Add("设备", 130);
        list.Columns.Add("角色", 90);
        list.Columns.Add("大小", 90);
        list.Columns.Add("版本", 70);
        list.Columns.Add("更新时间", 150);
        list.DoubleClick += (_, _) => RemoveSelected();
        var listHost = new Panel { Dock = DockStyle.Fill, Padding = new Padding(0, 4, 0, 0) };
        listHost.Controls.Add(list);
        var removeRow = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 38, FlowDirection = FlowDirection.RightToLeft, WrapContents = false };
        removeRow.Controls.Add(remove);

        var pairTop = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 50, WrapContents = false };
        pairTop.Controls.Add(pairCode);
        pairHint.Dock = DockStyle.Top; pairHint.Padding = new Padding(2, 2, 0, 0);
        var pairBottom = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 40, WrapContents = false };
        pairBottom.Controls.Add(pairSas); cancelPair.Margin = new Padding(18, 2, 0, 0); pairBottom.Controls.Add(cancelPair);
        var pairPanel = pairing;
        pairPanel.Padding = new Padding(4, 6, 4, 0);
        pairPanel.Controls.Add(pairHint); pairPanel.Controls.Add(pairBottom); pairPanel.Controls.Add(pairTop);

        var root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 6, Padding = new Padding(16, 10, 16, 12) };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 70));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 96));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 150));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        var close = new Button { Text = "关闭", AutoSize = true, DialogResult = DialogResult.Cancel };
        var bottom = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft, WrapContents = false };
        bottom.Controls.Add(close);
        root.Controls.Add(description, 0, 0);
        root.Controls.Add(disconnected, 0, 1);
        root.Controls.Add(connected, 0, 1);
        root.Controls.Add(listHost, 0, 2);
        root.Controls.Add(removeRow, 0, 2);
        root.Controls.Add(pairPanel, 0, 3);
        root.Controls.Add(message, 0, 4);
        root.Controls.Add(bottom, 0, 5);
        Controls.Add(root);
        CancelButton = close;

        create.Click += async (_, _) => await CreateSpaceAsync();
        join.Click += async (_, _) => await JoinAsync();
        pairNew.Click += async (_, _) => await PairNewDeviceAsync();
        syncNow.Click += async (_, _) => await SyncNowAsync();
        refresh.Click += async (_, _) => await RefreshDevicesAsync();
        disconnect.Click += async (_, _) => await DisconnectAsync();
        remove.Click += (_, _) => RemoveSelected();
        cancelPair.Click += (_, _) => CancelPairing();
        Shown += async (_, _) => { LoadConfiguration(); await RefreshDevicesAsync(); };
        FormClosing += (_, _) => pairingCancellation?.Cancel();
    }

    void LoadConfiguration()
    {
        config = SyncPreferences.Load(AccountPreferences.DefaultDirectory);
        if (config is null) { ApplyState(); return; }
        baseUrl.Text = config.BaseUrl;
        master = SyncSecrets.Read(config.SpaceId);
        if (master is null)
        {
            message.Text = "同步配置存在，但 Windows 凭据管理器里找不到主密钥；请断开本机后重新配对。";
            config = null;
        }
        ApplyState();
    }

    void ApplyState()
    {
        bool isConnected = config is not null && master is not null;
        disconnected.Visible = !isConnected;
        connected.Visible = isConnected;
        pairing.Visible = pairingCancellation is not null || pairDone;
        baseUrl.Enabled = !isConnected && !working;
        create.Enabled = join.Enabled = code.Enabled = !isConnected && !working;
        pairNew.Enabled = syncNow.Enabled = refresh.Enabled = disconnect.Enabled = isConnected && !working;
        remove.Enabled = isConnected && !working && list.SelectedItems.Count > 0;
        if (config is not null)
        {
            spaceText.Text = $"空间 {config.SpaceId[..8]}…";
            deviceText.Text = $"    本机 {config.DeviceId[..8]}…";
        }
        else
        {
            spaceText.Text = "";
            deviceText.Text = "";
        }
    }

    void SetWorking(bool active)
    {
        working = active;
        ApplyState();
        UseWaitCursor = active;
    }

    string BaseUrl()
    {
        string value = baseUrl.Text.Trim();
        if (!SyncPreferences.ValidBaseUrl(value))
            throw new ArgumentException("同步服务地址无效：需要 https，本机调试可用 http://127.0.0.1:8899");
        return value.TrimEnd('/');
    }

    JsonObject Connection()
    {
        if (config is null || master is null) throw new InvalidOperationException("sync_not_configured");
        return new JsonObject
        {
            ["base_url"] = config.BaseUrl,
            ["space_id"] = config.SpaceId,
            ["device_id"] = config.DeviceId,
            ["master_key"] = Convert.ToBase64String(master),
        };
    }

    async Task CreateSpaceAsync()
    {
        if (working) return;
        string url;
        try { url = BaseUrl(); }
        catch (ArgumentException ex) { message.Text = ex.Message; return; }
        string space = SyncPreferences.NewIdentifier();
        string device = SyncPreferences.NewIdentifier();
        string masterText = SyncSecrets.NewMasterKey();
        var input = new JsonObject
        {
            ["base_url"] = url, ["space_id"] = space, ["device_id"] = device, ["master_key"] = masterText
        };
        SetWorking(true); message.Text = "正在创建同步空间…";
        try
        {
            string output = await SyncBackendClient.RunAsync("--sync-space-create", input.ToJsonString(), CancellationToken.None);
            if (SyncRunResult.Read(output) is null) { message.Text = "创建同步空间失败：" + Reason(output); return; }
            byte[] key = Convert.FromBase64String(masterText);
            SyncSecrets.Save(space, key);
            config = new SyncPreferences(url, space, device, null);
            config.Save(AccountPreferences.DefaultDirectory);
            master = key;
            message.Text = "同步空间已创建。点「配对另一台设备」生成六位短码。";
            ApplyState();
            await RefreshDevicesAsync();
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or System.ComponentModel.Win32Exception or
            OperationCanceledException or ObjectDisposedException or FormatException or ArgumentException)
        {
            message.Text = "创建同步空间失败：" + Reason(ex.Message);
        }
        finally { SetWorking(false); }
    }

    async Task JoinAsync()
    {
        if (working) return;
        string url;
        try { url = BaseUrl(); }
        catch (ArgumentException ex) { message.Text = ex.Message; return; }
        string digits = new(code.Text.Where(char.IsAsciiDigit).ToArray());
        if (digits.Length != 6) { message.Text = "配对码应为六位数字。"; return; }
        string device = SyncPreferences.NewIdentifier();
        string? space = null, keyText = null, sas = null, failure = null;
        using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(CancellationToken.None);
        SetWorking(true); message.Text = "正在查找配对码…";
        try
        {
            await SyncBackendClient.PairAsync("--sync-pair-join",
                new JsonObject { ["base_url"] = url, ["code"] = digits }.ToJsonString(),
                ev =>
                {
                    string name = StringField(ev, "event");
                    if (name == "joined")
                    {
                        space = StringField(ev, "space_id"); keyText = StringField(ev, "master_key"); sas = StringField(ev, "sas");
                    }
                    else if (name == "error") failure = StringField(ev, "reason");
                }, cancellation.Token);
            if (failure is not null) { message.Text = "加入失败：" + Reason(failure); return; }
            if (space is null || keyText is null) { message.Text = "配对没有完成，请让另一台设备重新生成短码。"; return; }
            byte[] key = Convert.FromBase64String(keyText);
            SyncSecrets.Save(space, key);
            config = new SyncPreferences(url, space, device, null);
            config.Save(AccountPreferences.DefaultDirectory);
            master = key;
            ShowPairResult("已加入同步空间", sas ?? "");
            message.Text = "已加入同步空间。请核对两台设备上的六位数字一致。";
            await RefreshDevicesAsync();
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or System.ComponentModel.Win32Exception or
            OperationCanceledException or ObjectDisposedException or FormatException or ArgumentException)
        {
            message.Text = "加入失败：" + Reason(ex.Message);
        }
        finally { SetWorking(false); }
    }

    async Task PairNewDeviceAsync()
    {
        if (working || config is null || master is null) return;
        pairingCancellation = new CancellationTokenSource();
        pairDone = false; pairCode.Text = "正在生成…"; pairHint.Text = "正在向同步服务登记一次性配对槽。";
        pairSas.Text = ""; cancelPair.Text = "取消"; pairing.Visible = true;
        SetWorking(true);
        try
        {
            await SyncBackendClient.PairAsync("--sync-pair-create", Connection().ToJsonString(),
                ev => BeginInvoke(new Action(() => HandlePairEvent(ev))), pairingCancellation.Token);
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or System.ComponentModel.Win32Exception or
            OperationCanceledException or ObjectDisposedException)
        {
            if (!pairingCancellation.IsCancellationRequested) message.Text = "配对失败：" + Reason(ex.Message);
        }
        finally
        {
            pairingCancellation.Dispose(); pairingCancellation = null;
            SetWorking(false);
            ApplyState();
        }
    }

    void HandlePairEvent(JsonElement ev)
    {
        string name = StringField(ev, "event");
        if (name == "code")
        {
            string value = StringField(ev, "code");
            pairCode.Text = value.Length == 6 ? value[..3] + " " + value[3..] : value;
            pairHint.Text = "在另一台设备输入这六位数字。两台设备会各自显示一个核对码，必须一致。";
        }
        else if (name == "paired")
        {
            pairDone = true;
            pairSas.Text = "核对码 " + StringField(ev, "sas");
            pairHint.Text = "另一台设备已收到主密钥；请确认它显示的核对码与这里一致。";
            cancelPair.Text = "完成";
        }
        else if (name == "expired")
        {
            pairDone = true;
            pairCode.Text = "已过期";
            pairHint.Text = "配对码已过期，请重新生成。";
            cancelPair.Text = "完成";
        }
        else if (name == "error")
        {
            pairDone = true;
            pairCode.Text = "配对失败";
            pairHint.Text = Reason(StringField(ev, "reason"));
            cancelPair.Text = "完成";
        }
    }

    void ShowPairResult(string title, string sas)
    {
        pairDone = true;
        pairCode.Text = title;
        pairHint.Text = "请核对两台设备上的六位数字一致；不一致说明中间人可能介入，不要继续。";
        pairSas.Text = sas.Length == 6 ? "核对码 " + sas[..3] + " " + sas[3..] : "核对码 " + sas;
        cancelPair.Text = "完成";
        pairing.Visible = true;
    }

    void CancelPairing()
    {
        if (pairDone)
        {
            pairDone = false;
            pairing.Visible = false;
            pairCode.Text = ""; pairSas.Text = ""; pairHint.Text = "";
            ApplyState();
            return;
        }
        pairingCancellation?.Cancel();
        pairDone = false;
        pairing.Visible = false;
        message.Text = "已取消配对。";
        ApplyState();
    }

    async Task SyncNowAsync()
    {
        if (working || config is null || master is null) return;
        SetWorking(true); message.Text = "正在加密上传并拉取其他设备…";
        try
        {
            var input = Connection();
            input["settings"] = JsonNode.Parse(owner.SyncSettingsJson());
            if (owner.LatestAccountsJson is { } latest) input["latest_accounts"] = JsonNode.Parse(latest);
            string output = await SyncBackendClient.RunAsync("--sync-push", input.ToJsonString(), CancellationToken.None);
            var result = SyncRunResult.Read(output);
            if (result is null) { message.Text = "同步失败：" + Reason(output); return; }
            config = config with { LastSyncAt = DateTimeOffset.Now.ToUnixTimeSeconds() };
            config.Save(AccountPreferences.DefaultDirectory);
            string imported = result.Imported.Count == 0 ? "没有其他设备的新数据" : $"已合并 {result.Imported.Count} 台设备";
            string failed = result.Failed.Count == 0 ? "" : $"；{result.Failed.Count} 台设备的密文无法读取";
            message.Text = $"同步完成：本机已上传，{imported}{failed}。";
            await RefreshDevicesAsync();
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or System.ComponentModel.Win32Exception or
            OperationCanceledException or ObjectDisposedException or JsonException)
        {
            message.Text = "同步失败：" + Reason(ex.Message);
        }
        finally { SetWorking(false); }
    }

    async Task RefreshDevicesAsync()
    {
        if (config is null || master is null) return;
        try
        {
            string output = await SyncBackendClient.RunAsync("--sync-devices", Connection().ToJsonString(), CancellationToken.None);
            var rows = SyncDeviceRow.Read(output);
            list.BeginUpdate();
            try
            {
                list.Items.Clear();
                foreach (var row in rows)
                {
                    var item = new ListViewItem(row.ShortId) { Tag = row.DeviceId };
                    item.SubItems.Add(row.DeviceId == config.DeviceId ? "本机" : "其他设备");
                    item.SubItems.Add(row.SizeText); item.SubItems.Add(row.Version.ToString());
                    item.SubItems.Add(row.Updated);
                    if (row.DeviceId == config.DeviceId) item.ForeColor = Color.DimGray;
                    list.Items.Add(item);
                }
                if (rows.Count == 0) list.Items.Add(new ListViewItem("暂无设备"));
            }
            finally { list.EndUpdate(); }
            remove.Enabled = false;
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or System.ComponentModel.Win32Exception or
            OperationCanceledException or ObjectDisposedException or JsonException)
        {
            message.Text = "无法读取设备列表：" + Reason(ex.Message);
        }
    }

    void RemoveSelected()
    {
        if (working || config is null || master is null || list.SelectedItems.Count == 0) return;
        var selected = list.SelectedItems[0];
        string? device = selected.Tag as string;
        if (device is null || device == config.DeviceId) { message.Text = "不能移除本机；如需停止使用同步，请点「断开本机」。"; return; }
        if (MessageBox.Show(this, $"从同步空间移除设备 {device[..8]}…？\n它的密文会从服务端删除，该设备下次同步需要重新配对。",
                "移除设备", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        _ = RemoveAsync(device);
    }

    async Task RemoveAsync(string device)
    {
        SetWorking(true); message.Text = "正在移除设备…";
        try
        {
            var input = Connection(); input["remote_device_id"] = device;
            string output = await SyncBackendClient.RunAsync("--sync-device-remove", input.ToJsonString(), CancellationToken.None);
            if (SyncRunResult.Read(output) is null && !output.Contains("\"removed\"", StringComparison.Ordinal))
                message.Text = "移除失败：" + Reason(output);
            else message.Text = "设备已移除。";
            await RefreshDevicesAsync();
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or System.ComponentModel.Win32Exception or
            OperationCanceledException or ObjectDisposedException)
        { message.Text = "移除失败：" + Reason(ex.Message); }
        finally { SetWorking(false); }
    }

    async Task DisconnectAsync()
    {
        if (working) return;
        if (MessageBox.Show(this, "断开本机同步？\n同步空间和主密钥会从本机移除，已拉取的远端记录会清空；服务端密文不会删除。",
                "断开本机", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        SetWorking(true);
        try
        {
            if (config is not null)
            {
                try { await SyncBackendClient.RunAsync("--sync-reset", "{}", CancellationToken.None); }
                catch (Exception ex) when (ex is IOException or InvalidOperationException or System.ComponentModel.Win32Exception or
                    OperationCanceledException or ObjectDisposedException) { }
                SyncSecrets.Delete(config.SpaceId);
            }
            SyncPreferences.Delete(AccountPreferences.DefaultDirectory);
            config = null; master = null;
            list.Items.Clear();
            message.Text = "已断开本机同步。";
            ApplyState();
        }
        finally { SetWorking(false); }
    }

    static string StringField(JsonElement root, string key)
    {
        return root.ValueKind == JsonValueKind.Object && root.TryGetProperty(key, out var value) &&
               value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
    }

    static string Reason(string error)
    {
        string text = error.Trim();
        if (text.StartsWith("{", StringComparison.Ordinal))
        {
            try
            {
                using var document = JsonDocument.Parse(text);
                var root = document.RootElement;
                string reason = StringField(root, "reason");
                if (reason.Length > 0) return Reason(reason);
            }
            catch (JsonException) { }
        }
        return text switch
        {
            "unauthorized" => "同步服务拒绝了这个空间的密钥，请重新配对。",
            "not_found" => "找不到同步空间或设备；请确认地址与空间没有变化。",
            "expired" => "配对码或配对槽已过期，请重新生成。",
            "transport" => "无法连接同步服务；请检查地址、网络或本机服务是否启动。",
            "not_configured" => "同步服务地址无效：需要 https，本机调试可用 http://127.0.0.1:8899。",
            "invalid_code" => "配对码应为六位数字。",
            "invalid_master_key" => "同步主密钥损坏或长度不对，请重新配对。",
            "invalid_device" => "设备标识无效。",
            "invalid_space_id" => "空间标识无效。",
            "pair_code_not_found" => "配对码不存在或已经用过。",
            "pair_slot_expired" => "配对码已过期，请重新生成。",
            "pair_slot_consumed" => "配对码已完成，请重新生成。",
            "pair_slot_already_paired" => "这台设备已经加入过该配对槽。",
            "sync_backend_missing" => "后台组件缺失，请重新安装。",
            "sync_backend_failed" => "后台同步进程失败，请稍后重试。",
            "sync_directory_unavailable" => "无法访问本机同步目录。",
            _ => text.Length == 0 ? "未知错误。" : text,
        };
    }
}
