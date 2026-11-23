import AppKit
import SwiftUI

/// The multi-device window, opened from the panel's settings menu.
@MainActor
enum SyncWindow {
    private static var window: NSWindow?

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 700),
                             styleMask: [.titled, .closable], backing: .buffered, defer: false)
            w.title = "多机同步"
            w.isReleasedWhenClosed = false
            w.contentViewController = NSHostingController(
                rootView: SyncPairingView().environment(UsageStore.shared))
            w.center()
            window = w
        }
        StatusBarController.shared.closePanel()
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
        window?.orderFrontRegardless()
    }
}

private enum PairMode: String, CaseIterable, Identifiable {
    case host, join
    var id: String { rawValue }
    var label: String {
        switch self {
        case .host: return "这台创建配对码"
        case .join: return "输入配对码加入"
        }
    }
}

/// One line of the space's device list.
private struct SyncDeviceRow: Identifiable {
    let id: String
    let name: String
    let isLocal: Bool
    let appVersion: String
    let detail: String
    let updated: Date?
}

struct SyncPairingView: View {
    @Environment(UsageStore.self) private var store

    @State private var baseURL = SyncConfigurationStore.baseURL
    @State private var config: SyncConfiguration? = SyncConfigurationStore.load()
    @State private var mode: PairMode = .host
    @State private var showingPairing = false
    @State private var code: String?
    @State private var sas = ""
    @State private var codeInput = ""
    @State private var expiresAt: Date?
    @State private var invitation: PairingInvitation?
    @State private var joiner: PairingJoiner?
    @State private var pollTask: Task<Void, Never>?
    @State private var busy = false
    @State private var message: String?
    /// The name being typed for this Mac; saved on submit.
    @State private var deviceName = ""
    @State private var nameSaved = false
    /// The other device the user asked to remove, pending confirmation.
    @State private var removing: SyncDeviceRow?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("多机同步")
                        .font(.system(size: 19, weight: .semibold, design: .rounded))
                    Text("多台 Mac 用同一个同步空间合并用量、额度、账户信息与签到记录。服务器只存密文，主密钥不出本机；配对码 5 分钟有效。")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if let config, !showingPairing {
                    pairedView(config)
                } else {
                    pairingView
                }

                if let message {
                    Text(message)
                        .font(.system(size: 11)).foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .frame(width: 520, height: 700)
        .onAppear {
            config = SyncConfigurationStore.load()
            baseURL = SyncConfigurationStore.baseURL
            deviceName = store.syncDeviceName
        }
        .onDisappear { pollTask?.cancel() }
        .alert("移除「\(removing?.name ?? "")”？", isPresented: Binding(get: { removing != nil },
                                                                      set: { if !$0 { removing = nil } })) {
            Button("移除", role: .destructive) {
                if let device = removing?.id { Task { await store.forgetSyncDevice(device) } }
                removing = nil
            }
            Button("取消", role: .cancel) { removing = nil }
        } message: {
            Text("它上传到服务端的数据会被删除，本机也会忘掉它的记录。那台设备自己的数据不受影响，重新配对后会再次上传。")
        }
    }

    // MARK: Paired state

    private func pairedView(_ config: SyncConfiguration) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.seal.fill").foregroundStyle(.green)
                Text("已加入同步空间").font(.system(size: 13, weight: .semibold))
            }

            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 7) {
                GridRow {
                    Text("服务").foregroundStyle(.secondary)
                    Text(config.baseURL).textSelection(.enabled)
                }
                GridRow {
                    Text("空间").foregroundStyle(.secondary)
                    Text(config.shortenedSpace + "…").monospaced()
                }
                GridRow {
                    Text("本机设备").foregroundStyle(.secondary)
                    Text(config.shortenedDevice + "…").monospaced()
                }
                GridRow {
                    Text("本机名称").foregroundStyle(.secondary)
                    HStack(spacing: 6) {
                        TextField("这台 Mac 的名称", text: $deviceName)
                            .textFieldStyle(.roundedBorder)
                            .onSubmit(saveDeviceName)
                        Button("保存", action: saveDeviceName)
                            .disabled(deviceName == store.syncDeviceName)
                        if nameSaved {
                            Image(systemName: "checkmark").foregroundStyle(.green).font(.system(size: 10, weight: .semibold))
                        }
                    }
                }
            }
            .font(.system(size: 11.5))

            HStack(spacing: 8) {
                Text("自动同步")
                    .font(.system(size: 11.5))
                    .foregroundStyle(.secondary)
                Picker("", selection: Binding(get: { store.syncInterval },
                                              set: { store.syncInterval = $0 })) {
                    ForEach(SyncInterval.allCases) { Text($0.label).tag($0) }
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .frame(width: 150, alignment: .leading)
                Spacer(minLength: 8)
                if let last = store.lastSyncAt {
                    Text("上次 \(Fmt.moment(last))")
                        .font(.system(size: 10.5, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
            }

            HStack(spacing: 8) {
                Button(store.syncRunning ? "同步中…" : "立即同步") { syncNow() }
                    .disabled(busy || store.syncRunning)
                Button("添加另一台设备") {
                    resetPairingState()
                    mode = .host
                    showingPairing = true
                    beginHosting()
                }
                .disabled(busy || store.syncRunning)
                Spacer()
                Button("解除配对", role: .destructive) { clearPairing() }
                    .disabled(busy || store.syncRunning)
            }

            if let syncMessage = store.syncMessage {
                Text(syncMessage)
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Toggle("跟随其他设备的偏好设置", isOn: Binding(get: { store.syncPreferencesEnabled },
                                                          set: { store.syncPreferencesEnabled = $0 }))
                .font(.system(size: 11.5))
                .help("界面风格、额度不足阈值、提醒开关、卡片顺序、菜单栏显示与预算；哪台设备最后修改，就以哪台为准")

            deviceList

            Text("同步：按天 × 应用 × 模型的用量、各额度窗口的当日值与近 35 天峰值、账户余额 / 重置卡 / 续费、签到与领取记录、生图张数、卡册张数。不同步：登录凭据、会话与项目路径、来源开关、价格表、桌宠。")
                .font(.system(size: 10)).foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func saveDeviceName() {
        guard deviceName != store.syncDeviceName else { return }
        store.syncDeviceName = deviceName
        deviceName = store.syncDeviceName
        nameSaved = true
        // The new name reaches the other devices with the next round.
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(2))
            nameSaved = false
        }
    }

    // MARK: Devices

    /// This device first, then every other device the last round heard from.
    private var devices: [SyncDeviceRow] {
        var rows = [SyncDeviceRow(id: config?.deviceID ?? "", name: store.syncDeviceName, isLocal: true,
                                  appVersion: UsageStore.appVersion, detail: "本机",
                                  updated: store.lastSyncAt)]
        let local = config?.deviceID ?? ""
        for device in store.syncHistory?["devices"].array ?? [] {
            guard let id = device["device"].string, id != local else { continue }
            let name = device["name"].string ?? ""
            var parts: [String] = []
            if let days = device["days"].double, days > 0 { parts.append("\(Int(days)) 天用量") }
            if let quota = device["quota"].double, quota > 0 { parts.append("\(Int(quota)) 个额度窗口") }
            if let accounts = device["accounts"].double, accounts > 0 { parts.append("\(Int(accounts)) 个账户") }
            rows.append(SyncDeviceRow(id: id,
                                      name: SyncConfigurationStore.label(name: name, device: id),
                                      isLocal: false,
                                      appVersion: device["app_version"].string ?? "",
                                      detail: parts.isEmpty ? "尚未上传用量" : parts.joined(separator: " · "),
                                      updated: device["updated_at"].date))
        }
        return rows
    }

    private var deviceList: some View {
        let rows = devices
        return VStack(alignment: .leading, spacing: 6) {
            Text("空间内的设备")
                .font(.system(size: 11.5, weight: .semibold)).foregroundStyle(.secondary)
                .padding(.horizontal, 2)
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                    if index > 0 { Divider().opacity(0.45) }
                    deviceRow(row)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 4)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        }
    }

    private func deviceRow(_ row: SyncDeviceRow) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "display")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.secondary)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(row.name).font(.system(size: 12, weight: .medium))
                    if row.isLocal {
                        Text("本机")
                            .font(.system(size: 9, weight: .semibold))
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(Capsule().fill(Color.primary.opacity(0.08)))
                    }
                    if !row.appVersion.isEmpty {
                        Text("v\(row.appVersion)").font(.system(size: 9.5)).foregroundStyle(.tertiary)
                    }
                }
                Text(row.detail).font(.system(size: 10.5)).foregroundStyle(.secondary)
            }
            Spacer()
            Text(row.updated.map { "更新 " + Fmt.moment($0) } ?? (row.isLocal ? "尚未同步" : "尚未上传"))
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.tertiary)
            if !row.isLocal {
                Button("移除", role: .destructive) { removing = row }
                    .controlSize(.small)
                    .disabled(busy || store.syncRunning)
                    .help("从空间里移除这台设备，并删除它上传的数据")
            }
        }
        .padding(.vertical, 7)
    }

    // MARK: Pairing setup

    private var pairingView: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("同步服务地址").font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                Text(SyncConfigurationStore.baseURL)
                    .font(.system(size: 12, design: .monospaced))
                    .textSelection(.enabled)
                Text("已内置同步服务地址，无需填写。")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }

            if config == nil {
                Picker("", selection: $mode) {
                    ForEach(PairMode.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .disabled(busy)
            }

            if mode == .host {
                hostSection
            } else {
                joinSection
            }
        }
    }

    private var hostSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let code {
                hostCodeView(code)
            } else if busy {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("正在创建配对码…").font(.system(size: 11)).foregroundStyle(.secondary)
                }
            } else {
                Button(config == nil ? "创建同步空间并生成配对码" : "生成新的配对码") {
                    beginHosting()
                }
                .buttonStyle(.borderedProminent)
            }
        }
    }

    private func hostCodeView(_ code: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("把这 6 位配对码输入另一台 Mac")
                .font(.system(size: 11)).foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Text(PairingCode.grouped(code))
                    .font(.system(size: 30, weight: .bold, design: .monospaced))
                    .textSelection(.enabled)
                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(code, forType: .string)
                } label: {
                    Image(systemName: "doc.on.doc")
                }
                .buttonStyle(.borderless)
                .help("复制配对码")
            }
            if let expiresAt {
                TimelineView(.periodic(from: Date(), by: 1.0)) { context -> Text in
                    let left = max(0, Int(expiresAt.timeIntervalSince(context.date)))
                    return Text(left > 0 ? "剩余 \(left / 60):\(String(format: "%02d", left % 60))" : "已过期，请重新生成")
                        .font(.system(size: 10.5, design: .monospaced))
                        .foregroundStyle(left > 0 ? Color.secondary : Color.red)
                }
            }
            if sas.isEmpty {
                HStack(spacing: 7) {
                    ProgressView().controlSize(.small)
                    Text("等待另一台输入配对码…").font(.system(size: 11)).foregroundStyle(.secondary)
                }
            } else {
                ThemeDivider()
                Text("安全码 \(sas)")
                    .font(.system(size: 22, weight: .semibold, design: .monospaced))
                    .textSelection(.enabled)
                Text("另一台 Mac 应显示相同的六位数字。核对一致后完成配对；不一致请取消并重新生成。")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button("完成配对") { finishHosting() }
                        .buttonStyle(.borderedProminent)
                    Button("取消") { cancelPairing() }
                }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
    }

    private var joinSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("输入另一台 Mac 上显示的 6 位配对码")
                .font(.system(size: 11)).foregroundStyle(.secondary)
            HStack(spacing: 8) {
                TextField("123 456", text: $codeInput)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 22, design: .monospaced))
                    .onSubmit { beginJoining() }
                Button(busy ? "加入中…" : "加入") { beginJoining() }
                    .disabled(busy || PairingCode.normalize(codeInput) == nil)
            }
            if let sas = joinedSAS {
                joinedSuccessView(sas)
            } else if joiner != nil {
                HStack(spacing: 7) {
                    ProgressView().controlSize(.small)
                    Text("已收到配对码，等待另一台确认…").font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
        }
    }

    private var joinedSAS: String? {
        config != nil && !sas.isEmpty && mode == .join ? sas : nil
    }

    private func joinedSuccessView(_ sas: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("配对成功").font(.system(size: 13, weight: .semibold))
            Text("安全码 \(sas)")
                .font(.system(size: 22, weight: .semibold, design: .monospaced))
                .textSelection(.enabled)
            Text("确认另一台 Mac 显示相同的六位数字，然后就可以开始同步。")
                .font(.system(size: 10.5)).foregroundStyle(.secondary)
            HStack {
                Button("完成") {
                    showingPairing = false
                    self.sas = ""
                    codeInput = ""
                }
                .buttonStyle(.borderedProminent)
                Button("取消") { cancelPairing() }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
    }

    // MARK: Actions

    private func beginHosting() {
        guard !busy else { return }
        message = nil
        pollTask?.cancel()
        code = nil
        sas = ""
        busy = true

        Task { @MainActor in
            do {
                let url = try serviceURL()
                let configuration = try await ensureHostConfiguration(baseURL: url)
                config = configuration
                let keys = try SyncKeys(masterKey: configuration.masterKey,
                                        spaceID: configuration.spaceID)
                let transport = try PairingService(baseURL: url)
                let initiator = PairingInitiator(transport: transport,
                                                 spaceID: configuration.spaceID,
                                                 token: keys.authToken,
                                                 masterKey: configuration.masterKey)
                let invitation = try await initiator.start()
                self.invitation = invitation
                code = invitation.slot.code
                expiresAt = invitation.slot.expiresAt
                busy = false
                pollForPeer(initiator: initiator, invitation: invitation,
                            spaceToken: keys.authToken)
            } catch {
                busy = false
                message = describe(error)
            }
        }
    }

    private func pollForPeer(initiator: PairingInitiator, invitation: PairingInvitation,
                             spaceToken: String) {
        pollTask?.cancel()
        pollTask = Task { @MainActor in
            while !Task.isCancelled {
                if let expiresAt, Date() > expiresAt {
                    message = "配对码已过期，请重新生成"
                    return
                }
                do {
                    let finish = try await initiator.poll(invitation)
                    if case .sealed(let code) = finish {
                        sas = PairingCode.grouped(code)
                        return
                    }
                } catch {
                    message = describe(error)
                    return
                }
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func beginJoining() {
        guard !busy else { return }
        guard let normalized = PairingCode.normalize(codeInput) else {
            message = "请输入 6 位数字配对码"
            return
        }
        message = nil
        pollTask?.cancel()
        sas = ""
        joiner = nil
        busy = true

        Task { @MainActor in
            do {
                let url = try serviceURL()
                let transport = try PairingService(baseURL: url)
                let joiner = try await PairingJoiner.begin(transport: transport, code: normalized)
                self.joiner = joiner
                expiresAt = joiner.lookup.expiresAt
                busy = false
                pollForHost(joiner: joiner, baseURL: url)
            } catch {
                busy = false
                message = describe(error)
            }
        }
    }

    private func pollForHost(joiner: PairingJoiner, baseURL: URL) {
        pollTask?.cancel()
        pollTask = Task { @MainActor in
            while !Task.isCancelled {
                if let expiresAt, Date() > expiresAt {
                    message = "配对码已过期，请让另一台重新生成"
                    return
                }
                do {
                    let receive = try await joiner.poll()
                    if case .joined(let spaceID, let masterKey, let code) = receive {
                        let config = SyncConfiguration(spaceID: spaceID,
                                                       deviceID: SyncConfigurationStore.deviceID(),
                                                       masterKey: masterKey,
                                                       baseURL: baseURL.absoluteString)
                        guard SyncConfigurationStore.save(config) else {
                            message = "无法把同步密钥写入钥匙串"
                            return
                        }
                        // Paired on this build: the first round adopts the
                        // space's preferences, then it runs right away.
                        UserDefaults.standard.set(true, forKey: SyncPreferenceSync.adoptKey)
                        self.config = config
                        sas = PairingCode.grouped(code)
                        store.pairingFinished()
                        return
                    }
                } catch {
                    message = describe(error)
                    return
                }
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func finishHosting() {
        // Do not consume the slot here. The joining device may still be
        // polling for the sealed key, and consuming it would turn that poll
        // into a 410. The slot expires on its own five minutes after it was
        // created; the ciphertext is already sealed to the joining device.
        pollTask?.cancel()
        invitation = nil
        code = nil
        sas = ""
        showingPairing = false
        // The other device starts syncing as soon as it has the key; pick up
        // what it uploaded instead of waiting for the interval.
        store.pairingFinished()
    }

    private func cancelPairing() {
        pollTask?.cancel()
        invitation = nil
        joiner = nil
        code = nil
        sas = ""
        codeInput = ""
        showingPairing = false
        if config == nil {
            mode = .host
        }
    }

    /// Leaves the space. The store removes this device's blob from the
    /// service, forgets the other devices and says what it could not do.
    private func clearPairing() {
        pollTask?.cancel()
        config = nil
        code = nil
        sas = ""
        codeInput = ""
        showingPairing = false
        mode = .host
        message = nil
        Task { await store.unpair() }
    }

    private func syncNow() {
        guard !busy, !store.syncRunning else { return }
        message = nil
        Task { @MainActor in
            await store.syncNow()
        }
    }

    private func ensureHostConfiguration(baseURL: URL) async throws -> SyncConfiguration {
        if let existing = SyncConfigurationStore.load() {
            guard existing.baseURL == baseURL.absoluteString else {
                throw PairingError.rejected("base_url_changed")
            }
            return existing
        }
        let spaceID = SyncKeys.randomIdentifier()
        let masterKey = SyncKeys.randomMasterKey()
        let keys = try SyncKeys(masterKey: masterKey, spaceID: spaceID)
        let service = try SyncService(baseURL: baseURL)
        _ = try await service.createSpace(spaceID: spaceID, token: keys.authToken,
                                          authHash: keys.authHash)
        let configuration = SyncConfiguration(spaceID: spaceID,
                                              deviceID: SyncConfigurationStore.deviceID(),
                                              masterKey: masterKey,
                                              baseURL: baseURL.absoluteString)
        guard SyncConfigurationStore.save(configuration) else {
            throw PairingError.cryptoFailed
        }
        // A space created on this build shares its preferences; a device that
        // pairs into it later adopts them on its first round.
        UserDefaults.standard.set(true, forKey: SyncPreferenceSync.adoptKey)
        return configuration
    }

    private func serviceURL() throws -> URL {
        let trimmed = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), url.scheme != nil else {
            throw PairingError.notConfigured
        }
        return url
    }

    private func resetPairingState() {
        pollTask?.cancel()
        code = nil
        sas = ""
        invitation = nil
        joiner = nil
        expiresAt = nil
        message = nil
    }

    private func describe(_ error: Error) -> String {
        if let error = error as? PairingError {
            switch error {
            case .notConfigured:
                return "同步服务地址无效：需要 https，本机调试可用 http://127.0.0.1:8899"
            case .unauthorized:
                return "配对凭证无效，请重新生成配对码"
            case .notFound:
                return "配对码不存在或已过期"
            case .expired:
                return "配对码已过期，请重新生成"
            case .invalidCode:
                return "请输入 6 位数字配对码"
            case .invalidResponse:
                return "同步服务返回了无法识别的数据"
            case .transport:
                return "无法连接同步服务，请检查地址和网络"
            case .cryptoFailed:
                return "密钥校验失败，请重新配对"
            case .rejected(let code):
                switch code {
                case "pair_attempts_exceeded": return "尝试次数过多，配对码已作废"
                case "rate_limited": return "操作太频繁，请稍后再试"
                case "pair_slot_already_paired": return "该配对码已被使用"
                case "pair_slot_already_sealed": return "该配对码已完成"
                case "base_url_changed": return "已配对到另一个服务地址，请先解除配对"
                case "space_taken": return "空间标识冲突，请重新生成"
                default: return "同步服务返回：\(code)"
                }
            }
        }
        if let error = error as? SyncError {
            switch error {
            case .notConfigured: return "同步配置不完整"
            case .unauthorized: return "空间凭证无效，请重新配对"
            case .notFound: return "空间或设备不存在"
            case .invalidResponse: return "同步服务返回了无法识别的数据"
            case .transport: return "无法连接同步服务，请检查地址和网络"
            case .cryptoFailed: return "同步数据无法解密，请检查两台设备是否在同一空间"
            case .rejected(let code): return "同步服务返回：\(code)"
            }
        }
        return "操作失败，请稍后重试"
    }
}
