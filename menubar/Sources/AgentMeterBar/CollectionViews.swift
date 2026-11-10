import SwiftUI

// MARK: - Model

/// The backend's card binder and medals (agent_meter/collection.py).
struct CollectionData {
    struct CardDef: Identifiable {
        let id: String
        let name: String
        let series: String
        let seriesName: String
        let rarity: Rarity
        let symbol: String
        let description: String
    }

    struct Owned {
        let count: Int
        let firstAt: Date?
        let lastAt: Date?
        let sources: [String]
    }

    struct Drop: Identifiable {
        let id: Int
        let card: String
        let at: Date?
        let source: String?
        let detail: String?
    }

    struct OpenWindow: Identifiable {
        let id: Int
        let source: String
        let kind: String
        let peak: Double
        let resetsAt: Date?
        let currentCard: String?
        let nextCard: String?
        let nextThreshold: Double?
        /// Cards this window has already dropped (one per tier it crossed).
        let granted: [String]
    }

    struct Medal: Identifiable {
        let id: String
        let name: String
        let category: String
        let categoryName: String
        let target: Double
        let unit: String
        let symbol: String
        let tier: MedalTier
        let value: Double
        let progress: Double
        let earned: Bool
        let earnedOn: String?
        let count: Int
    }

    let catalog: [CardDef]
    let owned: [String: Owned]
    let recent: [Drop]
    let openWindows: [OpenWindow]
    let medals: [Medal]
    let stats: JSON

    init?(_ json: JSON) {
        guard !json["catalog"].array.isEmpty else { return nil }
        catalog = json["catalog"].array.map {
            CardDef(id: $0["id"].string ?? "", name: $0["name"].string ?? "", series: $0["series"].string ?? "",
                    seriesName: $0["series_name"].string ?? "", rarity: Rarity(rawValue: $0["rarity"].string ?? "") ?? .common,
                    symbol: $0["symbol"].string ?? "questionmark", description: $0["description"].string ?? "")
        }
        owned = json["cards"].object.mapValues {
            Owned(count: Int($0["count"].double ?? 0), firstAt: $0["first_at"].date, lastAt: $0["last_at"].date,
                  sources: $0["sources"].array.compactMap(\.string))
        }
        recent = json["recent"].array.enumerated().map {
            Drop(id: $0, card: $1["card"].string ?? "", at: $1["at"].date, source: $1["source"].string, detail: $1["detail"].string)
        }
        openWindows = json["open_windows"].array.enumerated().map {
            OpenWindow(id: $0, source: $1["source"].string ?? "", kind: $1["kind"].string ?? "", peak: $1["peak"].double ?? 0,
                       resetsAt: $1["resets_at"].date, currentCard: $1["current_card"].string,
                       nextCard: $1["next_card"].string, nextThreshold: $1["next_threshold"].double,
                       granted: $1["granted"].array.compactMap(\.string))
        }
        medals = json["medals"].array.map {
            Medal(id: $0["id"].string ?? "", name: $0["name"].string ?? "", category: $0["category"].string ?? "",
                  categoryName: $0["category_name"].string ?? "", target: $0["target"].double ?? 1, unit: $0["unit"].string ?? "",
                  symbol: $0["symbol"].string ?? "medal", tier: MedalTier(rawValue: $0["tier"].string ?? "") ?? .bronze,
                  value: $0["value"].double ?? 0, progress: $0["progress"].double ?? 0, earned: $0["earned"].bool ?? false,
                  earnedOn: $0["earned_on"].string, count: Int($0["count"].double ?? 0))
        }
        stats = json["stats"]
    }

    func def(_ id: String) -> CardDef? { catalog.first { $0.id == id } }
    /// "No.07/17" style position in the catalog.
    func serial(_ id: String) -> String {
        let index = (catalog.firstIndex { $0.id == id } ?? 0) + 1
        return String(format: "No.%02d/%02d", index, catalog.count)
    }
    var series: [(id: String, name: String, cards: [CardDef])] {
        var order: [String] = []
        for c in catalog where !order.contains(c.series) { order.append(c.series) }
        return order.map { s in (s, catalog.first { $0.series == s }?.seriesName ?? s, catalog.filter { $0.series == s }) }
    }
    var collectible: [CardDef] { catalog.filter { $0.rarity != .faded } }
    var distinct: Int { collectible.filter { owned[$0.id] != nil }.count }
    var earnedMedals: Int { medals.filter(\.earned).count }
}

extension Snapshot {
    var collection: CollectionData? { CollectionData(raw["collection"]) }
}

enum Rarity: String {
    case common, rare, epic, legendary, faded

    var label: String {
        switch self {
        case .common: return "普通"
        case .rare: return "稀有"
        case .epic: return "史诗"
        case .legendary: return "传说"
        case .faded: return "遗憾"
        }
    }
    var stars: Int { [.common: 1, .rare: 2, .epic: 3, .legendary: 4, .faded: 0][self] ?? 0 }
    /// Card face, deep to light.
    var colors: [Color] {
        switch self {
        case .common: return [Color(red: 0.16, green: 0.42, blue: 0.45), Color(red: 0.36, green: 0.72, blue: 0.70)]
        case .rare: return [Color(red: 0.10, green: 0.26, blue: 0.62), Color(red: 0.30, green: 0.58, blue: 0.98)]
        case .epic: return [Color(red: 0.32, green: 0.12, blue: 0.58), Color(red: 0.78, green: 0.36, blue: 0.96)]
        case .legendary: return [Color(red: 0.62, green: 0.28, blue: 0.04), Color(red: 1.00, green: 0.78, blue: 0.30)]
        case .faded: return [Color(white: 0.30), Color(white: 0.55)]
        }
    }
    var glow: Color { colors[1] }
    var holo: Bool { self == .epic || self == .legendary }
}

enum MedalTier: String {
    case bronze, silver, gold, platinum

    var colors: [Color] {
        switch self {
        case .bronze: return [Color(red: 0.55, green: 0.30, blue: 0.14), Color(red: 0.93, green: 0.62, blue: 0.38), Color(red: 0.62, green: 0.35, blue: 0.18)]
        case .silver: return [Color(red: 0.50, green: 0.55, blue: 0.62), Color(red: 0.95, green: 0.97, blue: 1.00), Color(red: 0.58, green: 0.63, blue: 0.70)]
        case .gold: return [Color(red: 0.70, green: 0.45, blue: 0.05), Color(red: 1.00, green: 0.88, blue: 0.42), Color(red: 0.80, green: 0.55, blue: 0.10)]
        case .platinum: return [Color(red: 0.36, green: 0.40, blue: 0.62), Color(red: 0.86, green: 0.95, blue: 1.00), Color(red: 0.62, green: 0.48, blue: 0.92)]
        }
    }
    var label: String { ["bronze": "铜", "silver": "银", "gold": "金", "platinum": "铂金"][rawValue] ?? "" }
}

// MARK: - Tab

struct CollectionView: View {
    let snapshot: Snapshot
    let now: Date
    @Environment(\.panelTheme) private var theme
    @State private var toast: String?
    @State private var heroPointer: CGPoint = .zero

    var body: some View {
        if let data = snapshot.collection {
            VStack(alignment: .leading, spacing: 14) {
                CollectionHero(data: data)
                    .background {
                        FloatingDust(color: theme.isLuminous || theme.forcedScheme == .dark ? .white : Rarity.legendary.glow,
                                     shift: heroPointer)
                            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    .modifier(PointerTracker(pointer: $heroPointer))
                    .overlay(alignment: .topTrailing) { shareMenu(data).padding(10) }
                if let toast {
                    Label(toast, systemImage: "checkmark.circle.fill")
                        .font(theme.font(11, weight: .semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                        .background(Capsule().fill(Color.green.opacity(0.15)))
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                NextGoals(data: data)
                if !data.recent.isEmpty { RecentDrops(data: data, now: now) }
                if !data.openWindows.isEmpty { OpenWindowsSection(data: data, now: now) }
                MedalWall(data: data)
                ForEach(data.series, id: \.id) { s in
                    BinderSection(data: data, title: s.name, cards: s.cards)
                }
                Text("额度用量每越过一档即掉落卡片，重置卡用掉或过期、签到与任务领取时也会掉落；奖章按本机全部历史重算。数据只在本机。")
                    .font(theme.font(10)).themeForeground(.tertiary)
                    .padding(.horizontal, 2)
            }
        } else {
            Card {
                Text("收集册还没准备好：后端版本较旧，或本次采集未生成收集数据。")
                    .font(theme.font(12)).themeForeground(.secondary)
            }
        }
    }
}

extension CollectionView {
    fileprivate func shareMenu(_ data: CollectionData) -> some View {
        Menu {
            Button("复制收集册分享图") { share(.copy, data) }
            Button("保存收集册为 PNG…") { share(.save, data) }
            Divider()
            Toggle("分享图附带项目二维码", isOn: Binding(get: { TrophyShare.showsQR },
                                                 set: { UserDefaults.standard.set($0, forKey: TrophyShare.qrKey) }))
        } label: {
            Image(systemName: "square.and.arrow.up")
                .font(.system(size: 11.5, weight: .semibold))
                .frame(width: 24, height: 24)
                .background(Circle().fill(Color.primary.opacity(0.07)))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("导出收集册分享图")
    }

    fileprivate func share(_ action: TrophyShare.Action, _ data: CollectionData) {
        let message = TrophyShare.perform(action, png: TrophyShare.png(CollectionShareCard(data: data)),
                                          name: "AgentMeter-收集册-" + Fmt.day(Date()))
        withAnimation(.spring(response: 0.35)) { toast = message }
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(2.5))
            withAnimation { if toast == message { toast = nil } }
        }
    }
}

// MARK: Hero

private struct CollectionHero: View {
    let data: CollectionData
    @Environment(\.panelTheme) private var theme

    private var streak: Double { data.stats["current_streak"].double ?? 0 }
    private var nextStreak: Double { [7.0, 30, 100, 365].first { $0 > streak } ?? 365 }

    var body: some View {
        Card(tint: Rarity.legendary.glow) {
            HStack(alignment: .center, spacing: 16) {
                ZStack {
                    ActivityRing(progress: Double(data.distinct) / Double(max(1, data.collectible.count)),
                                 colors: [Color(red: 1, green: 0.25, blue: 0.45), Color(red: 1, green: 0.55, blue: 0.75)], width: 11)
                        .frame(width: 104, height: 104)
                    ActivityRing(progress: Double(data.earnedMedals) / Double(max(1, data.medals.count)),
                                 colors: [Color(red: 0.55, green: 0.95, blue: 0.2), Color(red: 0.8, green: 1, blue: 0.4)], width: 11)
                        .frame(width: 78, height: 78)
                    ActivityRing(progress: min(1, streak / nextStreak),
                                 colors: [Color(red: 0.1, green: 0.85, blue: 0.95), Color(red: 0.45, green: 0.75, blue: 1)], width: 11)
                        .frame(width: 52, height: 52)
                    Image(systemName: "sparkles").font(.system(size: 13, weight: .bold))
                        .foregroundStyle(LinearGradient(colors: Rarity.legendary.colors.reversed(), startPoint: .top, endPoint: .bottom))
                }
                VStack(alignment: .leading, spacing: 7) {
                    HStack(spacing: 6) {
                        Text("收集册").font(theme.font(16, weight: .bold))
                        Text("Lv.\(level)").font(.system(size: 10, weight: .heavy, design: .rounded))
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(Capsule().fill(LinearGradient(colors: Rarity.legendary.colors, startPoint: .leading, endPoint: .trailing)))
                            .foregroundStyle(.white)
                    }
                    ringLegend(color: Color(red: 1, green: 0.3, blue: 0.5), title: "卡片", value: "\(data.distinct)/\(data.collectible.count)",
                               detail: "共 \(Int(data.stats["total_cards"].double ?? 0)) 张")
                    ringLegend(color: Color(red: 0.6, green: 0.95, blue: 0.25), title: "奖章", value: "\(data.earnedMedals)/\(data.medals.count)", detail: nil)
                    ringLegend(color: Color(red: 0.2, green: 0.85, blue: 0.95), title: "连续", value: "\(Int(streak)) 天",
                               detail: "下一档 \(Int(nextStreak)) 天")
                }
                Spacer(minLength: 0)
            }
            HStack(spacing: 6) {
                ForEach([Rarity.common, .rare, .epic, .legendary], id: \.self) { r in
                    RarityChip(rarity: r, count: Int(data.stats["by_rarity"][r.rawValue].double ?? 0))
                }
            }
            HStack(spacing: 6) {
                HeroStat(symbol: "yensign.circle.fill", tint: MedalTier.gold.colors[1], title: "累计估算",
                         value: "¥" + Fmt.grouped(data.stats["lifetime_cost_cny"].double ?? 0))
                HeroStat(symbol: "photo.on.rectangle.angled", tint: Rarity.epic.glow, title: "累计出图",
                         value: Fmt.grouped(data.stats["lifetime_images"].double ?? 0) + " 张")
                HeroStat(symbol: "sum", tint: Rarity.rare.glow, title: "累计 Token",
                         value: Fmt.tokens(data.stats["lifetime_tokens"].double ?? 0))
            }
            if let best = data.stats["best_day"]["tokens"].double, let date = data.stats["best_day"]["date"].string {
                HStack(spacing: 6) {
                    Image(systemName: "trophy.fill").foregroundStyle(MedalTier.gold.colors[1])
                    Text("个人最佳单日").font(theme.font(11)).themeForeground(.secondary)
                    Spacer()
                    Text(Fmt.tokens(best)).font(.system(size: 13, weight: .bold, design: .rounded)).monospacedDigit()
                    Text(date).font(theme.font(10)).themeForeground(.tertiary)
                }
            }
        }
    }

    /// One level per 3 cards and 2 medals, so both halves move the badge.
    private var level: Int {
        1 + Int(data.stats["total_cards"].double ?? 0) / 3 + data.earnedMedals / 2
    }

    private func ringLegend(color: Color, title: String, value: String, detail: String?) -> some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(title).font(theme.font(11)).themeForeground(.secondary)
            Text(value).font(.system(size: 13, weight: .bold, design: .rounded)).monospacedDigit()
            if let detail { Text(detail).font(theme.font(10)).themeForeground(.tertiary) }
        }
    }
}

private struct HeroStat: View {
    let symbol: String
    let tint: Color
    let title: String
    let value: String
    @Environment(\.panelTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 4) {
                Image(systemName: symbol).font(.system(size: 10, weight: .bold)).foregroundStyle(tint)
                Text(title).font(theme.font(9.5)).themeForeground(.secondary)
            }
            Text(value).font(.system(size: 13, weight: .bold, design: .rounded)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.7)
        }
        .padding(.horizontal, 9).padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(tint.opacity(0.10)))
        .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(tint.opacity(0.25), lineWidth: 0.6))
    }
}

struct ActivityRing: View {
    let progress: Double
    let colors: [Color]
    let width: CGFloat
    /// Rings sweep in from zero when they appear, like Activity rings.
    @State private var shown: Double = Motion.isStatic ? 1 : 0

    var body: some View {
        ZStack {
            Circle().stroke(colors[0].opacity(0.16), lineWidth: width)
            Circle()
                .trim(from: 0, to: max(0.001, min(1, progress) * shown))
                .stroke(AngularGradient(colors: colors + [colors[0]], center: .center),
                        style: StrokeStyle(lineWidth: width, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .shadow(color: colors[0].opacity(0.45), radius: 3)
            // Bright cap on the leading end of the arc.
            Circle()
                .fill(colors.last ?? colors[0])
                .frame(width: width, height: width)
                .shadow(color: .black.opacity(0.35), radius: 1.5)
                .offset(y: -width / 2)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .rotationEffect(.degrees(360 * min(1, progress) * shown))
                .opacity(progress > 0.02 ? 1 : 0)
        }
        .onAppear {
            guard !Motion.isStatic else { return }
            withAnimation(.spring(response: 1.1, dampingFraction: 0.82).delay(0.08)) { shown = 1 }
        }
    }
}


private struct RarityChip: View {
    let rarity: Rarity
    let count: Int

    var body: some View {
        HStack(spacing: 4) {
            Text(String(repeating: "★", count: rarity.stars)).font(.system(size: 7.5, weight: .black))
            Text(rarity.label).font(.system(size: 10, weight: .semibold))
            Text("\(count)").font(.system(size: 10.5, weight: .heavy, design: .rounded)).monospacedDigit()
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 7).padding(.vertical, 4)
        .frame(maxWidth: .infinity)
        .background(Capsule().fill(LinearGradient(colors: rarity.colors, startPoint: .leading, endPoint: .trailing)))
        .opacity(count > 0 ? 1 : 0.45)
    }
}

// MARK: Next goals

/// The three unearned medals closest to done, with what is left.
private struct NextGoals: View {
    let data: CollectionData
    @Environment(\.panelTheme) private var theme

    private var goals: [CollectionData.Medal] {
        Array(data.medals.filter { !$0.earned && $0.progress > 0.02 }.sorted { $0.progress > $1.progress }.prefix(3))
    }

    var body: some View {
        if !goals.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                SectionTitle(text: "下一个目标", trailing: "最接近达成")
                Card {
                    VStack(spacing: 10) {
                        ForEach(goals) { m in
                            Button { UsageStore.shared.openTrophy(Unlock(kind: .medal, id: m.id)) } label: { row(m) }
                                .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    private func row(_ m: CollectionData.Medal) -> some View {
        HStack(spacing: 10) {
            MedalView(medal: m, showsCaption: false).scaleEffect(0.62).frame(width: 34, height: 34)
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(m.name).font(theme.font(12, weight: .semibold))
                    Text(m.categoryName).font(theme.font(9.5)).themeForeground(.tertiary)
                    Spacer()
                    Text("\(Int(m.progress * 100))%").font(.system(size: 11, weight: .bold, design: .rounded)).monospacedDigit()
                        .foregroundStyle(m.tier.colors[1])
                }
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Color.primary.opacity(0.08))
                        Capsule().fill(LinearGradient(colors: [m.tier.colors[0], m.tier.colors[1]], startPoint: .leading, endPoint: .trailing))
                            .frame(width: max(5, geo.size.width * m.progress))
                            .shadow(color: m.tier.colors[1].opacity(0.5), radius: 2)
                    }
                }
                .frame(height: 5)
                Text("还差 " + TrophyShare.valueText(m, max(0, m.target - m.value)) + " · 目标 " + TrophyShare.medalGoal(m))
                    .font(theme.font(9.5)).themeForeground(.tertiary).lineLimit(1)
            }
        }
        .contentShape(Rectangle())
    }
}

// MARK: Recent drops

private struct RecentDrops: View {
    let data: CollectionData
    let now: Date
    @Environment(\.panelTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "最新掉落", trailing: "最近 \(data.recent.count) 次")
            Card {
                HStack(alignment: .top, spacing: 12) {
                    if let def = featured {
                        TradingCard(def: def, owned: data.owned[def.id], large: true, serial: data.serial(def.id))
                            .holoTilt(RoundedRectangle(cornerRadius: 12, style: .continuous), maxAngle: 12, glare: 0.38)
                            .frame(width: 118)
                            .contentShape(Rectangle())
                            .onTapGesture { UsageStore.shared.openTrophy(Unlock(kind: .card, id: def.id)) }
                    }
                    VStack(alignment: .leading, spacing: 7) {
                        ForEach(data.recent.prefix(6)) { drop in
                            if let def = data.def(drop.card) { dropRow(drop, def) }
                        }
                    }
                }
            }
        }
    }

    /// The rarest of the latest drops gets the big card.
    private var featured: CollectionData.CardDef? {
        let defs = data.recent.prefix(6).compactMap { data.def($0.card) }
        return defs.max { $0.rarity.stars < $1.rarity.stars } ?? defs.first
    }

    private func dropRow(_ drop: CollectionData.Drop, _ def: CollectionData.CardDef) -> some View {
        Button { UsageStore.shared.openTrophy(Unlock(kind: .card, id: def.id)) } label: { dropLabel(drop, def) }
            .buttonStyle(.plain)
    }

    private func dropLabel(_ drop: CollectionData.Drop, _ def: CollectionData.CardDef) -> some View {
        HStack(spacing: 7) {
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(LinearGradient(colors: def.rarity.colors, startPoint: .topLeading, endPoint: .bottomTrailing))
                .frame(width: 14, height: 19)
                .overlay(Image(systemName: def.symbol).font(.system(size: 7, weight: .bold)).foregroundStyle(.white))
            VStack(alignment: .leading, spacing: 1) {
                Text(def.name).font(theme.font(11.5, weight: .semibold)).lineLimit(1)
                Text([drop.source.map { Catalog.brand($0).name }, drop.detail].compactMap { $0 }.joined(separator: " · "))
                    .font(theme.font(9.5)).themeForeground(.tertiary).lineLimit(1)
            }
            Spacer(minLength: 4)
            if let at = drop.at {
                Text(Fmt.ago(at, now: now)).font(theme.font(9.5)).themeForeground(.tertiary).lineLimit(1)
            }
        }
    }
}

// MARK: Windows in progress

private struct OpenWindowsSection: View {
    let data: CollectionData
    let now: Date
    @Environment(\.panelTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "冲刺中", trailing: "越档即掉落")
            Card {
                VStack(spacing: 10) {
                    ForEach(windows) { w in row(w) }
                }
            }
        }
    }

    /// Windows with some use, most advanced first; untouched ones only fill gaps.
    private var windows: [CollectionData.OpenWindow] {
        let used = data.openWindows.filter { $0.peak > 0 }.sorted { $0.peak > $1.peak }
        return Array((used.isEmpty ? data.openWindows : used).prefix(5))
    }

    private func row(_ w: CollectionData.OpenWindow) -> some View {
        let current = w.currentCard.flatMap(data.def)
        let next = w.nextCard.flatMap(data.def)
        let tint = (current ?? next)?.rarity.glow ?? .gray
        return VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Text(Catalog.brand(w.source).name).font(theme.font(11.5, weight: .semibold))
                Text(w.kind == "five_hour" ? "5 小时" : "7 天").font(theme.font(10)).themeForeground(.tertiary)
                Spacer()
                if let at = w.resetsAt { Text(Fmt.countdown(to: at, now: now) + "重置").font(theme.font(10)).themeForeground(.tertiary) }
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.08))
                    Capsule()
                        .fill(LinearGradient(colors: [tint.opacity(0.7), tint], startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(4, geo.size.width * min(1, w.peak / 100)))
                        .shadow(color: tint.opacity(0.5), radius: 3)
                    ForEach([50.0, 80, 90], id: \.self) { mark in
                        Rectangle().fill(Color.primary.opacity(0.25)).frame(width: 1, height: 9)
                            .offset(x: geo.size.width * mark / 100)
                    }
                }
            }
            .frame(height: 7)
            HStack(spacing: 4) {
                Text("峰值 \(Int(w.peak.rounded()))%").font(.system(size: 10, weight: .semibold, design: .rounded)).monospacedDigit()
                if let current { Text("· 已获得「\(current.name)」").font(theme.font(10)).foregroundStyle(current.rarity.glow) }
                if !w.granted.isEmpty { Text("· 本窗 \(w.granted.count) 张").font(theme.font(10)).themeForeground(.tertiary) }
                Spacer()
                if let next, let t = w.nextThreshold {
                    Text("再用 \(max(1, Int((t - w.peak).rounded(.up))))% 解锁「\(next.name)」")
                        .font(theme.font(10)).themeForeground(.secondary)
                }
            }
        }
    }
}

// MARK: Medals

private struct MedalWall: View {
    let data: CollectionData

    private var groups: [(name: String, medals: [CollectionData.Medal])] {
        var order: [String] = []
        for m in data.medals where !order.contains(m.categoryName) { order.append(m.categoryName) }
        return order.map { n in (n, data.medals.filter { $0.categoryName == n }) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "奖章墙", trailing: "\(data.earnedMedals)/\(data.medals.count) 已获得")
            Card {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(groups, id: \.name) { g in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(g.name).font(.system(size: 10.5, weight: .semibold)).foregroundStyle(.secondary)
                            HStack(alignment: .top, spacing: 6) {
                                ForEach(g.medals) { m in
                                    MedalView(medal: m, tilts: true)
                                        .frame(maxWidth: .infinity)
                                        .contentShape(Rectangle())
                                        .onTapGesture { UsageStore.shared.openTrophy(Unlock(kind: .medal, id: m.id)) }
                                        .help("查看「\(m.name)」详情与分享")
                                }
                                ForEach(0..<max(0, 4 - g.medals.count), id: \.self) { _ in Color.clear.frame(maxWidth: .infinity, maxHeight: 1) }
                            }
                        }
                    }
                }
            }
        }
    }
}

// MARK: Binder

private struct BinderSection: View {
    let data: CollectionData
    let title: String
    let cards: [CollectionData.CardDef]

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 8), count: 4)

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: title, trailing: "\(cards.filter { data.owned[$0.id] != nil }.count)/\(cards.count)")
            LazyVGrid(columns: columns, spacing: 8) {
                ForEach(cards) { def in
                    TradingCard(def: def, owned: data.owned[def.id], serial: data.serial(def.id))
                        .holoTilt(RoundedRectangle(cornerRadius: 8, style: .continuous), maxAngle: 13,
                                  glare: data.owned[def.id] == nil ? 0.12 : 0.36)
                        .contentShape(Rectangle())
                        .onTapGesture { UsageStore.shared.openTrophy(Unlock(kind: .card, id: def.id)) }
                        .help("查看「\(def.name)」详情与分享")
                }
            }
        }
    }
}

