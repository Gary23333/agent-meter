import SwiftUI

/// 进程 tab: what the agent harnesses on this Mac have started, and nothing else.
struct ProcessesView: View {
    let snapshot: Snapshot
    let now: Date
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme

    private var tracker: ProcessTracker { .shared }

    var body: some View {
        let feed = tracker.feed
        VStack(alignment: .leading, spacing: 10) {
            hero(feed)
            if let feed {
                if !feed.isAvailable {
                    unavailable(feed)
                } else if feed.groups.isEmpty {
                    emptyCard
                } else {
                    ForEach(feed.groups) { GroupCard(group: $0, snapshot: snapshot) }
                }
            } else {
                Card {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("正在读取 harness 的进程…").font(theme.font(12)).themeForeground(.secondary)
                    }
                }
            }
            footnote
        }
        .onAppear { tracker.panelAppeared() }
        .onDisappear { tracker.panelDisappeared() }
    }

    // MARK: Hero

    private func hero(_ feed: ProcessFeed?) -> some View {
        Card {
            SectionTitle(text: "进程星图", trailing: "大小 = 内存 · 亮度 = CPU · 可拖动")
            ProcessConstellation(groups: groupsForScene(feed), height: 190)
            HStack(spacing: 0) {
                stat("Harness", feed.map { "\($0.harnessCount)" } ?? "—")
                stat("进程", feed.map { "\($0.processCount)" } ?? "—")
                stat("CPU", feed.map { ProcessFormat.cpu($0.cpu) } ?? "—")
                stat("内存", feed.map { ProcessFormat.memory($0.rss) } ?? "—")
            }
            legend
        }
    }

    /// The scene gets the real parent links (a process hangs below its parent, not always the core).
    private func groupsForScene(_ feed: ProcessFeed?) -> [ConstellationGroup] {
        guard let feed, feed.isAvailable, !feed.groups.isEmpty else {
            return [ConstellationGroup(id: "idle", tint: NSColor(white: 0.6, alpha: 1), alive: false, nodes: [])]
        }
        return feed.groups.map { g in
            let known = Set(g.rows.map(\.pid))
            return ConstellationGroup(
                id: g.id, tint: NSColor(Catalog.brand(g.app).tint), alive: g.alive,
                nodes: g.rows.map { p in
                    ConstellationNode(pid: p.pid, parent: known.contains(p.parent) ? p.parent : nil, kind: p.kind, cpu: p.cpu, rss: p.rss)
                })
        }
    }

    private func stat(_ title: String, _ value: String) -> some View {
        VStack(spacing: 2) {
            Text(value).font(theme.number(15)).monospacedDigit().themeForeground().lineLimit(1).minimumScaleFactor(0.7)
            Text(title).font(theme.font(10, weight: .medium)).themeForeground(.tertiary)
        }
        .frame(maxWidth: .infinity)
    }

    private var legend: some View {
        let kinds: [ProcessKind] = [.shell, .server, .mcp, .build, .test, .runtime]
        return HStack(spacing: 10) {
            ForEach(kinds, id: \.rawValue) { k in
                HStack(spacing: 4) {
                    Circle().fill(k.color).frame(width: 6, height: 6)
                    Text(k.label).font(theme.font(10)).themeForeground(.tertiary)
                }
            }
            Spacer(minLength: 0)
        }
    }

    // MARK: States

    private var emptyCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 6) {
                Label("没有 harness 在运行", systemImage: "moon.zzz").font(theme.font(13, weight: .semibold)).themeForeground()
                Text("启动 Claude Code、Codex、Kimi Code 等之后，它们启动的 shell、构建、开发服务器和 MCP 服务会出现在这里。")
                    .font(theme.font(11)).themeForeground(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func unavailable(_ feed: ProcessFeed) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 6) {
                Label(feed.status == "unsupported_platform" ? "此系统暂不支持进程监控" : "无法读取进程表", systemImage: "exclamationmark.triangle")
                    .font(theme.font(13, weight: .semibold)).themeForeground()
                Text(feed.status == "unsupported_platform" ? "进程监控目前支持 macOS 与 Linux。" : "原因：\(feed.reason ?? "未知")。")
                    .font(theme.font(11)).themeForeground(.secondary)
            }
        }
    }

    private var footnote: some View {
        Text("只读：只显示 harness 进程树里的进程，不读取环境变量、输出或文件，命令行已脱敏；这里不提供结束进程。后台遗留的进程只有在它还挂在 harness 下时被看到过，才会被认领。")
            .font(theme.font(10)).themeForeground(.tertiary)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 2)
    }
}

/// One harness (or the leftovers of one that has exited) with its process tree.
private struct GroupCard: View {
    let group: HarnessGroup
    let snapshot: Snapshot
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme
    @State private var open = true

    private var brand: Catalog.Brand { Catalog.brand(group.app) }

    var body: some View {
        Card(tint: brand.tint) {
            Button { withAnimation(.easeInOut(duration: 0.2)) { open.toggle() } } label: { header }
                .buttonStyle(.plain)
            metrics
            if open {
                if group.rows.isEmpty {
                    Text(group.alive ? "它现在没有启动任何进程" : "没有遗留进程").font(theme.font(11)).themeForeground(.tertiary)
                } else {
                    VStack(spacing: 7) {
                        ForEach(group.rows) { ProcessRow(process: $0) }
                    }
                    if group.truncated {
                        Text("进程太多，只显示前 \(group.rows.count) 个").font(theme.font(10)).themeForeground(.tertiary)
                    }
                }
            }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            BrandBadge(brand: brand, size: 28, icon: AppLauncher.icon(for: group.app, in: snapshot))
                .opacity(group.alive ? 1 : 0.55)
            VStack(alignment: .leading, spacing: 1) {
                Text(group.alive ? group.label : group.label + " · 遗留进程")
                    .font(.system(size: 14, weight: .bold))
                Text(subtitle).font(.system(size: 11)).themeForeground(.secondary).lineLimit(1)
            }
            Spacer(minLength: 6)
            if group.alive {
                StatusPill(status: "available", text: "运行中")
            } else {
                StatusPill(status: "stale", text: "harness 已退出")
            }
            Image(systemName: "chevron.right").font(.system(size: 9, weight: .bold)).themeForeground(.tertiary)
                .rotationEffect(.degrees(open ? 90 : 0))
        }
        .contentShape(Rectangle())
    }

    private var subtitle: String {
        var parts: [String] = []
        if let alias = group.projectAlias { parts.append(alias) }
        if let up = group.uptime { parts.append((group.alive ? "已运行 " : "最久 ") + ProcessFormat.uptime(up)) }
        if let pid = group.pid { parts.append("PID \(pid)") }
        return parts.isEmpty ? "—" : parts.joined(separator: " · ")
    }

    private var metrics: some View {
        HStack(spacing: 0) {
            metric("进程", "\(group.count)")
            metric("CPU", ProcessFormat.cpu(group.cpu), hot: group.cpu >= 80)
            metric("内存", ProcessFormat.memory(group.rss))
        }
        .padding(.vertical, 2)
    }

    private func metric(_ title: String, _ value: String, hot: Bool = false) -> some View {
        HStack(spacing: 5) {
            Text(title).font(theme.font(11, weight: .medium)).themeForeground(.tertiary)
            Text(value).font(.system(size: 12, weight: .semibold, design: theme.numberDesign)).monospacedDigit()
                .foregroundStyle(hot ? AnyShapeStyle(Color.orange) : AnyShapeStyle(theme.textColor(.primary, scheme: scheme)))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ProcessRow: View {
    let process: HarnessProcess
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(alignment: .top, spacing: 7) {
            Color.clear.frame(width: CGFloat(min(process.depth - 1, 5)) * 11, height: 1)
            Image(systemName: process.kind.symbol)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(process.kind.color)
                .frame(width: 20, height: 20)
                .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(process.kind.color.opacity(0.14)))
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 5) {
                    Text(process.name).font(theme.font(12, weight: .semibold)).themeForeground().lineLimit(1)
                    ForEach(process.ports.prefix(3), id: \.self) { port in
                        Text(":" + String(port))
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(ProcessKind.server.color)
                            .padding(.horizontal, 5).padding(.vertical, 1.5)
                            .background(Capsule().fill(ProcessKind.server.color.opacity(0.14)))
                    }
                    if process.orphaned {
                        Text("遗留").font(.system(size: 9, weight: .semibold)).foregroundStyle(.orange)
                            .padding(.horizontal, 5).padding(.vertical, 1.5)
                            .background(Capsule().fill(Color.orange.opacity(0.14)))
                    }
                }
                Text(process.command).font(.system(size: 10, design: .monospaced)).themeForeground(.tertiary)
                    .lineLimit(1).truncationMode(.middle)
            }
            Spacer(minLength: 6)
            VStack(alignment: .trailing, spacing: 2) {
                Text(ProcessFormat.cpu(process.cpu))
                    .font(.system(size: 12, weight: .semibold, design: theme.numberDesign)).monospacedDigit()
                    .foregroundStyle(heat)
                Text(ProcessFormat.memory(process.rss)).font(.system(size: 11, design: theme.numberDesign)).monospacedDigit()
                    .themeForeground(.secondary)
            }
            .lineLimit(1).minimumScaleFactor(0.75).frame(width: 62, alignment: .trailing)
            Text(ProcessFormat.uptime(process.uptime)).font(theme.font(10)).monospacedDigit().themeForeground(.tertiary)
                .lineLimit(1).minimumScaleFactor(0.75).frame(width: 54, alignment: .trailing)
        }
        .help("\(process.kind.label) · \(ProcessFormat.state(process.state)) · PID \(process.pid)")
    }

    private var heat: AnyShapeStyle {
        if process.cpu >= 80 { return AnyShapeStyle(Color.red) }
        if process.cpu >= 30 { return AnyShapeStyle(Color.orange) }
        return AnyShapeStyle(theme.textColor(.primary, scheme: scheme))
    }
}
