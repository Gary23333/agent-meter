import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// The 桌宠 tab: the pet living in the panel (the same page and the same frames as the desktop one), a gallery of
/// forms, every state to try, what the pet is wired to, and its settings. Nothing here changes data: trying a
/// state only changes what this stage shows.
struct PetTabView: View {
    @Environment(UsageStore.self) private var store
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme
    @AppStorage("petTabSettingsOpen") private var settingsOpen = false
    @State private var packs: [PetResources.Pack] = []
    @State private var dropTargeted = false

    private let prefs = PetPrefs.shared
    private let feed = PetFeed.shared
    private let stage = PetStageHost.shared
    private let thumbnails = PetThumbnails.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            stageCard
            desktopCard
            galleryCard
            statesCard
            linkageCard
            settingsCard
        }
        .onAppear {
            packs = PetResources.allPacks()
            stage.attach()
        }
        .onDisappear { stage.detach() }
        .task(id: thumbnailKey) {
            thumbnails.ensure(packs, theme: store.theme.rawValue, scheme: scheme == .dark ? "dark" : "light")
        }
    }

    private var thumbnailKey: String {
        "\(store.theme.rawValue)|\(scheme == .dark)|" + packs.map(\.id).joined(separator: ",")
    }

    private var status: PetStatus? { feed.status }
    private var shownID: String { stage.previewID ?? status?.state ?? "idle" }

    // MARK: Colours

    private func color(_ tone: PetStateTone) -> Color {
        switch tone {
        case .calm: return theme.health(100)
        case .active: return theme == .minimal ? .primary : theme.accent[0]
        case .warn: return theme.health(35)
        case .danger: return theme.health(5)
        case .quiet: return .secondary
        }
    }

    // MARK: Stage

    private var stageCard: some View {
        Card {
            HStack(spacing: 8) {
                stateBadge
                Spacer(minLength: 8)
                if stage.previewID != nil {
                    Button { stage.endPreview() } label: {
                        Label("回到真实状态", systemImage: "arrow.uturn.backward")
                            .font(theme.font(10.5, weight: .semibold))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(theme == .minimal ? Color.primary : theme.accent[0])
                } else if let updated = feed.updatedAt {
                    Text("更新于 " + Fmt.ago(updated, now: store.now)).font(theme.font(10.5)).themeForeground(.tertiary)
                }
            }
            stageSurface
            Text(stage.previewID != nil ? "这是试玩，真实的桌宠和数据没有变化。" : (status?.summaryLine(now: store.now) ?? "正在连接桌宠大脑…"))
                .font(theme.font(11.5, weight: .medium))
                .themeForeground(.secondary)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
            if stage.previewID == nil, let status, !status.explanation.isEmpty {
                Text("判断依据：" + status.explanation.joined(separator: " · "))
                    .font(theme.font(10))
                    .themeForeground(.tertiary)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var stateBadge: some View {
        let info = PetCatalog.info(shownID)
        let tone = info?.tone ?? .quiet
        return HStack(spacing: 6) {
            Circle().fill(color(tone)).frame(width: 8, height: 8).themeGlow(color(tone), radius: 4, theme: theme)
            Text(info?.label ?? shownID).font(theme.font(12.5, weight: .semibold))
            if stage.previewID != nil {
                Text("预览")
                    .font(theme.font(9.5, weight: .semibold))
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(Capsule().fill(Color.primary.opacity(0.1)))
            }
        }
    }

    @ViewBuilder private var stageSurface: some View {
        Group {
            if let problem = stage.problem, !stage.ready {
                VStack(spacing: 6) {
                    Image(systemName: "exclamationmark.triangle").font(.system(size: 20)).foregroundStyle(.orange)
                    Text(problem).font(theme.font(11)).themeForeground(.secondary).multilineTextAlignment(.center)
                }
                .padding(20)
            } else {
                PetStageView()
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 252)
        .background { stageBackdrop }
        .background { if !stage.ready && stage.problem == nil { ProgressView().controlSize(.small) } }
        .clipShape(RoundedRectangle(cornerRadius: theme == .neon ? 6 : 12, style: .continuous))
    }

    @ViewBuilder private var stageBackdrop: some View {
        let shape = RoundedRectangle(cornerRadius: theme == .neon ? 6 : 12, style: .continuous)
        switch theme {
        case .minimal:
            shape.fill(Color.primary.opacity(0.035))
        case .native:
            shape.fill(Color(nsColor: .windowBackgroundColor).opacity(0.8))
                .overlay(shape.strokeBorder(Color(nsColor: .separatorColor).opacity(0.5), lineWidth: 0.5))
        default:
            shape.fill(LinearGradient(colors: [theme.accent[0].opacity(scheme == .dark ? 0.16 : 0.10),
                                               theme.accent[1].opacity(scheme == .dark ? 0.05 : 0.03)],
                                      startPoint: .top, endPoint: .bottom))
                .overlay(shape.strokeBorder(theme.accent[0].opacity(0.2), lineWidth: 0.6))
        }
    }

    // MARK: On the desktop

    private var desktopCard: some View {
        Card {
            HStack(spacing: 10) {
                Image(systemName: "macwindow.on.rectangle")
                    .font(.system(size: 17, weight: .medium))
                    .foregroundStyle(theme == .minimal ? Color.primary : theme.accent[0])
                    .frame(width: 26)
                VStack(alignment: .leading, spacing: 2) {
                    Text("在桌面上陪着我").font(theme.font(13, weight: .semibold))
                    Text(prefs.enabled ? "已在桌面显示：可以拖动，空白处点击会穿透到下面的窗口。" : "打开后它会悬浮在所有窗口之上，不抢焦点。")
                        .font(theme.font(10.5)).themeForeground(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                Toggle("在桌面显示桌宠", isOn: Binding(get: { prefs.enabled }, set: { prefs.enabled = $0 }))
                    .labelsHidden()
                    .toggleStyle(.switch)
            }
        }
    }

    // MARK: Forms

    private var galleryCard: some View {
        Card {
            SectionTitle(text: "形象", trailing: "\(packs.count) 个")
            ScrollViewReader { proxy in
                ScrollView(.horizontal) {
                    HStack(spacing: 10) {
                        ForEach(packs) { pack in packTile(pack).id(pack.id) }
                    }
                    .padding(.vertical, 2)
                    .padding(.horizontal, 1)
                }
                .scrollIndicators(.never)
                .onChange(of: packs) { _, _ in proxy.scrollTo(prefs.packID, anchor: .center) }
                .onChange(of: prefs.packID) { _, id in withAnimation { proxy.scrollTo(id, anchor: .center) } }
            }
            if let pack = packs.first(where: { $0.id == prefs.packID }) {
                Text(packCaption(pack)).font(theme.font(10.5)).themeForeground(.tertiary)
            }
            Text("把 .agentpet 形象包拖到这里即可安装（会先校验）。")
                .font(theme.font(10)).themeForeground(.tertiary)
        }
        .overlay {
            if dropTargeted {
                RoundedRectangle(cornerRadius: theme == .neon ? 6 : 12, style: .continuous)
                    .strokeBorder(theme == .minimal ? Color.primary : theme.accent[0], style: StrokeStyle(lineWidth: 1.6, dash: [5, 4]))
            }
        }
        .onDrop(of: [UTType.fileURL], isTargeted: $dropTargeted) { providers in
            guard !providers.isEmpty else { return false }
            Task { @MainActor in
                let urls = await PetInstaller.urls(from: providers)
                guard !urls.isEmpty else { return }
                PetController.shared.installDropped(urls) { packs = PetResources.allPacks() }
            }
            return true
        }
    }

    private func packTile(_ pack: PetResources.Pack) -> some View {
        let selected = pack.id == prefs.packID
        let shape = RoundedRectangle(cornerRadius: theme == .neon ? 6 : 12, style: .continuous)
        return Button { prefs.packID = pack.id } label: {
            VStack(spacing: 4) {
                ZStack {
                    shape.fill(Color.primary.opacity(0.05))
                    if let image = thumbnails.images[pack.id] {
                        Image(nsImage: image).resizable().interpolation(.high).scaledToFit().padding(5)
                    } else if thumbnails.failed.contains(pack.id) {
                        Image(systemName: "questionmark.square.dashed").font(.system(size: 20)).themeForeground(.tertiary)
                    } else {
                        ProgressView().controlSize(.small)
                    }
                }
                .frame(width: 76, height: 82)
                .overlay(shape.strokeBorder(selected ? AnyShapeStyle(theme == .minimal ? Color.primary : theme.accent[0])
                                                     : AnyShapeStyle(Color.primary.opacity(0.1)),
                                            lineWidth: selected ? 2 : 0.6))
                Text(pack.name).font(theme.font(11, weight: selected ? .semibold : .regular)).lineLimit(1)
                Text(pack.builtin ? (pack.renderer == "sprite" ? "精灵图" : "3D") : "自制")
                    .font(theme.font(9)).themeForeground(.tertiary)
            }
            .frame(width: 76)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("切换到「\(pack.name)」" + (prefs.enabled ? "（桌面上的桌宠也会换）" : ""))
    }

    private func packCaption(_ pack: PetResources.Pack) -> String {
        let kind = pack.renderer == "sprite" ? "逐帧精灵图" : "three.js 实时 3D"
        return "\(pack.name) · \(kind) · \(pack.builtin ? "内置" : "自制")"
    }

    // MARK: States

    private var statesCard: some View {
        Card {
            SectionTitle(text: "状态", trailing: "点一下，看它这时的样子")
            FlowLayout(spacing: 6, lineSpacing: 6) {
                ForEach(PetCatalog.states) { info in chip(info, reaction: false) }
            }
            SectionTitle(text: "短反应")
            FlowLayout(spacing: 6, lineSpacing: 6) {
                ForEach(PetCatalog.reactions) { info in chip(info, reaction: true) }
            }
            if let info = PetCatalog.info(shownID) {
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: info.symbol).font(.system(size: 11, weight: .semibold)).foregroundStyle(color(info.tone)).frame(width: 14)
                    Text((stage.previewID != nil ? "试玩「\(info.label)」：" : "现在是「\(info.label)」：") + info.trigger)
                        .font(theme.font(11)).themeForeground(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func chip(_ info: PetStateInfo, reaction: Bool) -> some View {
        let selected = !reaction && stage.previewID == info.id
        let live = !reaction && stage.previewID == nil && status?.state == info.id
        return Button {
            if reaction { stage.previewReaction(info.id) } else { stage.previewState(info.id) }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: info.symbol).font(.system(size: 10, weight: .semibold))
                Text(info.label).font(theme.font(11, weight: .medium))
            }
            .padding(.horizontal, 9).padding(.vertical, 5)
            .foregroundStyle(selected ? selectedChipText : (live ? color(info.tone) : theme.textColor(.primary, scheme: scheme)))
            .background { Capsule().fill(selected ? selectedChipFill : AnyShapeStyle(Color.primary.opacity(0.06))) }
            .overlay { if live { Capsule().strokeBorder(color(info.tone), lineWidth: 1.2) } }
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .help(info.trigger)
    }

    private var selectedChipFill: AnyShapeStyle {
        switch theme {
        case .minimal: return AnyShapeStyle(Color.primary)
        case .native: return AnyShapeStyle(Color.accentColor)
        default: return AnyShapeStyle(LinearGradient(colors: theme.accent, startPoint: .leading, endPoint: .trailing))
        }
    }

    private var selectedChipText: Color {
        switch theme {
        case .minimal: return Color(nsColor: .textBackgroundColor)
        case .native, .porcelain, .aurora: return .white
        case .titanium: return Color(red: 0.055, green: 0.08, blue: 0.11)
        case .neon, .prism: return Color(red: 0.025, green: 0.035, blue: 0.06)
        }
    }

    // MARK: Wiring

    private var linkageCard: some View {
        Card {
            SectionTitle(text: "联动", trailing: "它读到了什么")
            if let status {
                energyRow(status)
                InfoRow(symbol: "terminal", title: "运行中的会话", value: status.running > 0 ? "\(status.running) 个" : "没有",
                        detail: sessionDetail(status), valueTint: status.running > 0 ? theme.health(100) : .secondary)
                if let tokens = status.todayTokens {
                    InfoRow(symbol: "sum", title: "今日 Token", value: Fmt.tokens(tokens))
                }
                if let forecast = status.forecastMood, forecast == "resetting" || forecast == "excited" {
                    InfoRow(symbol: "sparkles", title: "重置预测", value: forecast == "resetting" ? "快重置了" : "有戏")
                }
            } else {
                Text("还没连上桌宠大脑（本机后端）。").font(theme.font(11.5)).themeForeground(.secondary)
            }
            remindersBlock
            focusRow
            eventsRow
            Toggle("提醒交给桌宠气泡（代替系统通知）", isOn: Binding(get: { prefs.takeoverAlerts }, set: { prefs.takeoverAlerts = $0 }))
                .font(theme.font(12))
                .toggleStyle(.switch)
                .controlSize(.small)
                .disabled(!prefs.enabled)
                .help(prefs.enabled ? "额度不足、重置卡到期等提醒改由桌面上的桌宠说出来" : "先在桌面上显示桌宠")
            hooksRow
            actionsRow
        }
    }

    /// What the pet would announce right now. The stage stays quiet about these (the desktop pet or a system
    /// notification says them), so they are listed here, with a way to the page they are about.
    @ViewBuilder private var remindersBlock: some View {
        if let reminders = status?.reminders, !reminders.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                ForEach(reminders.prefix(3)) { reminder in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: "bell.fill").font(.system(size: 10.5)).foregroundStyle(reminderColor(reminder.tone)).frame(width: 14)
                        Text(reminder.text).font(theme.font(11.5)).themeForeground(.secondary).fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 6)
                        if let tab = reminder.tab, Tab(rawValue: tab) != nil {
                            smallButton("查看") { UserDefaults.standard.set(tab, forKey: "panelTab") }
                        }
                    }
                }
                if reminders.count > 3 {
                    Text("还有 \(reminders.count - 3) 条").font(theme.font(10.5)).themeForeground(.tertiary).padding(.leading, 22)
                }
            }
        }
    }

    private func reminderColor(_ tone: String) -> Color {
        switch tone {
        case "danger": return theme.health(5)
        case "warn": return theme.health(35)
        case "good": return theme.health(100)
        default: return .secondary
        }
    }

    private var actionsRow: some View {
        HStack(spacing: 8) {
            Image(systemName: "bolt").font(.system(size: 11, weight: .medium)).themeForeground(.tertiary).frame(width: 14)
            Text("快捷操作").font(theme.font(12)).themeForeground(.secondary)
            Spacer(minLength: 8)
            smallButton("立即刷新") { store.refresh() }
            smallButton("分享用量报告…") { ReportWindow.show() }
        }
        .frame(minHeight: 22)
    }

    private func energyRow(_ s: PetStatus) -> some View {
        let e = s.energy
        let value: String
        var detail: String?
        var tint: Color = .secondary
        if e.known, let remaining = e.remaining {
            value = Fmt.percent(remaining.rounded())
            var parts = [e.label ?? "额度"]
            if let reset = e.resetsAt { parts.append(Fmt.shortCountdown(to: reset, now: store.now, past: "待刷新")) }
            detail = parts.joined(separator: " · ") + (e.drivesState ? "" : "（没在用，不影响状态）")
            tint = theme.health(remaining)
        } else {
            value = e.stale ? "已过期" : "未知"
            detail = e.stale ? "超过 20 分钟没刷新，不会当成 0%" : "还没读到百分比额度"
        }
        return Button {
            UserDefaults.standard.set("accounts", forKey: "panelTab")
        } label: {
            InfoRow(symbol: "gauge.with.dots.needle.67percent", title: "在用的额度", value: value, detail: detail, valueTint: tint)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("打开「账户额度」")
    }

    private func sessionDetail(_ s: PetStatus) -> String? {
        let parts = s.sessions.prefix(3).map { $0.label + ($0.count > 1 ? " ×\($0.count)" : "") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    @ViewBuilder private var focusRow: some View {
        HStack(spacing: 8) {
            Image(systemName: "timer").font(.system(size: 11, weight: .medium)).themeForeground(.tertiary).frame(width: 14)
            if let end = status?.focusEndsAt {
                Text("专注中，还剩 " + Fmt.shortCountdown(to: end, now: store.now, past: "不到 1 分")).font(theme.font(12)).themeForeground(.secondary)
                Spacer(minLength: 8)
                smallButton("结束") { feed.emit(["kind": "focus_stop"]) }
            } else {
                Text("专注计时").font(theme.font(12)).themeForeground(.secondary)
                Spacer(minLength: 8)
                smallButton("25 分钟") { feed.emit(["kind": "focus_start", "minutes": 25]) }
                smallButton("50 分钟") { feed.emit(["kind": "focus_start", "minutes": 50]) }
            }
        }
        .frame(minHeight: 22)
    }

    private func smallButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(theme.font(11, weight: .medium))
                .padding(.horizontal, 9).padding(.vertical, 4)
                .background(Capsule().fill(Color.primary.opacity(0.07)))
                .overlay(Capsule().strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.5))
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder private var eventsRow: some View {
        let events = (status?.events ?? []).filter { $0.kind.hasPrefix("agent_") }.suffix(3).reversed()
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: "point.3.connected.trianglepath.dotted").font(.system(size: 11, weight: .medium)).themeForeground(.tertiary).frame(width: 14)
            VStack(alignment: .leading, spacing: 2) {
                Text("Agent 事件（hooks）").font(theme.font(12)).themeForeground(.secondary)
                if events.isEmpty {
                    Text("还没收到。接入后，Claude Code / Codex 开始、完成、等你确认、出错时它都会知道。")
                        .font(theme.font(10.5)).themeForeground(.tertiary).fixedSize(horizontal: false, vertical: true)
                } else {
                    ForEach(Array(events)) { event in
                        Text("\(PetTabView.eventText(event)) · \(Fmt.ago(event.at, now: store.now))")
                            .font(theme.font(10.5)).themeForeground(.tertiary)
                    }
                }
            }
            Spacer(minLength: 0)
        }
    }

    static func eventText(_ event: PetStatus.Event) -> String {
        let who = event.source.map { Catalog.brand($0).name == $0 ? $0 : Catalog.brand($0).name } ?? "Agent"
        switch event.kind {
        case "agent_started": return who + " 开始了"
        case "agent_done": return who + " 完成了"
        case "agent_waiting": return who + " 在等你"
        case "agent_failed": return who + " 出错了"
        default: return who
        }
    }

    private var hooksRow: some View {
        HStack(spacing: 8) {
            Image(systemName: "link").font(.system(size: 11, weight: .medium)).themeForeground(.tertiary).frame(width: 14)
            Text("接入 Claude Code / Codex").font(theme.font(12)).themeForeground(.secondary)
            Spacer(minLength: 8)
            smallButton("复制 Claude 命令") { copy(PetHooks.command(target: "claude", project: store.projectDirectory)) }
            smallButton("Codex") { copy(PetHooks.command(target: "codex", project: store.projectDirectory)) }
        }
        .help("复制后在终端运行，会打印要粘贴进配置文件的内容。只打印，不会替你改任何文件。")
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    // MARK: Settings

    private var settingsCard: some View {
        Card {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) { settingsOpen.toggle() }
            } label: {
                HStack {
                    Text("设置").font(theme.font(11.5, weight: .semibold)).themeForeground(.secondary)
                    Spacer()
                    Image(systemName: settingsOpen ? "chevron.up" : "chevron.down").font(.system(size: 9, weight: .semibold)).themeForeground(.tertiary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if settingsOpen {
                settingRow("大小") {
                    PillTabs(items: PetSize.allCases, title: { $0.label },
                             selection: Binding(get: { prefs.size }, set: { prefs.size = $0 }), small: true)
                        .frame(width: 150)
                }
                settingRow("桌面上的额度显示") {
                    Picker("", selection: Binding(get: { prefs.hud }, set: { prefs.hud = $0 })) {
                        ForEach(PetHUD.allCases) { Text($0.label).tag($0) }
                    }
                    .labelsHidden().pickerStyle(.menu).fixedSize()
                }
                settingRow("参考哪个来源的额度") {
                    Picker("", selection: Binding(get: { prefs.energySource }, set: { prefs.energySource = $0 })) {
                        Text("自动（跟着我在用的）").tag("auto")
                        ForEach(energySources, id: \.self) { Text(Catalog.brand($0).name).tag($0) }
                    }
                    .labelsHidden().pickerStyle(.menu).fixedSize()
                }
                settingRow("久坐提醒") {
                    Picker("", selection: Binding(get: { prefs.breakMinutes }, set: { prefs.breakMinutes = $0 })) {
                        Text("关闭").tag(0)
                        Text("连续 1 小时").tag(60)
                        Text("连续 2 小时").tag(120)
                        Text("连续 3 小时").tag(180)
                    }
                    .labelsHidden().pickerStyle(.menu).fixedSize()
                }
                settingRow("免打扰（它会去睡觉）") {
                    Picker("", selection: Binding(get: { prefs.quietHours ?? "" }, set: { prefs.quietHours = $0.isEmpty ? nil : $0 })) {
                        Text("不设置").tag("")
                        Text("23:00 – 08:00").tag("23:00-08:00")
                        Text("00:00 – 08:00").tag("00:00-08:00")
                        Text("22:00 – 07:00").tag("22:00-07:00")
                    }
                    .labelsHidden().pickerStyle(.menu).fixedSize()
                }
                Toggle("眼睛跟随光标", isOn: Binding(get: { prefs.followCursor }, set: { prefs.followCursor = $0 }))
                    .font(theme.font(12)).toggleStyle(.switch).controlSize(.small)
                Toggle("漫游（在屏幕里慢慢走动）", isOn: Binding(get: { prefs.roam }, set: { prefs.roam = $0 }))
                    .font(theme.font(12)).toggleStyle(.switch).controlSize(.small)
                    .disabled(!prefs.enabled)
                    .help(prefs.enabled ? "拖动、点击或免打扰时它会停下来" : "先在桌面上显示桌宠")
                Toggle("安静模式（少说话、不乱动）", isOn: Binding(get: { prefs.calm }, set: { prefs.calm = $0 }))
                    .font(theme.font(12)).toggleStyle(.switch).controlSize(.small)
                HStack(spacing: 8) {
                    smallButton("打开形象文件夹") { PetController.shared.openUserFolder() }
                    smallButton("重新读取形象") { packs = PetResources.allPacks() }
                    Spacer(minLength: 0)
                }
                Text("想做自己的形象？在 Claude Code 里用 agentmeter-pet-three（程序化 3D）或 agentmeter-pet-imagegen（生图 + 精灵图）技能，做好后放进形象文件夹即可。")
                    .font(theme.font(10.5)).themeForeground(.tertiary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func settingRow<Control: View>(_ title: String, @ViewBuilder control: () -> Control) -> some View {
        HStack(spacing: 8) {
            Text(title).font(theme.font(12)).themeForeground(.secondary).lineLimit(1)
            Spacer(minLength: 8)
            control()
        }
        .frame(minHeight: 24)
    }

    /// The sources the pet can be pinned to: whatever it currently has a meter for, plus the pinned one.
    private var energySources: [String] {
        var list: [String] = []
        for meter in status?.meters ?? [] where !list.contains(meter.source) { list.append(meter.source) }
        if prefs.energySource != "auto", !list.contains(prefs.energySource) { list.append(prefs.energySource) }
        return list
    }
}

// MARK: - Helpers

/// What to run in a terminal to print the hook / notify configuration for a tool. The text itself comes from the
/// backend CLI (`agent_meter pet hooks`), so there is one source of truth; nothing is ever applied automatically.
enum PetHooks {
    static func command(target: String, project: URL?, resources: URL? = Bundle.main.resourceURL, port: Int = BackendClient.port,
                        fileManager: FileManager = .default) -> String {
        func quote(_ text: String) -> String { "'" + text.replacingOccurrences(of: "'", with: "'\\''") + "'" }
        let portFlag = port == BackendClient.defaultPort ? "" : " --port \(port)"
        let tail = "pet\(portFlag) hooks \(target)"
        if let executable = resources?.appendingPathComponent("backend/agent-meter-backend"),
           fileManager.isExecutableFile(atPath: executable.path) {
            return "\(quote(executable.path)) \(tail)"
        }
        if let project { return "cd \(quote(project.path)) && python3 -m agent_meter \(tail)" }
        return "python3 -m agent_meter \(tail)"
    }
}

/// Chips that wrap onto as many lines as they need.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 6

    private struct Placement {
        var points: [CGPoint] = []
        var size = CGSize.zero
    }

    private func arrange(_ subviews: Subviews, width: CGFloat) -> Placement {
        var placement = Placement()
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, usedWidth: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width {
                x = 0
                y += rowHeight + lineSpacing
                rowHeight = 0
            }
            placement.points.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            usedWidth = max(usedWidth, x - spacing)
        }
        placement.size = CGSize(width: usedWidth, height: y + rowHeight)
        return placement
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        let placement = arrange(subviews, width: width)
        return CGSize(width: proposal.width ?? placement.size.width, height: placement.size.height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let placement = arrange(subviews, width: bounds.width)
        for (view, point) in zip(subviews, placement.points) {
            view.place(at: CGPoint(x: bounds.minX + point.x, y: bounds.minY + point.y), proposal: .unspecified)
        }
    }
}
