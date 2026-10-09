import SwiftUI

/// One entry of the menu bar ticker: icon + remaining amount + time left.
struct TickerItem: Identifiable, Equatable {
    let id: String
    let symbol: String
    let tint: Color
    let name: String
    let value: String
    let valueTint: Color
    let time: String?
    let timeSymbol: String
    let urgent: Bool
    var icon: NSImage? = nil
    /// The underlying number, for change arrows (percent, count or balance).
    var numeric: Double? = nil
    /// Change since the previous different reading.
    var delta: Double? = nil
    var deltaIsPercent = false
}

extension Snapshot {
    /// Quotas first (tightest feel of the board), then cards and balances.
    @MainActor func tickerItems(now: Date) -> [TickerItem] {
        var items: [TickerItem] = []
        for s in accountSources {
            let brand = Catalog.brand(s.id)
            let short = s.shortName
            let quotas = s.metric("quota")?.value.rows.filter { $0["remaining_percent"].double != nil } ?? []
            for (i, q) in quotas.enumerated() {
                let r = q["remaining_percent"].double ?? 0
                let reset = q["resets_at"].date
                items.append(TickerItem(
                    id: "\(s.id)-q\(i)", symbol: brand.symbol, tint: brand.tint,
                    name: quotas.count > 1 ? "\(short) \(Catalog.bucketLabel(q).replacingOccurrences(of: " ", with: ""))" : short,
                    value: Fmt.percent(r.rounded()), valueTint: healthTint(r),
                    time: reset.map { Fmt.shortCountdown(to: $0, now: now, past: "待刷新") },
                    timeSymbol: "arrow.clockwise", urgent: r < 20,
                    icon: AppLauncher.icon(for: s.baseID, in: self), numeric: r.rounded(), deltaIsPercent: true))
            }
            if let cards = s.metric("reset_cards")?.value, let count = cards["available_count"].double, count > 0 {
                let next = cards["cards"].array.compactMap { $0["expires_at"].date }.filter { $0 > now }.min()
                    ?? cards["next_known_expiry"].date
                items.append(TickerItem(
                    id: "\(s.id)-cards", symbol: "ticket.fill", tint: brand.tint, name: "\(short) 重置卡",
                    value: "\(Int(count))张", valueTint: .primary,
                    time: next.map { Fmt.shortCountdown(to: $0, now: now, past: "已到期") },
                    timeSymbol: "hourglass", urgent: next.map { $0.timeIntervalSince(now) < 3 * 86400 } ?? false,
                    numeric: count))
            }
            if quotas.isEmpty {
                for (i, c) in (s.metric("credits")?.value.rows ?? []).enumerated() {
                    guard let amount = c["balance"].double ?? c["remaining"].double ?? c["amount"].double ?? c["total"].double else { continue }
                    let unit = c["unit"].string
                    let value = unit == "CNY" || unit == "USD" ? Fmt.amount(amount, unit: unit) : Fmt.compact(amount)
                    var time: String?
                    var symbol = "arrow.triangle.2.circlepath"
                    var urgent = false
                    if let day = Fmt.parseDay(s.metric("credit_refresh_time")?.value["date"].string) {
                        time = Fmt.shortDayCountdown(day, now: now)
                    } else if let exp = c["buckets"].array.filter({ ($0["balance"].double ?? 0) > 0 })
                                .compactMap({ $0["expires_at"].date }).filter({ $0 > now }).min() {
                        time = Fmt.shortCountdown(to: exp, now: now, past: "已失效")
                        symbol = "hourglass"
                        urgent = exp.timeIntervalSince(now) < 3 * 86400
                    }
                    items.append(TickerItem(
                        id: "\(s.id)-c\(i)", symbol: brand.symbol, tint: brand.tint, name: short,
                        value: value, valueTint: .primary, time: time, timeSymbol: symbol, urgent: urgent,
                        icon: AppLauncher.icon(for: s.baseID, in: self), numeric: amount))
                }
            }
        }
        return items
    }
}

struct TickerCell: View {
    let item: TickerItem
    var body: some View {
        HStack(spacing: 4) {
            if let icon = item.icon {
                Image(nsImage: icon).resizable().interpolation(.high).frame(width: 15, height: 15)
            } else {
                Image(systemName: item.symbol)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(item.tint)
            }
            Text(item.name)
                .font(.system(size: 11.5, weight: .medium))
            Text(item.value)
                .font(.system(size: 12, weight: .bold, design: .rounded))
                .foregroundStyle(item.valueTint)
            if let d = item.delta, d != 0 {
                // Green ▲ = more left (reset, top-up); red ▼ = consumed.
                Text((d > 0 ? "▲" : "▼") + (item.deltaIsPercent ? Fmt.trim(abs(d)) : Fmt.compact(abs(d))))
                    .font(.system(size: 9.5, weight: .heavy, design: .rounded))
                    .foregroundStyle(d > 0 ? Color(red: 0.2, green: 0.85, blue: 0.5) : Color(red: 1, green: 0.32, blue: 0.36))
            }
            if let time = item.time {
                HStack(spacing: 1.5) {
                    Image(systemName: item.timeSymbol).font(.system(size: 8, weight: .bold))
                    Text(time).font(.system(size: 11))
                }
                .foregroundStyle(item.urgent ? Color.orange : Color.secondary)
            }
        }
        .monospacedDigit()
        .lineLimit(1)
        .fixedSize()
    }
}

/// One item at a time, rolling up every few seconds like a quote board.
struct FlipTicker: View {
    let items: [TickerItem]
    let width: CGFloat
    var interval: Double = 3.5

    var body: some View {
        TimelineView(.periodic(from: .now, by: interval)) { ctx in
            let index = items.isEmpty ? 0 : Int(ctx.date.timeIntervalSinceReferenceDate / interval) % items.count
            ZStack(alignment: .leading) {
                if !items.isEmpty {
                    TickerCell(item: items[index])
                        .id(index)
                        .transition(.asymmetric(insertion: .move(edge: .bottom).combined(with: .opacity),
                                                removal: .move(edge: .top).combined(with: .opacity)))
                }
            }
            .frame(width: width, height: 22, alignment: .leading)
            .animation(.easeInOut(duration: 0.4), value: index)
        }
        .clipped()
    }
}

/// Content of the status item button.
struct StatusLabel: View {
    let store: UsageStore
    let onWidth: (CGFloat) -> Void

    var body: some View {
        content
            .padding(.horizontal, 6)
            .frame(height: 22)
            .fixedSize()
            .background(GeometryReader { g in
                Color.clear
                    .onAppear { onWidth(g.size.width) }
                    .onChange(of: g.size.width) { _, w in onWidth(w) }
            })
    }

    @ViewBuilder private var content: some View {
        let items = store.tickerItems()
        switch store.menuBarMode {
        case .ticker where !items.isEmpty:
            // Drawn by the Core Animation marquee in StatusBarController.
            Color.clear.frame(width: 1)
        case .flip where !items.isEmpty:
            FlipTicker(items: items, width: store.tickerWidth.points)
        default:
            HStack(spacing: 3) {
                Image(systemName: store.menuBarSymbol).font(.system(size: 13, weight: .medium))
                if let text = store.menuBarText {
                    Text(text).font(.system(size: 12, weight: .medium)).monospacedDigit()
                }
            }
        }
    }
}
