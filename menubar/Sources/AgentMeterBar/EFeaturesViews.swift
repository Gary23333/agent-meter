import SwiftUI

private func countText(_ n: Int) -> String { Fmt.tokens(Double(n)) }

// MARK: - E2 项目归因

struct ProjectItem: Identifiable {
    let path: String
    let tokens: Int
    let requests: Int
    let apps: [(name: String, tokens: Int)]
    var id: String { path }
}

struct ProjectsFeed {
    let items: [ProjectItem]
    let attributed: Int
    let total: Int
    let unattributed: Int
    let unattributedApps: [(name: String, tokens: Int)]
    let gaps: [(source: String, reason: String)]

    init(_ json: JSON) {
        items = json["projects"].array.compactMap { row in
            guard let path = row["project_path"].string, !path.isEmpty else { return nil }
            let apps = row["apps"].object.map { key, value in
                (name: key, tokens: Int(value["tokens"].double ?? 0))
            }.sorted { $0.tokens > $1.tokens }
            return ProjectItem(path: path, tokens: Int(row["tokens"].double ?? 0),
                               requests: Int(row["requests"].double ?? 0), apps: apps)
        }
        attributed = Int(json["attributed_tokens"].double ?? 0)
        total = Int(json["total_tokens"].double ?? 0)
        unattributed = Int(json["unattributed"]["tokens"].double ?? 0)
        unattributedApps = json["unattributed"]["by_app"].object.map { key, value in
            (name: key, tokens: Int(value["tokens"].double ?? 0))
        }.sorted { $0.tokens > $1.tokens }
        gaps = json["source_gaps"].array.compactMap { row in
            guard let source = row["source"].string else { return nil }
            return (source: source, reason: row["reason"].string ?? "")
        }
    }
}

enum ProjectAliases {
    static func decode(_ raw: String) -> [String: String] {
        guard let data = raw.data(using: .utf8),
              let dict = try? JSONDecoder().decode([String: String].self, from: data) else { return [:] }
        return dict.filter { !$0.value.trimmingCharacters(in: .whitespaces).isEmpty }
    }

    static func encode(_ aliases: [String: String]) -> String {
        guard let data = try? JSONEncoder().encode(aliases) else { return "{}" }
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    static func display(_ path: String, aliases: [String: String]) -> String {
        if let alias = aliases[path] { return alias }
        return (path as NSString).lastPathComponent
    }
}

/// 项目归因：折叠在「应用」页底部，默认收起；数据来自 /v1/projects 投影（120 秒节流），不触发全量采集。
struct ProjectsSection: View {
    @Environment(UsageStore.self) private var store
    @AppStorage("projectAliasesData") private var aliasesRaw = "{}"
    @AppStorage("projectsSectionExpanded") private var expanded = false
    @State private var renamed: ProjectItem?

    private var aliases: [String: String] { ProjectAliases.decode(aliasesRaw) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Card {
                HStack(spacing: 8) {
                    Button {
                        withAnimation(.easeInOut(duration: 0.2)) { expanded.toggle() }
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "folder").foregroundStyle(.secondary).frame(width: 22)
                            VStack(alignment: .leading, spacing: 3) {
                                Text("项目").font(.system(size: 13, weight: .semibold))
                                Text(store.projects == nil ? "正在读取项目归因…" : "按工作目录归因本机用量")
                                    .font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if let feed = store.projects {
                                Text("已归因 \(countText(feed.attributed)) / 总计 \(countText(feed.total))")
                                    .font(.caption).monospacedDigit()
                            }
                            Image(systemName: expanded ? "chevron.up" : "chevron.down").font(.caption2)
                        }
                        .contentShape(Rectangle())
                    }.buttonStyle(.plain)
                    IconButton(symbol: "arrow.clockwise", help: "刷新项目归因") {
                        Task { await store.loadProjects(force: true) }
                    }
                }
            }
            if expanded {
                if let feed = store.projects {
                    if feed.items.isEmpty {
                        Card { Text("暂无可归因的项目记录。").font(.system(size: 12)).themeForeground(.secondary) }
                    }
                    ForEach(feed.items.prefix(30)) { item in
                        ProjectRowView(item: item, display: ProjectAliases.display(item.path, aliases: aliases)) {
                            renamed = item
                        }
                    }
                    if feed.unattributed > 0 || !feed.unattributedApps.isEmpty {
                        Card {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("未归属：\(countText(feed.unattributed))")
                                    .font(.system(size: 12, weight: .medium))
                                if !feed.unattributedApps.isEmpty {
                                    Text(feed.unattributedApps.prefix(4).map { "\(Catalog.appLabel($0.name)) \(countText($0.tokens))" }
                                        .joined(separator: " · "))
                                        .font(.system(size: 10.5)).themeForeground(.secondary)
                                }
                                Text("没有明确项目路径的账本（如 Kimi、Claude、导入历史等）不做推测，统一进未归属。")
                                    .font(.system(size: 10)).themeForeground(.secondary)
                            }
                        }
                    }
                    if !feed.gaps.isEmpty {
                        Text("读取缺口：" + feed.gaps.prefix(4).map { "\(Catalog.brand($0.source).name)（\(Catalog.reason($0.reason))）" }.joined(separator: "、"))
                            .font(.system(size: 10)).themeForeground(.secondary)
                    }
                    Text("项目路径仅在本机显示；分享时使用你起的别名。")
                        .font(.system(size: 10)).themeForeground(.secondary)
                } else {
                    ProgressView().controlSize(.small).frame(maxWidth: .infinity)
                }
            }
        }
        .task { await store.loadProjects() }
        .sheet(item: $renamed) { item in
            ProjectRenameSheet(item: item, current: ProjectAliases.display(item.path, aliases: aliases)) { alias in
                var updated = aliases
                let trimmed = alias.trimmingCharacters(in: .whitespaces)
                if trimmed.isEmpty { updated.removeValue(forKey: item.path) } else { updated[item.path] = trimmed }
                aliasesRaw = ProjectAliases.encode(updated)
                renamed = nil
            }
        }
    }
}

private struct ProjectRowView: View {
    let item: ProjectItem
    let display: String
    let onRename: () -> Void

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(display).font(.system(size: 12.5, weight: .medium)).lineLimit(1)
                    Spacer()
                    Text(countText(item.tokens)).font(.system(size: 12, weight: .semibold, design: .rounded))
                }
                HStack(spacing: 6) {
                    Text("\(item.requests) 次请求").font(.system(size: 10.5)).themeForeground(.secondary)
                    ForEach(item.apps.prefix(3), id: \.name) { app in
                        Text(Catalog.appLabel(app.name))
                            .font(.system(size: 9.5))
                            .padding(.horizontal, 5).padding(.vertical, 1.5)
                            .background(Catalog.appTint(app.name).opacity(0.14), in: Capsule())
                    }
                    Spacer()
                }
            }
        }
        .contextMenu {
            Button("重命名…") { onRename() }
        }
    }
}

private struct ProjectRenameSheet: View {
    let item: ProjectItem
    let current: String
    let onSave: (String) -> Void
    @State private var text: String = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("重命名项目").font(.system(size: 15, weight: .semibold))
            Text(item.path).font(.system(size: 10)).themeForeground(.secondary).lineLimit(2)
            TextField("别名", text: $text, prompt: Text(current))
            HStack {
                Spacer()
                Button("取消") { dismiss() }
                Button("保存") { onSave(text) }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 360)
        .onAppear { text = current }
    }
}

// MARK: - E3 周期环比

struct PeriodReport {
    let currentTokens: Int
    let currentCost: Double
    let currentDays: Int
    let previousTokens: Int
    let previousCost: Double
    let tokensPct: Double?
    let costPct: Double?
    let cacheChange: Double?
    let movers: [(model: String, delta: Int)]
    let basis: String
    let gaps: [String]

    init(_ json: JSON) {
        func money(_ row: JSON) -> Double { row["cost_cny"].double ?? 0 }
        currentTokens = Int(json["current"]["tokens"].double ?? 0)
        currentCost = money(json["current"])
        currentDays = Int(json["current"]["days_with_data"].double ?? 0)
        previousTokens = Int(json["previous"]["tokens"].double ?? 0)
        previousCost = money(json["previous"])
        tokensPct = json["delta"]["tokens_pct"].double
        costPct = json["delta"]["cost_pct"].double
        cacheChange = json["delta"]["cache_hit_rate_change"].double
        movers = json["top_movers"].array.compactMap { row in
            guard let model = row["model"].string else { return nil }
            return (model: model, delta: Int(row["delta_tokens"].double ?? 0))
        }
        basis = json["basis"].string ?? ""
        gaps = json["sources_without_daily_detail"].array.compactMap(\.string)
    }
}

struct PeriodCompareCard: View {
    @Environment(UsageStore.self) private var store
    @AppStorage("periodCompareKind") private var kind = "week"

    private var report: PeriodReport? { kind == "week" ? store.weekReport : store.monthReport }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(kind == "week" ? "本周环比" : "本月环比")
                        .font(.system(size: 12.5, weight: .medium))
                    Spacer()
                    Picker("", selection: $kind) {
                        Text("周").tag("week")
                        Text("月").tag("month")
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .frame(width: 88)
                }
                if let report {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(countText(report.currentTokens)).font(.system(size: 16, weight: .semibold, design: .rounded))
                        Text(pct(report.tokensPct)).font(.system(size: 11, weight: .medium))
                            .themeForeground((report.tokensPct ?? 0) >= 0 ? .primary : .secondary)
                        Spacer()
                        Text("上期 \(countText(report.previousTokens))").font(.system(size: 10.5)).themeForeground(.secondary)
                    }
                    Text("估算费用 \(Fmt.amount(report.currentCost, unit: "CNY"))  ·  \(pct(report.costPct))  ·  有效 \(report.currentDays) 天")
                        .font(.system(size: 10.5)).themeForeground(.secondary)
                    if !report.movers.isEmpty {
                        Text("变动主要来自：" + report.movers.prefix(3).map {
                            "\(Catalog.modelLabel($0.model)) \($0.delta >= 0 ? "+" : "")\(countText(abs($0.delta)))"
                        }.joined(separator: "、"))
                            .font(.system(size: 10)).themeForeground(.secondary)
                    }
                    Text(report.basis == "daily_rollup_base_price_no_peak_split"
                         ? "按日汇总基准价估算，非账单；当期截至现在。" : "估算口径见后端说明。")
                        .font(.system(size: 9.5)).themeForeground(.secondary)
                    if !report.gaps.isEmpty {
                        Text("无逐日分项来源：" + report.gaps.prefix(4).joined(separator: "、")).font(.system(size: 9.5)).themeForeground(.secondary)
                    }
                } else {
                    ProgressView().controlSize(.small)
                }
            }
        }
        .task(id: kind) { await store.loadReport(kind: kind) }
    }

    private func pct(_ value: Double?) -> String {
        guard let value else { return "—" }
        return String(format: "%@%.1f%%", value >= 0 ? "+" : "", value)
    }
}

// MARK: - E4 数据状态与省资源

struct StatusFeed {
    struct Row: Identifiable {
        let id: String
        let status: String
        let reason: String?
        let observed: String?
        let lastError: String?
    }
    let rows: [Row]
    let stale: [String]
    let unpriced: [String]
    let disabled: [String]
    let lowResource: Bool
    let skipped: [String]
    let ttl: Int
    let snapshotAt: String?
    let fromCache: Bool

    init(_ json: JSON) {
        rows = json["sources"].array.compactMap { row in
            guard let id = row["id"].string else { return nil }
            return Row(id: id, status: row["status"].string ?? "unknown",
                       reason: row["reason"].string,
                       observed: row["observed_at"]["display"].string,
                       lastError: row["last_error"].string)
        }
        stale = json["stale_sources"].array.compactMap(\.string)
        unpriced = json["unpriced_models"].array.compactMap(\.string)
        disabled = json["disabled_sources"].array.compactMap(\.string)
        lowResource = json["low_resource_mode"].bool ?? false
        skipped = json["skipped_ledgers"].array.compactMap(\.string)
        ttl = Int(json["cache_ttl_seconds"].double ?? 120)
        snapshotAt = json["snapshot_at"]["display"].string
        fromCache = json["served_from_cache"].bool ?? false
    }
}

@MainActor
enum DataStatusWindow {
    private static var window: NSWindow?

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 470, height: 560),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            w.title = "数据状态与省资源"
            w.isReleasedWhenClosed = false
            w.contentViewController = NSHostingController(rootView: DataStatusView().environment(UsageStore.shared))
            w.center()
            window = w
        }
        StatusBarController.shared.closePanel()
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
        window?.orderFrontRegardless()
    }
}

struct DataStatusView: View {
    @Environment(UsageStore.self) private var store

    private static let candidateLedgers = ["opencode", "gemini", "deepseek_harness", "kimi_desktop",
                                           "kimi_legacy", "mimo_code", "deveco", "codex", "claude",
                                           "workbuddy", "antigravity", "zcode"]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("数据状态").font(.system(size: 16, weight: .semibold, design: .rounded))
                    Spacer()
                    IconButton(symbol: "arrow.clockwise", help: "刷新状态") {
                        Task { await store.loadStatus(force: true); await store.fetch(force: false) }
                    }
                }
                if let feed = store.statusFeed {
                    Text("快照 \(feed.snapshotAt ?? "未知")\(feed.fromCache ? " · 缓存命中" : "") · 缓存 TTL \(feed.ttl) 秒")
                        .font(.system(size: 10.5)).themeForeground(.secondary)
                    ForEach(feed.rows) { row in
                        HStack(spacing: 8) {
                            Circle().fill(Catalog.statusColor(row.status)).frame(width: 7, height: 7)
                            Text(Catalog.brand(row.id).name).font(.system(size: 11.5)).lineLimit(1)
                            Spacer()
                            Text(Catalog.statusLabel(row.status)).font(.system(size: 10.5))
                                .themeForeground(.secondary)
                            if let reason = row.reason, !reason.isEmpty {
                                Text(Catalog.reason(reason)).font(.system(size: 10)).themeForeground(.secondary).lineLimit(1)
                            }
                        }
                    }
                    if !feed.unpriced.isEmpty {
                        Text("未计价模型：\(feed.unpriced.prefix(8).map(Catalog.modelLabel).joined(separator: "、"))")
                            .font(.system(size: 10.5)).themeForeground(.secondary)
                    }
                    Divider()
                    Toggle("省资源模式（刷新间隔变为 3 倍）", isOn: Binding(get: { store.lowResourceMode },
                                                                    set: { store.lowResourceMode = $0 }))
                        .font(.system(size: 12))
                    if store.lowResourceMode {
                        Text("跳过高开销账本（下载/解析量大的来源）：")
                            .font(.system(size: 10.5)).themeForeground(.secondary)
                        ForEach(Self.candidateLedgers, id: \.self) { id in
                            Toggle(Catalog.brand(id).name, isOn: Binding(
                                get: { store.skipLedgersLowResource.contains(id) },
                                set: { on in
                                    var list = store.skipLedgersLowResource
                                    if on { if !list.contains(id) { list.append(id) } }
                                    else { list.removeAll { $0 == id } }
                                    store.skipLedgersLowResource = list
                                }))
                                .font(.system(size: 11.5))
                        }
                    }
                } else {
                    ProgressView().controlSize(.small)
                }
            }
            .padding(16)
        }
        .task { await store.loadStatus() }
        .themedRoot(store.theme)
    }
}