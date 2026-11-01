import SwiftUI

/// 会话活动：跨 harness 的最近会话/回合状态，5 秒轻量轮询，绝不触发全量采集。
struct ActivityView: View {
    @Environment(UsageStore.self) private var store
    @State private var filter: ActivityFeed.Filter = .all
    @State private var expanded: Set<String> = []
    @State private var renameTarget: ActivityRow?
    @State private var renameText = ""

    var body: some View {
        TimelineView(.periodic(from: .now, by: 5)) { context in
            let tracker = ActivityTracker.shared
            VStack(alignment: .leading, spacing: 10) {
                header(tracker)
                if let message = tracker.errorMessage {
                    Text("活动读取失败：\(message)（将继续重试）")
                        .font(.system(size: 10.5))
                        .foregroundStyle(.secondary)
                }
                rows(tracker, now: context.date)
            }
            .onAppear {
                tracker.panelAppeared()
                // Offline preview: expand everything so the detail layout is rendered.
                if PanelView.expandForPreview, let feed = tracker.feed {
                    expanded = Set(feed.activities.map(\.id))
                }
            }
            .onDisappear { tracker.panelDisappeared() }
            .sheet(item: $renameTarget) { row in
                ActivityRenameSheet(row: row, tracker: tracker) { renameTarget = nil }
            }
        }
    }

    // MARK: Header

    private func header(_ tracker: ActivityTracker) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                PillTabs(items: ActivityFeed.Filter.allCases, title: { $0.label },
                         selection: $filter, small: true)
                    .frame(width: 200)
                Spacer()
                if let feed = tracker.feed {
                    let running = feed.runningCount
                    Text(running > 0 ? "\(running) 个进行中" : "无进行中任务")
                        .font(.system(size: 10.5, weight: running > 0 ? .semibold : .regular))
                        .foregroundStyle(running > 0 ? AnyShapeStyle(.green) : AnyShapeStyle(.secondary))
                }
            }
            if let feed = tracker.feed {
                Text(cadenceNote(feed, tracker: tracker))
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
        }
    }

    private func cadenceNote(_ feed: ActivityFeed, tracker: ActivityTracker) -> String {
        var parts = ["窗口 \(feed.windowHours) 小时", "空闲阈值 \(feed.idleAfterMinutes) 分钟",
                     "刷新 \(Int(ActivityCadence.interval(panelVisible: tracker.panelVisible, hasRunning: feed.hasRunning))) 秒"]
        if let fetched = tracker.lastFetched {
            parts.append("更新于 " + Fmt.ago(fetched, now: Date()))
        }
        let failed = feed.sourcesMeta.values.filter { $0.status != "available" }
        if failed.count == 1, let meta = failed.first {
            parts.append(Catalog.reason(meta.reason))
        } else if failed.count > 1 {
            parts.append("\(failed.count) 个来源未接入")
        }
        return parts.joined(separator: " · ")
    }

    // MARK: Rows

    @ViewBuilder
    private func rows(_ tracker: ActivityTracker, now: Date) -> some View {
        if let feed = tracker.feed {
            let visible = ActivityFeed.sorted(feed.activities).filter { filter.matches($0) }
            if visible.isEmpty {
                Text(feed.activities.isEmpty
                     ? "最近 \(feed.windowHours) 小时没有会话活动"
                     : "当前筛选下没有会话活动")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 24)
            } else {
                VStack(spacing: 6) {
                    ForEach(visible) { row in
                        ActivityRowView(row: row, aliases: tracker.aliases, now: now,
                                        expanded: expanded.contains(row.id),
                                        onToggle: { toggle(row.id) },
                                        onRename: renameTarget(row))
                    }
                }
            }
        } else {
            Text("正在读取活动…")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.vertical, 24)
        }
    }

    private func toggle(_ id: String) {
        if expanded.contains(id) { expanded.remove(id) } else { expanded.insert(id) }
    }

    private func renameTarget(_ row: ActivityRow) -> (() -> Void)? {
        guard row.projectPath != nil else { return nil }
        return { renameTarget = row }
    }
}

// MARK: - One activity row

private struct ActivityRowView: View {
    let row: ActivityRow
    let aliases: [String: String]
    let now: Date
    let expanded: Bool
    let onToggle: () -> Void
    let onRename: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button(action: onToggle) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Circle().fill(Self.color(row.status)).frame(width: 7, height: 7)
                        Text(row.displayName(aliases: aliases))
                            .font(.system(size: 12.5, weight: .semibold))
                            .lineLimit(1)
                        if row.subagent {
                            tag("子代理", color: .secondary)
                        }
                        tag(row.granularity.label, color: .secondary)
                        Spacer()
                        if let last = row.lastEventAt {
                            Text(Fmt.ago(last, now: now))
                                .font(.system(size: 10.5))
                                .foregroundStyle(.secondary)
                        }
                        Image(systemName: expanded ? "chevron.up" : "chevron.down")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(.tertiary)
                    }
                    HStack(spacing: 6) {
                        Text(row.appLabel)
                            .font(.system(size: 10.5))
                            .foregroundStyle(.secondary)
                        if let model = row.lastModel {
                            Text(Catalog.modelLabel(model))
                                .font(.system(size: 10.5, design: .monospaced))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        Spacer()
                        if let tokens = row.tokens {
                            Text(Fmt.tokens(tokens.total))
                                .font(.system(size: 10.5, weight: .medium))
                        }
                        if let cost = row.estimatedCostUSD {
                            Text("≈¥" + Fmt.grouped(cost * Fmt.usdToCNY, fraction: 2))
                                .font(.system(size: 10.5))
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .contextMenu {
                if let onRename {
                    Button("命名项目…", action: onRename)
                }
            }

            if expanded {
                VStack(alignment: .leading, spacing: 5) {
                    detailLine(row)
                    if row.hasTurnDetail {
                        turnDetail(row)
                    }
                    Text(row.granularity.caveat)
                        .font(.system(size: 9.5))
                        .foregroundStyle(.tertiary)
                }
                .padding(.leading, 13)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 9).fill(Color.primary.opacity(0.045)))
    }

    @ViewBuilder
    private func detailLine(_ row: ActivityRow) -> some View {
        let parts = detailParts(row)
        Text(parts.joined(separator: " · "))
            .font(.system(size: 10.5))
            .foregroundStyle(.secondary)
    }

    private func detailParts(_ row: ActivityRow) -> [String] {
        var parts: [String] = []
        parts.append("状态：" + row.status.label
                     + (row.status == .running ? "" : "（\(row.statusBasis == "explicit_event" ? "明确事件" : "按最近活动")）"))
        if let start = row.startedAt {
            parts.append("持续 " + Fmt.shortCountdown(to: row.lastEventAt ?? now, now: start, past: "进行中"))
        }
        if let requests = row.requests {
            parts.append("\(requests) 次请求")
        }
        if let tokens = row.tokens {
            parts.append("输入 \(Fmt.tokens(tokens.freshInput + tokens.cacheRead + tokens.cacheWrite)) / 输出 \(Fmt.tokens(tokens.output))")
            if let hit = tokens.cacheHitRate {
                parts.append("缓存命中 " + Fmt.percent(hit * 100))
            }
        }
        if row.calls != nil {
            parts.append("调用 \(row.calls ?? 0)")
            if row.failedCalls ?? 0 > 0 { parts.append("失败 \(row.failedCalls ?? 0)") }
            if row.generatingCalls ?? 0 > 0 { parts.append("生成中 \(row.generatingCalls ?? 0)") }
        }
        if let turns = row.turns {
            parts.append("\(turns) 回合")
        }
        if let path = row.projectPath, !path.isEmpty {
            parts.append(path)
        }
        return parts
    }

    @ViewBuilder
    private func turnDetail(_ row: ActivityRow) -> some View {
        let chips = row.turnStatuses.sorted { $0.key < $1.key }
            .map { key, count in
                let label = ActivityStatus(rawValue: key)?.label ?? key
                return "\(count) 回合\(label)"
            }
        if !chips.isEmpty {
            Text("回合终态：" + chips.joined(separator: "、"))
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
        }
        ForEach(row.recentTurns) { turn in
            HStack(spacing: 6) {
                Text("回合 \(turn.turn)")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                Circle().fill(Self.color(turn.status)).frame(width: 5, height: 5)
                Text(turn.status.label)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                if let model = turn.model {
                    Text(Catalog.modelLabel(model))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
                if let steps = turn.steps {
                    Text("\(steps) 步")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                }
                Spacer()
                Text(Fmt.tokens(turn.tokens))
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
            }
        }
    }

    private func tag(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.system(size: 9.5, weight: .medium))
            .foregroundStyle(color)
            .padding(.horizontal, 5)
            .padding(.vertical, 1.5)
            .background(Capsule().fill(color.opacity(0.1)))
    }

    static func color(_ status: ActivityStatus) -> Color {
        switch status {
        case .running: return .green
        case .suspectedEnded: return .orange
        case .completed: return .teal
        case .cancelled: return .secondary
        case .failed: return .red
        case .unknown: return .gray
        }
    }
}

// MARK: - Rename sheet

private struct ActivityRenameSheet: View {
    let row: ActivityRow
    let tracker: ActivityTracker
    let dismiss: () -> Void
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("命名项目").font(.system(size: 13, weight: .semibold))
            Text(row.projectPath ?? "")
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.secondary)
                .lineLimit(2)
            TextField("项目名称", text: $text)
                .textFieldStyle(.roundedBorder)
            HStack {
                Spacer()
                Button("取消", action: dismiss).keyboardShortcut(.cancelAction)
                Button("保存") {
                    tracker.renameProject(path: row.projectPath ?? "", to: text)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 320)
        .onAppear { text = row.displayName(aliases: tracker.aliases) }
    }
}
