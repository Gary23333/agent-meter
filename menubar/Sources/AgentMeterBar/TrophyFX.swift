import AppKit
import SwiftUI

// MARK: - Motion

enum Motion {
    /// Previews and Reduce Motion get the final frame without movement.
    static var isStatic: Bool {
        PanelView.expandForPreview || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }
}

// MARK: - Pointer-following tilt

/// Tilts a trophy toward the pointer in 3D, lifts it, and slides a specular
/// glare across its face. The hover is read from an untransformed overlay, so
/// the tilt never feeds back into its own pointer coordinates.
struct HoloTilt<S: Shape>: ViewModifier {
    let shape: S
    var maxAngle: Double = 16
    var glare: Double = 0.6
    /// Pointer position, -0.5…0.5 per axis; zero at rest.
    @State private var tilt: CGPoint = .zero
    /// Where the glare sits (unit point); kept after the pointer leaves so it fades in place.
    @State private var light = UnitPoint(x: 0.5, y: 0.3)
    @State private var hovering = false
    @State private var size: CGSize = .zero

    func body(content: Content) -> some View {
        content
            .environment(\.tilt, tilt)
            .overlay {
                // Always in the tree; only its opacity changes, so it never pops in.
                ZStack {
                    // Soft light pool under the pointer: tinted, not a white blowout.
                    RadialGradient(colors: [.white.opacity(glare * 0.55), .white.opacity(glare * 0.12), .clear],
                                   center: light, startRadius: 0, endRadius: max(size.width, size.height) * 0.6)
                        .blendMode(.softLight)
                    RadialGradient(colors: [.white.opacity(glare * 0.22), .clear],
                                   center: light, startRadius: 0, endRadius: max(size.width, size.height) * 0.35)
                        .blendMode(.screen)
                    // Iridescent band opposite the light, like foil turning.
                    LinearGradient(colors: [.clear, .cyan.opacity(0.16), .purple.opacity(0.14), .pink.opacity(0.1), .clear],
                                   startPoint: UnitPoint(x: 1 - light.x, y: 0), endPoint: UnitPoint(x: light.x, y: 1))
                        .blendMode(.overlay)
                }
                .clipShape(shape)
                .overlay {
                    // Rim light: the edge nearest the pointer catches the light.
                    shape.stroke(LinearGradient(colors: [.white.opacity(min(0.75, glare * 1.3)), .white.opacity(0.05), .clear],
                                                startPoint: light, endPoint: UnitPoint(x: 1 - light.x, y: 1 - light.y)),
                                 lineWidth: 1.4)
                }
                .opacity(hovering ? 1 : 0)
                .allowsHitTesting(false)
            }
            .rotation3DEffect(.degrees(Double(-tilt.y) * maxAngle * 2), axis: (x: 1, y: 0, z: 0), perspective: 0.5)
            .rotation3DEffect(.degrees(Double(tilt.x) * maxAngle * 2), axis: (x: 0, y: 1, z: 0), perspective: 0.5)
            .scaleEffect(hovering ? 1.05 : 1)
            .shadow(color: .black.opacity(hovering ? 0.24 : 0), radius: hovering ? 9 : 0,
                    x: -tilt.x * 8, y: 4 - tilt.y * 6)
            .overlay {
                GeometryReader { geo in
                    Color.clear
                        .contentShape(Rectangle())
                        .onAppear { size = geo.size }
                        .onChange(of: geo.size) { _, new in size = new }
                        .onContinuousHover(coordinateSpace: .local) { phase in
                            switch phase {
                            case .active(let p):
                                guard size.width > 0, size.height > 0 else { return }
                                let next = CGPoint(x: min(0.5, max(-0.5, p.x / size.width - 0.5)),
                                                   y: min(0.5, max(-0.5, p.y / size.height - 0.5)))
                                // Ignore sub-pixel jitter; it only restarts the spring.
                                guard abs(next.x - tilt.x) > 0.006 || abs(next.y - tilt.y) > 0.006 || !hovering else { return }
                                withAnimation(.interactiveSpring(response: 0.32, dampingFraction: 0.88, blendDuration: 0.12)) {
                                    tilt = next
                                    light = UnitPoint(x: next.x + 0.5, y: next.y + 0.5)
                                }
                                if !hovering { withAnimation(.easeOut(duration: 0.22)) { hovering = true } }
                            case .ended:
                                withAnimation(.spring(response: 0.5, dampingFraction: 0.9)) {
                                    tilt = .zero
                                    hovering = false
                                }
                            }
                        }
                }
            }
            .zIndex(hovering ? 1 : 0)
    }
}

extension View {
    func holoTilt<S: Shape>(_ shape: S, maxAngle: Double = 16, glare: Double = 0.6) -> some View {
        modifier(HoloTilt(shape: shape, maxAngle: maxAngle, glare: glare))
    }
}

// MARK: - Unlocks

/// A trophy the user has not seen yet.
struct Unlock: Identifiable, Equatable {
    enum Kind: Equatable { case medal, card }
    let kind: Kind
    let id: String
}

enum UnlockTracker {
    private static let key = "seenTrophies"

    /// New medals and first copies of cards since the last look. The first
    /// run only records what exists, so history never floods the screen.
    static func newUnlocks(in data: CollectionData) -> [Unlock] {
        let current = Set(data.medals.filter(\.earned).map { "medal:" + $0.id })
            .union(data.owned.keys.filter { $0 != "rc_wasted" }.map { "card:" + $0 })
        let defaults = UserDefaults.standard
        guard let seenList = defaults.stringArray(forKey: key) else {
            defaults.set(Array(current), forKey: key)
            return []
        }
        let seen = Set(seenList)
        let fresh = current.subtracting(seen)
        guard !fresh.isEmpty else { return [] }
        defaults.set(Array(seen.union(current)), forKey: key)
        // Medals first, then cards from rarest; stable by id.
        let medals = data.medals.filter { fresh.contains("medal:" + $0.id) }.map { Unlock(kind: .medal, id: $0.id) }
        let cards = data.catalog.filter { fresh.contains("card:" + $0.id) }
            .sorted { $0.rarity.stars > $1.rarity.stars }
            .map { Unlock(kind: .card, id: $0.id) }
        return medals + cards
    }
}

struct LightRays: View {
    let color: Color
    var count = 16

    var body: some View {
        Canvas { ctx, size in
            let c = CGPoint(x: size.width / 2, y: size.height / 2)
            let r = max(size.width, size.height) / 2
            for i in 0..<count {
                let a = Double(i) / Double(count) * 2 * .pi
                let w = .pi / Double(count) * 0.55
                var p = Path()
                p.move(to: c)
                p.addArc(center: c, radius: r, startAngle: .radians(a - w), endAngle: .radians(a + w), clockwise: false)
                p.closeSubpath()
                ctx.fill(p, with: .radialGradient(Gradient(colors: [color.opacity(0.55), color.opacity(0)]),
                                                  center: c, startRadius: 10, endRadius: r))
            }
        }
    }
}

/// Confetti burst: deterministic particles driven by time since `start`.
struct Confetti: View {
    let colors: [Color]
    let start: Date
    private static let pieces: [(x: Double, vx: Double, vy: Double, spin: Double, size: Double, shape: Int, color: Int)] = {
        var g = SystemRandomNumberGenerator()
        return (0..<90).map { i in
            (Double.random(in: 0.3...0.7, using: &g), Double.random(in: -260...260, using: &g),
             Double.random(in: -520 ... -220, using: &g), Double.random(in: -9...9, using: &g),
             Double.random(in: 4...8, using: &g), i % 3, i)
        }
    }()

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 60)) { context in
            let t = context.date.timeIntervalSince(start)
            Canvas { ctx, size in
                guard t < 4.5 else { return }
                for p in Self.pieces {
                    let x = size.width * p.x + p.vx * t
                    let y = size.height * 0.42 + p.vy * t + 0.5 * 620 * t * t
                    guard y < size.height + 20 else { continue }
                    let alpha = max(0, 1 - t / 4.5)
                    var c = ctx
                    c.translateBy(x: x, y: y)
                    c.rotate(by: .radians(p.spin * t))
                    let rect = CGRect(x: -p.size / 2, y: -p.size / 4, width: p.size, height: p.shape == 0 ? p.size : p.size / 2)
                    let shape = p.shape == 1 ? Path(ellipseIn: rect) : Path(rect)
                    c.fill(shape, with: .color(colors[p.color % colors.count].opacity(alpha)))
                }
            }
        }
        .allowsHitTesting(false)
    }
}

// MARK: - Share images

enum TrophyShare {
    enum Action { case copy, save }
    static let width: CGFloat = 540
    /// Whether trophy share images carry the project QR code (on by default).
    static let qrKey = "trophyShareQR"
    static var showsQR: Bool { UserDefaults.standard.object(forKey: qrKey) as? Bool ?? true }

    static func medalGoal(_ m: CollectionData.Medal) -> String {
        switch m.unit {
        case "tokens": return (m.category == "day_peak" ? "单日 " : "累计 ") + Fmt.tokens(m.target) + " Token"
        case "days": return (m.category == "img_streak" ? "连续出图 " : "连续活跃 ") + "\(Int(m.target)) 天"
        case "apps": return "一天用 \(Int(m.target)) 个应用"
        case "times": return "刷新个人最佳 \(Int(m.target)) 次"
        case "credits": return (m.category == "creative" ? "创作积分用掉 " : "免费积分用掉 ") + Fmt.grouped(m.target)
        case "cny":
            let prefix = ["cost_day": "单日估算花费 ", "cost_month": "单月估算花费 ", "cost_life": "累计估算价值 "][m.category] ?? ""
            return prefix + "¥" + Fmt.grouped(m.target)
        case "images": return (m.category == "img_day" ? "单日出图 " : "累计出图 ") + Fmt.grouped(m.target) + " 张"
        default: return Fmt.grouped(m.target)
        }
    }

    @MainActor
    static func png(_ view: some View) -> Data? {
        let renderer = ImageRenderer(content: view.frame(width: width))
        renderer.scale = 2
        renderer.isOpaque = true
        renderer.proposedSize = ProposedViewSize(width: width, height: nil)
        guard let cg = renderer.cgImage else { return nil }
        let rep = NSBitmapImageRep(cgImage: cg)
        rep.size = CGSize(width: CGFloat(cg.width) / 2, height: CGFloat(cg.height) / 2)
        return rep.representation(using: .png, properties: [:])
    }

    /// Copies or saves; returns a short status line for a toast.
    @MainActor
    static func perform(_ action: Action, png: Data?, name: String) -> String {
        guard let png else { return "生成图片失败" }
        switch action {
        case .copy:
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setData(png, forType: .png)
            return "已复制分享图"
        case .save:
            let panel = NSSavePanel()
            panel.allowedContentTypes = [.png]
            panel.canCreateDirectories = true
            panel.nameFieldStringValue = name + ".png"
            NSApp.activate(ignoringOtherApps: true)
            guard panel.runModal() == .OK, let url = panel.url else { return "已取消" }
            do { try png.write(to: url); return "已保存 \(url.lastPathComponent)" }
            catch { return "保存失败" }
        }
    }
}

// MARK: - Trophy stage (unlock celebration and detail page)

/// Full-panel stage for one medal or card. `unlock` plays the celebration
/// (rays, confetti, flip-in) with a "收下" queue; `detail` is the same stage
/// opened from the binder, with progress for locked pieces and a close button.
struct TrophyStage: View {
    enum Mode: Equatable { case unlock(position: Int, total: Int), detail }

    let unlock: Unlock
    let data: CollectionData
    let mode: Mode
    let onShare: (TrophyShare.Action) -> Void
    let onDismiss: () -> Void

    @AppStorage(TrophyShare.qrKey) private var showsQR = true
    @State private var stage: Double = Motion.isStatic ? 1 : 0
    @State private var spin = false
    @State private var start = Date()
    @State private var pointer: CGPoint = .zero

    private var medal: CollectionData.Medal? { unlock.kind == .medal ? data.medals.first { $0.id == unlock.id } : nil }
    private var card: CollectionData.CardDef? { unlock.kind == .card ? data.def(unlock.id) : nil }
    private var owned: Bool { medal?.earned ?? (card.map { data.owned[$0.id] != nil } ?? false) }
    private var accent: [Color] {
        guard owned else { return [Color(white: 0.35), Color(white: 0.7), Color(white: 0.5)] }
        return medal?.tier.colors ?? card?.rarity.colors ?? Rarity.legendary.colors
    }
    private var isUnlock: Bool { if case .unlock = mode { return true } else { return false } }

    var body: some View {
        ZStack {
            Rectangle().fill(.ultraThinMaterial).environment(\.colorScheme, .dark)
            Color.black.opacity(0.6)
            RadialGradient(colors: [accent[1].opacity(0.5), accent[0].opacity(0.16), .clear],
                           center: .init(x: 0.5, y: 0.36), startRadius: 4, endRadius: 280)
                .scaleEffect(0.6 + 0.4 * stage)
            StarField(seed: 7).opacity(0.5)
            if owned {
                GeometryReader { geo in
                    LightRays(color: accent[1])
                        .frame(width: 560, height: 560)
                        .rotationEffect(.degrees(spin ? 360 : 0))
                        .position(x: geo.size.width / 2, y: geo.size.height * 0.36)
                        .opacity((isUnlock ? 0.32 : 0.2) * stage)
                        .blendMode(.screen)
                }
            }
            if isUnlock && !Motion.isStatic { Confetti(colors: accent + [.white, .pink, .cyan, .yellow], start: start) }
            if owned { SparkBurst(colors: accent + [.white], start: start) }

            VStack(spacing: 12) {
                topBar
                trophy.frame(height: 200).padding(.top, 4)
                titleBlock
                infoBlock
                actions
                if case .unlock(let position, let total) = mode, total > 1 {
                    HStack(spacing: 5) {
                        ForEach(1...total, id: \.self) { i in
                            Capsule().fill(i == position ? Color.white : .white.opacity(0.3))
                                .frame(width: i == position ? 14 : 5, height: 5)
                        }
                    }
                }
            }
            .padding(.horizontal, 22)
            .padding(.vertical, 18)
        }
        .clipped()
        .contentShape(Rectangle())
        .modifier(PointerTracker(pointer: $pointer))
        .onAppear(perform: play)
        .onChange(of: unlock) { _, _ in
            stage = Motion.isStatic ? 1 : 0
            start = Date()
            play()
        }
    }

    private var topBar: some View {
        HStack {
            Text(heading)
                .font(.system(size: 11.5, weight: .heavy)).kerning(3)
                .foregroundStyle(LinearGradient(colors: [accent[1], .white], startPoint: .leading, endPoint: .trailing))
            Spacer()
            if !isUnlock {
                Button(action: onDismiss) {
                    Image(systemName: "xmark").font(.system(size: 11, weight: .bold)).foregroundStyle(.white.opacity(0.8))
                        .frame(width: 24, height: 24).background(Circle().fill(.white.opacity(0.12)))
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.cancelAction)
                .help("关闭")
            }
        }
        .opacity(stage)
    }

    private var heading: String {
        switch (isUnlock, medal != nil) {
        case (true, true): return "解锁新奖章"
        case (true, false): return "新卡片入册"
        case (false, true): return "奖章详情"
        case (false, false): return "卡片详情"
        }
    }

    private var trophy: some View {
        let entrance = Motion.isStatic ? 1 : stage
        return ZStack {
            if owned {
                EnergyRings(colors: accent, tilt: pointer)
                    .opacity(entrance)
                OrbitParticles(color: accent[1], radius: 118, tilt: pointer, half: .back).opacity(entrance)
            }
            piece(entrance)
            if owned { OrbitParticles(color: accent[1], radius: 118, tilt: pointer, half: .front).opacity(entrance) }
        }
        .frame(width: 400)
    }

    @ViewBuilder private func piece(_ entrance: Double) -> some View {
        Group {
            if let medal {
                MedalView(medal: medal, showsCaption: false, ornate: true)
                    .scaleEffect(2.9)
                    .frame(width: 160, height: 160)
                    .holoTilt(Circle(), maxAngle: 20, glare: owned ? 0.6 : 0.2)
            } else if let card {
                TradingCard(def: card, owned: data.owned[card.id], large: true, serial: data.serial(card.id))
                    .frame(width: 136)
                    .holoTilt(RoundedRectangle(cornerRadius: 12, style: .continuous), maxAngle: 14, glare: owned ? 0.42 : 0.15)
            }
        }
        .scaleEffect(0.25 + 0.75 * entrance)
        .rotation3DEffect(.degrees((1 - entrance) * (isUnlock ? 540 : 90)), axis: (x: 0, y: 1, z: 0), perspective: 0.5)
        .shadow(color: accent[0].opacity(0.8 * entrance), radius: 22)
    }

    private var titleBlock: some View {
        VStack(spacing: 4) {
            Text(medal?.name ?? card?.name ?? "")
                .font(.system(size: 24, weight: .black, design: .rounded))
                .foregroundStyle(owned ? AnyShapeStyle(LinearGradient(colors: [.white, accent[1]], startPoint: .top, endPoint: .bottom))
                                       : AnyShapeStyle(Color.white.opacity(0.75)))
                .shadow(color: accent[1].opacity(owned ? 0.8 : 0), radius: 8)
            Text(subtitle).font(.system(size: 11.5, weight: .semibold)).foregroundStyle(accent[1])
        }
        .opacity(stage)
        .offset(y: (1 - stage) * 14)
    }

    @ViewBuilder private var infoBlock: some View {
        VStack(spacing: 8) {
            Text(goal).font(.system(size: 11.5)).foregroundStyle(.white.opacity(0.8)).multilineTextAlignment(.center)
            if let medal, !medal.earned {
                VStack(spacing: 4) {
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(.white.opacity(0.12))
                            Capsule().fill(LinearGradient(colors: [medal.tier.colors[2], medal.tier.colors[1]], startPoint: .leading, endPoint: .trailing))
                                .frame(width: max(5, geo.size.width * medal.progress))
                        }
                    }
                    .frame(width: 220, height: 6)
                    Text("当前 \(TrophyShare.valueText(medal, medal.value)) · 完成 \(Int(medal.progress * 100))%")
                        .font(.system(size: 10.5, design: .rounded)).foregroundStyle(.white.opacity(0.6))
                }
            }
            HStack(spacing: 8) {
                ForEach(facts, id: \.0) { fact in
                    VStack(spacing: 2) {
                        Text(fact.1).font(.system(size: 13, weight: .heavy, design: .rounded)).foregroundStyle(.white).monospacedDigit()
                            .lineLimit(1).minimumScaleFactor(0.7)
                        Text(fact.0).font(.system(size: 9.5)).foregroundStyle(.white.opacity(0.55))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(.white.opacity(0.07)))
                }
            }
            .frame(maxWidth: 320)
        }
        .opacity(stage)
    }

    private var facts: [(String, String)] {
        if let medal {
            var out: [(String, String)] = [("等级", medal.tier.label), ("目标", TrophyShare.valueText(medal, medal.target))]
            if medal.earned { out.append(("达成", medal.earnedOn ?? "—")) }
            if medal.count > 1 { out.append(("次数", "×\(medal.count)")) }
            return out
        }
        guard let card else { return [] }
        let o = data.owned[card.id]
        var out: [(String, String)] = [("稀有度", card.rarity.label), ("编号", data.serial(card.id))]
        if let o {
            out.append(("持有", "\(o.count) 张"))
            if let first = o.firstAt { out.append(("首次", Fmt.day(first))) }
        } else {
            out.append(("状态", "未获得"))
        }
        return out
    }

    private var goal: String {
        if let medal { return TrophyShare.medalGoal(medal) }
        guard let card else { return "" }
        var text = card.description
        if let sources = data.owned[card.id]?.sources, !sources.isEmpty {
            text += " · 来自 " + sources.map { Catalog.brand($0).name }.joined(separator: "、")
        }
        return text
    }

    private var subtitle: String {
        if let medal { return "\(medal.categoryName) · \(medal.tier.label)奖章" }
        if let card { return "\(card.seriesName) · \(card.rarity.label)" + String(repeating: " ★", count: card.rarity.stars) }
        return ""
    }

    private var actions: some View {
        HStack(spacing: 8) {
            if owned {
                ghostButton("复制", symbol: "doc.on.doc") { onShare(.copy) }
                ghostButton("保存", symbol: "square.and.arrow.down") { onShare(.save) }
                Button { showsQR.toggle() } label: {
                    Image(systemName: showsQR ? "qrcode" : "qrcode.viewfinder")
                        .font(.system(size: 12, weight: .semibold))
                        .frame(width: 30, height: 30)
                        .background(Circle().fill(showsQR ? accent[1].opacity(0.35) : .white.opacity(0.1)))
                        .overlay(Circle().strokeBorder(.white.opacity(0.3), lineWidth: 0.8))
                        .foregroundStyle(.white)
                }
                .buttonStyle(.plain)
                .help(showsQR ? "分享图附带项目二维码（点击关闭）" : "分享图不带二维码（点击开启）")
            }
            Button(action: onDismiss) {
                Text(primaryTitle)
                    .font(.system(size: 12, weight: .bold))
                    .padding(.horizontal, 18).padding(.vertical, 7)
                    .background(Capsule().fill(LinearGradient(colors: [accent[1], accent[0]], startPoint: .top, endPoint: .bottom)))
                    .foregroundStyle(.white)
                    .shadow(color: accent[1].opacity(0.6), radius: 6)
            }
            .buttonStyle(.plain)
            .keyboardShortcut(.defaultAction)
        }
        .opacity(stage)
    }

    private var primaryTitle: String {
        if case .unlock(let position, let total) = mode { return position < total ? "收下 · 下一个" : "收下" }
        return "关闭"
    }

    private func ghostButton(_ title: String, symbol: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.system(size: 11.5, weight: .semibold))
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(Capsule().fill(.white.opacity(0.12)))
                .overlay(Capsule().strokeBorder(.white.opacity(0.3), lineWidth: 0.8))
                .foregroundStyle(.white)
        }
        .buttonStyle(.plain)
        .help(title == "复制" ? "复制分享图到剪贴板" : "保存分享图 PNG")
    }

    private func play() {
        guard !Motion.isStatic else { return }
        withAnimation(.spring(response: isUnlock ? 0.9 : 0.55, dampingFraction: isUnlock ? 0.62 : 0.8)) { stage = 1 }
        spin = false
        withAnimation(.linear(duration: 18).repeatForever(autoreverses: false)) { spin = true }
    }
}

extension TrophyShare {
    static func valueText(_ m: CollectionData.Medal, _ v: Double) -> String {
        switch m.unit {
        case "tokens": return Fmt.tokens(v)
        case "days": return "\(Int(v)) 天"
        case "apps": return "\(Int(v)) 个"
        case "times": return "\(Int(v)) 次"
        case "credits": return Fmt.grouped(v)
        case "cny": return "¥" + Fmt.grouped(v)
        case "images": return Fmt.grouped(v) + " 张"
        default: return Fmt.grouped(v)
        }
    }
}

/// Tiny deterministic stars for dark stages.
struct StarField: View {
    let seed: Int

    var body: some View {
        Canvas { ctx, size in
            var x = UInt64(seed * 7919 + 17)
            func next() -> CGFloat { x = x &* 6364136223846793005 &+ 1442695040888963407; return CGFloat(x >> 33) / CGFloat(1 << 31) }
            for _ in 0..<70 {
                let p = CGPoint(x: next() * size.width, y: next() * size.height)
                let r = 0.4 + next() * 1.2
                ctx.fill(Path(ellipseIn: CGRect(x: p.x, y: p.y, width: r, height: r)), with: .color(.white.opacity(0.25 + next() * 0.6)))
            }
        }
        .allowsHitTesting(false)
    }
}

// MARK: - Share images

/// Share image for one medal or card: a holographic frame, the piece on a lit
/// podium, the goal, six headline numbers and (optionally) the project QR.
struct TrophyShareCard: View {
    let unlock: Unlock
    let data: CollectionData
    var showsQR = TrophyShare.showsQR

    private var medal: CollectionData.Medal? { unlock.kind == .medal ? data.medals.first { $0.id == unlock.id } : nil }
    private var card: CollectionData.CardDef? { unlock.kind == .card ? data.def(unlock.id) : nil }
    private var accent: [Color] { medal?.tier.colors ?? card?.rarity.colors ?? Rarity.legendary.colors }

    var body: some View {
        VStack(spacing: 0) {
            ShareBrand(accent: accent[1])
            ZStack {
                LightRays(color: accent[1], count: 22).frame(width: 520, height: 520).opacity(0.55)
                Podium(color: accent[1]).offset(y: 132)
                EnergyRings(colors: accent).scaleEffect(1.2)
                OrbitParticles(color: accent[1], count: 44, radius: 150, half: .back)
                Group {
                    if let medal {
                        MedalView(medal: medal, showsCaption: false, ornate: true).scaleEffect(3.5).frame(width: 190, height: 190)
                    } else if let card {
                        TradingCard(def: card, owned: data.owned[card.id], large: true, serial: data.serial(card.id)).frame(width: 176)
                    }
                }
                .shadow(color: accent[1].opacity(0.55), radius: 30)
                OrbitParticles(color: accent[1], count: 44, radius: 150, half: .front)
            }
            .frame(height: 330)
            VStack(spacing: 8) {
                Text(medal != nil ? "ACHIEVEMENT UNLOCKED" : "NEW CARD COLLECTED")
                    .font(.system(size: 11, weight: .heavy, design: .monospaced)).kerning(3).foregroundStyle(accent[1].opacity(0.9))
                Text(medal?.name ?? card?.name ?? "")
                    .font(.system(size: 40, weight: .black, design: .rounded))
                    .foregroundStyle(LinearGradient(colors: [.white, accent[1]], startPoint: .top, endPoint: .bottom))
                    .shadow(color: accent[1].opacity(0.7), radius: 12)
                HStack(spacing: 8) {
                    Pill(text: medal.map { "\($0.categoryName) · \($0.tier.label)奖章" } ?? card.map { "\($0.seriesName) · \($0.rarity.label)" } ?? "",
                         colors: [accent[0], accent[2 % accent.count]])
                    if let medal, medal.count > 1 { Pill(text: "已达成 \(medal.count) 次", colors: [.pink, .purple]) }
                    if let card, let n = data.owned[card.id]?.count, n > 1 { Pill(text: "持有 \(n) 张", colors: [.pink, .purple]) }
                }
                Text(medal.map { TrophyShare.medalGoal($0) } ?? card?.description ?? "")
                    .font(.system(size: 15, weight: .medium)).foregroundStyle(.white.opacity(0.85))
                if let date = medal?.earnedOn ?? card.flatMap({ data.owned[$0.id]?.firstAt }).map({ Fmt.day($0) }) {
                    Text("达成于 " + date).font(.system(size: 12)).foregroundStyle(.white.opacity(0.5))
                }
            }
            .padding(.bottom, 22)
            ShareStatsGrid(data: data, accent: accent[1])
            ShareFooter(showsQR: showsQR).padding(.top, 20)
        }
        .padding(28)
        .frame(width: TrophyShare.width)
        .background(ShareStage(accent: accent))
        .overlay(HoloFrame().padding(10))
        .environment(\.colorScheme, .dark)
    }
}

/// Share image for the whole binder.
struct CollectionShareCard: View {
    let data: CollectionData
    var showsQR = TrophyShare.showsQR
    private let medalColumns = Array(repeating: GridItem(.flexible(), spacing: 8), count: 6)
    private let cardColumns = Array(repeating: GridItem(.flexible(), spacing: 9), count: 6)

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            ShareBrand(accent: Rarity.epic.glow)
            HStack(spacing: 22) {
                ZStack {
                    ActivityRing(progress: Double(data.distinct) / Double(max(1, data.collectible.count)),
                                 colors: [Color(red: 1, green: 0.25, blue: 0.45), Color(red: 1, green: 0.55, blue: 0.75)], width: 15)
                        .frame(width: 136, height: 136)
                    ActivityRing(progress: Double(data.earnedMedals) / Double(max(1, data.medals.count)),
                                 colors: [Color(red: 0.55, green: 0.95, blue: 0.2), Color(red: 0.8, green: 1, blue: 0.4)], width: 15)
                        .frame(width: 102, height: 102)
                    ActivityRing(progress: min(1, (data.stats["current_streak"].double ?? 0) / 365),
                                 colors: [Color(red: 0.1, green: 0.85, blue: 0.95), Color(red: 0.45, green: 0.75, blue: 1)], width: 15)
                        .frame(width: 68, height: 68)
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("MY COLLECTION").font(.system(size: 11, weight: .heavy, design: .monospaced)).kerning(3)
                        .foregroundStyle(Rarity.epic.glow)
                    Text("我的收集册").font(.system(size: 32, weight: .black, design: .rounded))
                        .foregroundStyle(LinearGradient(colors: [.white, Color(red: 0.85, green: 0.75, blue: 1)], startPoint: .top, endPoint: .bottom))
                    HStack(spacing: 6) {
                        Pill(text: "卡片 \(data.distinct)/\(data.collectible.count)", colors: [Color(red: 1, green: 0.25, blue: 0.45), Color(red: 0.8, green: 0.2, blue: 0.5)])
                        Pill(text: "奖章 \(data.earnedMedals)/\(data.medals.count)", colors: [Color(red: 0.4, green: 0.75, blue: 0.1), Color(red: 0.25, green: 0.55, blue: 0.1)])
                    }
                    if let best = data.stats["best_day"]["tokens"].double {
                        Text("个人最佳单日 \(Fmt.tokens(best)) Token").font(.system(size: 13, weight: .semibold)).foregroundStyle(MedalTier.gold.colors[1])
                    }
                }
            }
            ShareStatsGrid(data: data, accent: Rarity.epic.glow)
            sectionTitle("奖章墙", "\(data.earnedMedals)/\(data.medals.count)")
            LazyVGrid(columns: medalColumns, spacing: 10) {
                ForEach(data.medals.sorted { ($0.earned ? 0 : 1, $0.id) < ($1.earned ? 0 : 1, $1.id) }) { MedalView(medal: $0) }
            }
            sectionTitle("卡册", "\(data.distinct)/\(data.collectible.count)")
            LazyVGrid(columns: cardColumns, spacing: 9) {
                ForEach(data.collectible) { TradingCard(def: $0, owned: data.owned[$0.id], serial: data.serial($0.id)) }
            }
            ShareFooter(showsQR: showsQR)
        }
        .padding(30)
        .frame(width: TrophyShare.width)
        .background(ShareStage(accent: Rarity.epic.colors))
        .overlay(HoloFrame().padding(10))
        .environment(\.colorScheme, .dark)
    }

    private func sectionTitle(_ title: String, _ trailing: String) -> some View {
        HStack {
            Rectangle().fill(LinearGradient(colors: [Rarity.epic.glow, .clear], startPoint: .leading, endPoint: .trailing)).frame(width: 18, height: 2)
            Text(title).font(.system(size: 13, weight: .heavy)).foregroundStyle(.white.opacity(0.85))
            Spacer()
            Text(trailing).font(.system(size: 12, weight: .semibold, design: .rounded)).foregroundStyle(.white.opacity(0.5))
        }
    }
}

private struct ShareBrand: View {
    let accent: Color

    var body: some View {
        HStack(spacing: 8) {
            ZStack {
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(LinearGradient(colors: [accent, Color(red: 0.35, green: 0.25, blue: 0.85)], startPoint: .topLeading, endPoint: .bottomTrailing))
                Image(systemName: "gauge.with.dots.needle.67percent").font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
            }
            .frame(width: 26, height: 26)
            VStack(alignment: .leading, spacing: 0) {
                Text("AgentMeter").font(.system(size: 13, weight: .heavy))
                Text("Agent 用量 · 收集册").font(.system(size: 9.5)).opacity(0.6)
            }
            Spacer()
            Text(Fmt.day(Date())).font(.system(size: 11, design: .monospaced)).opacity(0.6)
        }
        .foregroundStyle(.white)
        .padding(.bottom, 4)
    }
}

private struct ShareStatsGrid: View {
    let data: CollectionData
    let accent: Color

    private var items: [(String, String, String)] {
        [("卡片", "\(data.distinct)/\(data.collectible.count)", "rectangle.stack.fill"),
         ("奖章", "\(data.earnedMedals)/\(data.medals.count)", "medal.fill"),
         ("连续活跃", "\(Int(data.stats["current_streak"].double ?? 0)) 天", "flame.fill"),
         ("累计 Token", Fmt.tokens(data.stats["lifetime_tokens"].double ?? 0), "sum"),
         ("估算价值", "¥" + Fmt.tokens(data.stats["lifetime_cost_cny"].double ?? 0), "yensign.circle.fill"),
         ("累计出图", Fmt.grouped(data.stats["lifetime_images"].double ?? 0) + " 张", "photo.fill")]
    }

    var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
            ForEach(items, id: \.0) { item in
                HStack(spacing: 8) {
                    Image(systemName: item.2).font(.system(size: 13, weight: .bold)).foregroundStyle(accent)
                        .frame(width: 26, height: 26).background(Circle().fill(accent.opacity(0.15)))
                    VStack(alignment: .leading, spacing: 1) {
                        Text(item.1).font(.system(size: 15, weight: .heavy, design: .rounded)).foregroundStyle(.white)
                            .monospacedDigit().lineLimit(1).minimumScaleFactor(0.6)
                        Text(item.0).font(.system(size: 9.5)).foregroundStyle(.white.opacity(0.55))
                    }
                    Spacer(minLength: 0)
                }
                .padding(9)
                .background(RoundedRectangle(cornerRadius: 11, style: .continuous).fill(.white.opacity(0.06)))
                .overlay(RoundedRectangle(cornerRadius: 11, style: .continuous)
                    .strokeBorder(LinearGradient(colors: [.white.opacity(0.25), .white.opacity(0.05)], startPoint: .top, endPoint: .bottom), lineWidth: 0.8))
            }
        }
    }
}

private struct ShareFooter: View {
    let showsQR: Bool

    var body: some View {
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 3) {
                Text("数据来自本机账本 · 不含对话内容").font(.system(size: 9.5)).foregroundStyle(.white.opacity(0.45))
                Text("金额为 API 等价估算 · USD 按 1:7.25 折算").font(.system(size: 9.5)).foregroundStyle(.white.opacity(0.45))
            }
            Spacer()
            if showsQR { QRBadge(size: 64) }
        }
        .padding(.top, 14)
        .overlay(alignment: .top) { Rectangle().fill(.white.opacity(0.12)).frame(height: 0.6) }
    }
}

private struct Pill: View {
    let text: String
    let colors: [Color]

    var body: some View {
        Text(text).font(.system(size: 11, weight: .bold)).foregroundStyle(.white)
            .padding(.horizontal, 10).padding(.vertical, 4)
            .background(Capsule().fill(LinearGradient(colors: colors, startPoint: .leading, endPoint: .trailing)))
            .overlay(Capsule().strokeBorder(.white.opacity(0.35), lineWidth: 0.6))
    }
}

/// Lit ellipse the trophy stands on.
private struct Podium: View {
    let color: Color

    var body: some View {
        ZStack {
            Ellipse().fill(RadialGradient(colors: [color.opacity(0.7), color.opacity(0.0)], center: .center, startRadius: 2, endRadius: 140))
                .frame(width: 300, height: 56)
            Ellipse().stroke(color.opacity(0.6), lineWidth: 1.2).frame(width: 200, height: 30)
            Ellipse().stroke(.white.opacity(0.25), lineWidth: 0.8).frame(width: 260, height: 42)
        }
    }
}

/// Iridescent hairline frame around share images.
private struct HoloFrame: View {
    var body: some View {
        RoundedRectangle(cornerRadius: 18, style: .continuous)
            .strokeBorder(AngularGradient(colors: [.pink, .orange, .yellow, .green, .cyan, .blue, .purple, .pink], center: .center),
                          lineWidth: 1.5)
            .opacity(0.55)
    }
}

private struct ShareStage: View {
    let accent: [Color]

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.04, green: 0.05, blue: 0.10), Color(red: 0.09, green: 0.06, blue: 0.17)],
                           startPoint: .top, endPoint: .bottom)
            RadialGradient(colors: [accent[1].opacity(0.42), .clear], center: .init(x: 0.5, y: 0.25), startRadius: 10, endRadius: 380)
            RadialGradient(colors: [accent[0].opacity(0.35), .clear], center: .init(x: 0.05, y: 0.95), startRadius: 10, endRadius: 320)
            RadialGradient(colors: [Color.purple.opacity(0.25), .clear], center: .init(x: 1, y: 0.7), startRadius: 10, endRadius: 300)
            // Perspective grid floor.
            Canvas { ctx, size in
                var p = Path()
                let horizon = size.height * 0.62
                for i in 0...16 {
                    let x = size.width * CGFloat(i) / 16
                    p.move(to: CGPoint(x: size.width / 2 + (x - size.width / 2) * 0.15, y: horizon))
                    p.addLine(to: CGPoint(x: size.width / 2 + (x - size.width / 2) * 2.2, y: size.height))
                }
                var y = horizon
                var step: CGFloat = 6
                while y < size.height {
                    p.move(to: CGPoint(x: 0, y: y)); p.addLine(to: CGPoint(x: size.width, y: y))
                    y += step; step *= 1.25
                }
                ctx.stroke(p, with: .linearGradient(Gradient(colors: [.white.opacity(0), accent[1].opacity(0.18)]),
                                                     startPoint: CGPoint(x: 0, y: horizon), endPoint: CGPoint(x: 0, y: size.height)),
                           lineWidth: 0.7)
            }
            StarField(seed: 3).opacity(0.7)
        }
    }
}
