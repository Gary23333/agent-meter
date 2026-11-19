import AppKit
import SwiftUI

/// The multi-device window, opened from the panel's settings menu.
@MainActor
enum SyncWindow {
    private static var window: NSWindow?

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 620),
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
    @State private var syncMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("多机同步")
                    .font(.system(size: 19, weight: .semibold, design: .rounded))
                Text("两台 Mac 用同一个同步空间合并用量。服务器只存密文，主密钥不出本机；配对码 5 分钟有效。")
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

            Spacer(minLength: 0)
        }
        .padding(20)
        .frame(width: 520, height: 620, alignment: .topLeading)
        .onAppear {
            config = SyncConfigurationStore.load()
            if !SyncConfigurationStore.baseURL.isEmpty {
                baseURL = SyncConfigurationStore.baseURL
            }
        }
        .onDisappear { pollTask?.cancel() }
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
            }
            .font(.system(size: 11.5))

            HStack(spacing: 8) {
                Button(busy ? "同步中…" : "立即同步") { syncNow() }
                    .disabled(busy)
                Button("添加另一台设备") {
                    resetPairingState()
                    mode = .host
                    showingPairing = true
                    beginHosting()
                }
                .disabled(busy)
                Spacer()
                Button("解除配对", role: .destructive) { clearPairing() }
                    .disabled(busy)
            }

            if let syncMessage {
                Text(syncMessage)
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let code {
                hostCodeView(code)
            } else if let sas = joinedSAS {
                joinedSuccessView(sas)
            }
        }
    }

    // MARK: Pairing setup

    private var pairingView: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("同步服务地址").font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                TextField("https://sync.example.com", text: $baseURL)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 12, design: .monospaced))
                Text("两台 Mac 必须填同一个地址。本机调试可用 http://127.0.0.1:8899")
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
                        self.config = config
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

    private func clearPairing() {
        SyncConfigurationStore.clear()
        pollTask?.cancel()
        config = nil
        code = nil
        sas = ""
        codeInput = ""
        showingPairing = false
        mode = .host
        syncMessage = nil
        message = nil
    }

    private func syncNow() {
        guard let config, !busy else { return }
        guard let backend = store.backendClient else {
            message = "本机后端尚未就绪，请稍后再试"
            return
        }
        guard let url = URL(string: config.baseURL) else {
            message = "同步服务地址无效"
            return
        }
        busy = true
        message = nil
        syncMessage = nil

        Task { @MainActor in
            do {
                let transport = try SyncService(baseURL: url)
                let keys = try SyncKeys(masterKey: config.masterKey, spaceID: config.spaceID)
                let runner = SyncRunner(transport: transport, keys: keys,
                                        deviceID: config.deviceID)
                var settings = SyncSettings()
                settings.theme = store.theme.rawValue
                settings.lowQuotaThreshold = store.lowQuotaThreshold
                settings.alertsEnabled = store.notificationsEnabled
                let coordinator = SyncCoordinator(backend: backend, runner: runner,
                                                  settings: settings)
                let report = try await coordinator.run()
                var summary = "已上传本机用量，空间内共 \(report.devices) 台设备"
                if !report.importedDevices.isEmpty {
                    summary += "，合并了 \(report.importedDevices.count) 台其他设备"
                }
                if !report.failedDevices.isEmpty {
                    summary += "；\(report.failedDevices.count) 台设备的密文无法读取"
                }
                syncMessage = summary + "。"
                store.refresh()
            } catch {
                message = describe(error)
            }
            busy = false
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
