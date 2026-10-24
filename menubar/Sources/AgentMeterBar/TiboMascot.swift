import SwiftUI

/// Q 版 Tibo 吉祥物与「重置器」。纯装饰：情绪只是把预测页已有的数据换一种
/// 说法（已记录的落地、站内承诺、各站公布的中位值），不产生任何新的判断。

// MARK: - Mood

enum TiboMood {
    case resetting   // 已公告时段正在进行
    case celebrate   // 追踪站 24 小时内记录到一次全员重置
    case excited     // 站内挂着承诺，或 48 小时中位 ≥ 50%
    case waiting     // 48 小时中位 ≥ 20%
    case sleepy      // 其余情况
    case offline     // 没有任何可用预测

    /// Same thresholds as the notifier, so the mascot never celebrates a
    /// landing that the alerts would not claim.
    static func from(forecast: JSON, targets: [JSON], now: Date) -> TiboMood {
        if targets.contains(where: { $0["kind"].string == "promised_reset" && $0["state"].string == "inside_window" }) {
            return .resetting
        }
        if let latest = forecast["history_events"].array.first, latest["kind"].string == "reset",
           let at = latest["announced_at"].date, at <= now, now.timeIntervalSince(at) < 86400,
           ["high", "medium"].contains(latest["confidence"].string ?? "") {
            return .celebrate
        }
        let horizons = forecast["ensemble"]["horizons"].object
        guard !horizons.isEmpty else { return .offline }
        let median = horizons["48h"]?["weighted_median"].double ?? horizons["24h"]?["weighted_median"].double ?? 0
        if !forecast["promises"].array.isEmpty || median >= 50 { return .excited }
        if median >= 20 { return .waiting }
        return .sleepy
    }

    var pressing: Bool { self == .resetting || self == .celebrate }
}

// MARK: - Palette

/// Colours for the mascot and the machine, one set per theme. Minimal is line
/// art, native is flat system colour, aurora is pastel with gradients, neon is
/// glowing wireframe on ink.
struct TiboPalette {
    var skin: Color
    var hair: Color
    var hairLine: Color
    var shirt: Color
    var pants: Color
    var outline: Color
    var eye: Color
    var cheek: Color
    var mouth: Color
    var badge: Color
    var sparkles: [Color]
    var glow: Color?
    var line: CGFloat

    static func make(_ theme: PanelTheme, _ scheme: ColorScheme) -> TiboPalette {
        switch theme {
        case .minimal:
            let paper = Color(nsColor: .textBackgroundColor)
            return TiboPalette(skin: paper, hair: .primary, hairLine: .primary, shirt: paper, pants: .primary,
                               outline: .primary, eye: .primary, cheek: Color.primary.opacity(0.14),
                               mouth: .primary, badge: .primary, sparkles: [.primary, .secondary], glow: nil, line: 2)
        case .native:
            let ink = Color(red: 0.24, green: 0.17, blue: 0.14)
            return TiboPalette(skin: Color(red: 1.0, green: 0.87, blue: 0.76), hair: Color(red: 0.33, green: 0.23, blue: 0.19),
                               hairLine: ink, shirt: Color(nsColor: .systemBlue), pants: Color(red: 0.25, green: 0.28, blue: 0.36),
                               outline: ink, eye: ink, cheek: Color(nsColor: .systemPink).opacity(0.45),
                               mouth: Color(red: 0.75, green: 0.25, blue: 0.28), badge: .white,
                               sparkles: [Color(nsColor: .systemYellow), Color(nsColor: .systemOrange)], glow: nil, line: 1.8)
        case .titanium:
            let ink = Color(red: 0.06, green: 0.09, blue: 0.13)
            return TiboPalette(skin: Color(red: 0.92, green: 0.82, blue: 0.72), hair: Color(red: 0.24, green: 0.34, blue: 0.43),
                               hairLine: Color.white.opacity(0.55), shirt: Color(red: 0.32, green: 0.55, blue: 0.68),
                               pants: Color(red: 0.12, green: 0.18, blue: 0.25), outline: ink, eye: ink,
                               cheek: Color(red: 0.90, green: 0.42, blue: 0.42).opacity(0.48), mouth: Color(red: 0.65, green: 0.20, blue: 0.24),
                               badge: .white, sparkles: [Color(red: 0.56, green: 0.76, blue: 0.88), Color.white],
                               glow: Color(red: 0.40, green: 0.62, blue: 0.78).opacity(0.42), line: 1.6)
        case .porcelain, .aurora:
            let ink = Color(red: 0.16, green: 0.14, blue: 0.34)
            return TiboPalette(skin: Color(red: 1.0, green: 0.89, blue: 0.82), hair: Color(red: 0.46, green: 0.40, blue: 0.98),
                               hairLine: ink, shirt: Color(red: 0.20, green: 0.82, blue: 0.80),
                               pants: Color(red: 0.36, green: 0.34, blue: 0.62), outline: ink, eye: ink,
                               cheek: Color(red: 1.0, green: 0.48, blue: 0.62).opacity(0.55),
                               mouth: Color(red: 0.86, green: 0.30, blue: 0.45), badge: .white,
                               sparkles: [Color(red: 0.70, green: 0.36, blue: 0.98), Color(red: 0.18, green: 0.80, blue: 0.98),
                                          Color(red: 1.0, green: 0.62, blue: 0.40)],
                               glow: Color(red: 0.55, green: 0.40, blue: 1.0).opacity(scheme == .dark ? 0.55 : 0.3), line: 1.8)
        case .neon, .prism:
            return TiboPalette(skin: Neon.ink, hair: Neon.magenta.opacity(0.28), hairLine: Neon.magenta,
                               shirt: Neon.cyan.opacity(0.16), pants: Neon.violet.opacity(0.35), outline: Neon.cyan,
                               eye: Neon.cyan, cheek: Neon.magenta.opacity(0.7), mouth: Neon.magenta, badge: Neon.lime,
                               sparkles: [Neon.yellow, Neon.lime, Neon.magenta], glow: Neon.cyan, line: 1.6)
        }
    }
}

// MARK: - Chibi

/// Big-head, small-body Tibo drawn in a 100×124 design box. `headOnly` crops to
/// the face for list avatars.
struct TiboChibi: View {
    var mood: TiboMood
    var headOnly = false
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var bob = false

    private var still: Bool { headOnly || reduceMotion || PanelView.expandForPreview }

    var body: some View {
        let palette = TiboPalette.make(theme, scheme)
        Group {
            if still {
                canvas(palette, blink: false)
            } else {
                // Blink about once every four seconds; the canvas is tiny so
                // the redraw is cheap and stops when the tab is hidden.
                TimelineView(.periodic(from: .now, by: 0.15)) { context in
                    let t = context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 4.2)
                    canvas(palette, blink: t < 0.15)
                }
            }
        }
        .offset(y: bob ? -1.5 : 1)
        .onAppear {
            guard !still else { return }
            withAnimation(.easeInOut(duration: mood == .sleepy ? 2.4 : 1.3).repeatForever(autoreverses: true)) { bob = true }
        }
        .accessibilityHidden(true)
    }

    private func canvas(_ p: TiboPalette, blink: Bool) -> some View {
        Canvas { ctx, size in
            let box = headOnly ? CGRect(x: 14, y: 0, width: 72, height: 76) : CGRect(x: 0, y: 0, width: 100, height: 124)
            let k = min(size.width / box.width, size.height / box.height)
            ctx.translateBy(x: (size.width - box.width * k) / 2 - box.minX * k, y: (size.height - box.height * k) / 2 - box.minY * k)
            ctx.scaleBy(x: k, y: k)
            if let glow = p.glow { ctx.addFilter(.shadow(color: glow, radius: theme == .neon ? 2.5 : 4)) }
            TiboArt(p: p, mood: mood, blink: blink, headOnly: headOnly).draw(in: &ctx)
        }
    }
}

private struct TiboArt {
    let p: TiboPalette
    let mood: TiboMood
    let blink: Bool
    let headOnly: Bool

    func draw(in ctx: inout GraphicsContext) {
        let lw = p.line
        func fillStroke(_ path: Path, _ fill: Color, _ stroke: Color? = nil) {
            ctx.fill(path, with: .color(fill))
            ctx.stroke(path, with: .color(stroke ?? p.outline), style: StrokeStyle(lineWidth: lw, lineCap: .round, lineJoin: .round))
        }
        func line(_ path: Path, _ color: Color, _ width: CGFloat) {
            ctx.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
        }
        func limb(from a: CGPoint, to b: CGPoint, _ color: Color, width: CGFloat, hand: Color?) {
            var path = Path(); path.move(to: a); path.addLine(to: b)
            line(path, p.outline, width + lw * 2)
            line(path, color, width)
            if let hand { fillStroke(Path(ellipseIn: CGRect(x: b.x - 4.5, y: b.y - 4.5, width: 9, height: 9)), hand) }
        }

        if !headOnly {
            ctx.fill(Path(ellipseIn: CGRect(x: 26, y: 114, width: 48, height: 7)), with: .color(p.outline.opacity(0.14)))
            // Legs, body, collar, chest badge.
            fillStroke(Path(roundedRect: CGRect(x: 37, y: 98, width: 10, height: 15), cornerRadius: 4), p.pants)
            fillStroke(Path(roundedRect: CGRect(x: 53, y: 98, width: 10, height: 15), cornerRadius: 4), p.pants)
            let leftHand = mood == .celebrate ? CGPoint(x: 15, y: 62) : CGPoint(x: 21, y: 96)
            let rightHand = mood.pressing || mood == .excited ? CGPoint(x: 88, y: 64) : CGPoint(x: 79, y: 96)
            limb(from: CGPoint(x: 33, y: 80), to: leftHand, p.shirt, width: 8, hand: p.skin)
            limb(from: CGPoint(x: 67, y: 80), to: rightHand, p.shirt, width: 8, hand: p.skin)
            fillStroke(Path(roundedRect: CGRect(x: 29, y: 72, width: 42, height: 32), cornerRadius: 14), p.shirt)
            var collar = Path()
            collar.move(to: CGPoint(x: 43, y: 73)); collar.addLine(to: CGPoint(x: 50, y: 80)); collar.addLine(to: CGPoint(x: 57, y: 73))
            line(collar, p.outline, lw)
            ctx.fill(Sparkle().path(in: CGRect(x: 54, y: 83, width: 10, height: 10)), with: .color(p.badge))
        }

        // Ears, head, hair, ahoge.
        fillStroke(Path(ellipseIn: CGRect(x: 15, y: 41, width: 11, height: 12)), p.skin)
        fillStroke(Path(ellipseIn: CGRect(x: 74, y: 41, width: 11, height: 12)), p.skin)
        fillStroke(Path(ellipseIn: CGRect(x: 19, y: 14, width: 62, height: 60)), p.skin)
        var hair = Path()
        hair.move(to: CGPoint(x: 19, y: 46))
        hair.addCurve(to: CGPoint(x: 50, y: 9), control1: CGPoint(x: 14, y: 20), control2: CGPoint(x: 31, y: 9))
        hair.addCurve(to: CGPoint(x: 81, y: 46), control1: CGPoint(x: 69, y: 9), control2: CGPoint(x: 86, y: 20))
        for (x, y) in [(76, 31), (68, 37), (62, 27), (53, 35), (45, 26), (37, 36), (29, 29)] {
            hair.addLine(to: CGPoint(x: x, y: y))
        }
        hair.closeSubpath()
        fillStroke(hair, p.hair, p.hairLine)
        var ahoge = Path()
        ahoge.move(to: CGPoint(x: 50, y: 11))
        ahoge.addCurve(to: CGPoint(x: 61, y: 2), control1: CGPoint(x: 47, y: 2), control2: CGPoint(x: 55, y: -1))
        ahoge.addQuadCurve(to: CGPoint(x: 56, y: 9), control: CGPoint(x: 62, y: 8))
        line(ahoge, p.hairLine, lw + 0.6)

        // Cheeks, eyes, mouth.
        ctx.fill(Path(ellipseIn: CGRect(x: 25, y: 55, width: 11, height: 6)), with: .color(p.cheek))
        ctx.fill(Path(ellipseIn: CGRect(x: 64, y: 55, width: 11, height: 6)), with: .color(p.cheek))
        for cx in [39.0, 61.0] {
            let c = CGPoint(x: cx, y: 48)
            switch (mood, blink) {
            case (.sleepy, _), (_, true):
                var arc = Path(); arc.move(to: CGPoint(x: c.x - 4.5, y: c.y)); arc.addQuadCurve(to: CGPoint(x: c.x + 4.5, y: c.y), control: CGPoint(x: c.x, y: c.y + 4))
                line(arc, p.eye, 2.2)
            case (.celebrate, _):
                ctx.fill(Sparkle().path(in: CGRect(x: c.x - 6, y: c.y - 6, width: 12, height: 12)), with: .color(p.sparkles[0]))
            case (.excited, _), (.resetting, _):
                var arc = Path(); arc.move(to: CGPoint(x: c.x - 4.5, y: c.y + 1.5)); arc.addQuadCurve(to: CGPoint(x: c.x + 4.5, y: c.y + 1.5), control: CGPoint(x: c.x, y: c.y - 6))
                line(arc, p.eye, 2.4)
            default:
                ctx.fill(Path(ellipseIn: CGRect(x: c.x - 3.6, y: c.y - 4.8, width: 7.2, height: 9.6)), with: .color(p.eye))
                ctx.fill(Path(ellipseIn: CGRect(x: c.x - 0.4, y: c.y - 3.6, width: 2.8, height: 2.8)), with: .color(.white))
            }
        }
        switch mood {
        case .celebrate, .excited, .resetting:
            var open = Path()
            open.move(to: CGPoint(x: 45, y: 58)); open.addLine(to: CGPoint(x: 55, y: 58))
            open.addQuadCurve(to: CGPoint(x: 45, y: 58), control: CGPoint(x: 50, y: 68))
            open.closeSubpath()
            fillStroke(open, p.mouth)
        case .sleepy:
            ctx.fill(Path(ellipseIn: CGRect(x: 48, y: 58, width: 4, height: 4)), with: .color(p.mouth))
        case .waiting, .offline:
            var smile = Path(); smile.move(to: CGPoint(x: 46, y: 59)); smile.addQuadCurve(to: CGPoint(x: 54, y: 59), control: CGPoint(x: 50, y: 63))
            line(smile, p.outline, lw)
        }

        guard !headOnly else { return }
        // Mood props around the figure.
        switch mood {
        case .sleepy, .offline:
            for (i, (x, y, s)) in [(80.0, 20.0, 9.0), (88.0, 10.0, 11.0)].enumerated() {
                ctx.draw(Text("z").font(.system(size: s, weight: .heavy, design: .rounded)).foregroundStyle(p.sparkles[i % p.sparkles.count]),
                         at: CGPoint(x: x, y: y))
            }
        case .waiting:
            var drop = Path()
            drop.move(to: CGPoint(x: 80, y: 22))
            drop.addQuadCurve(to: CGPoint(x: 80, y: 33), control: CGPoint(x: 74, y: 31))
            drop.addQuadCurve(to: CGPoint(x: 80, y: 22), control: CGPoint(x: 86, y: 31))
            fillStroke(drop, Color(red: 0.55, green: 0.80, blue: 1.0).opacity(0.85))
        case .excited, .resetting:
            ctx.draw(Text("!").font(.system(size: 16, weight: .black, design: .rounded)).foregroundStyle(p.sparkles[0]),
                     at: CGPoint(x: 86, y: 16))
            for (a, b) in [((92.0, 52.0), (98.0, 48.0)), ((93.0, 60.0), (99.0, 60.0))] {
                var dash = Path(); dash.move(to: CGPoint(x: a.0, y: a.1)); dash.addLine(to: CGPoint(x: b.0, y: b.1))
                line(dash, p.sparkles[1 % p.sparkles.count], 1.6)
            }
        case .celebrate:
            for (i, (x, y, s)) in [(9.0, 30.0, 10.0), (88.0, 12.0, 12.0), (6.0, 80.0, 7.0), (94.0, 86.0, 8.0)].enumerated() {
                ctx.fill(Sparkle().path(in: CGRect(x: x - s / 2, y: y - s / 2, width: s, height: s)),
                         with: .color(p.sparkles[i % p.sparkles.count]))
            }
        }
    }
}

// MARK: - Resetter machine

/// A cute arcade-style box: dome button and antenna on top, an LCD with the
/// pooled 48-hour median, two knobs and a ticket strip with the next window.
struct ResetterMachine: View {
    var percent: Double?
    var horizon = "48h"
    var secondary: String?
    var ticket: String
    var pressed: Bool
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulse = false

    var body: some View {
        let s = MachineStyle.make(theme, scheme)
        VStack(spacing: 0) {
            top(s)
            bodyBox(s)
            ticketStrip(s)
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.72), value: pressed)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Tibo 重置预测，\(horizon == "24h" ? "24" : "48") 小时中位概率 \(percent.map { Fmt.trim($0) + "%" } ?? "未知")，\(ticket)")
        .onAppear {
            guard !reduceMotion, !PanelView.expandForPreview else { return }
            withAnimation(.easeInOut(duration: pressed ? 0.45 : 1.2).repeatForever(autoreverses: true)) { pulse = true }
        }
    }

    private func top(_ s: MachineStyle) -> some View {
        HStack(alignment: .bottom, spacing: 0) {
            // Antenna with a status light.
            VStack(spacing: 0) {
                Circle().fill(s.light).frame(width: 8, height: 8)
                    .overlay(Circle().strokeBorder(s.outline, lineWidth: s.line * 0.7))
                    .opacity(pulse || PanelView.expandForPreview ? 1 : 0.45)
                    .themeGlow(s.light, radius: 4, theme: theme)
                Rectangle().fill(s.outline).frame(width: s.line, height: 12)
            }
            .padding(.leading, 18)
            Spacer()
            VStack(spacing: 0) {
                UnevenRoundedRectangle(topLeadingRadius: 22, topTrailingRadius: 22, style: .continuous)
                    .fill(s.button)
                    .overlay(UnevenRoundedRectangle(topLeadingRadius: 22, topTrailingRadius: 22, style: .continuous)
                        .strokeBorder(s.outline, lineWidth: s.line))
                    .overlay(alignment: .topLeading) {
                        Capsule().fill(Color.white.opacity(theme == .minimal ? 0 : 0.55))
                            .frame(width: 10, height: 4).rotationEffect(.degrees(-20)).offset(x: 9, y: 5)
                    }
                    .frame(width: 44, height: pressed ? 11 : 17)
                    .themeGlow(s.buttonGlow, radius: pressed && pulse ? 9 : 4, theme: theme)
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(s.plate)
                    .overlay(RoundedRectangle(cornerRadius: 2, style: .continuous).strokeBorder(s.outline, lineWidth: s.line))
                    .frame(width: 62, height: 7)
            }
            Spacer()
            Text("RESET")
                .font(.system(size: 7.5, weight: .heavy, design: .rounded)).kerning(1)
                .foregroundStyle(s.label)
                .padding(.trailing, 14).padding(.bottom, 2)
        }
        .frame(height: 30)
    }

    private func bodyBox(_ s: MachineStyle) -> some View {
        let shape = RoundedRectangle(cornerRadius: theme.isLuminous ? 9 : 18, style: .continuous)
        return HStack(spacing: 8) {
            screen(s)
            VStack(spacing: 7) {
                knob(s, angle: pressed ? 60 : -40)
                knob(s, angle: 15)
                Capsule().fill(s.outline.opacity(0.75)).frame(width: 16, height: 3)
            }
            .frame(width: 22)
        }
        .padding(9)
        .background(shape.fill(s.body))
        .overlay(shape.strokeBorder(s.rim, lineWidth: s.line))
        .overlay(alignment: .top) {
            Capsule().fill(Color.white.opacity(theme == .minimal ? 0 : 0.24))
                .frame(height: 1).padding(.horizontal, 20).padding(.top, 4)
        }
        .overlay(alignment: .topLeading) {
            HStack { rivet(s); Spacer(); rivet(s) }.padding(.horizontal, 6).padding(.top, 4)
        }
        .shadow(color: s.buttonGlow.opacity(theme.is3D ? 0.18 : 0.08), radius: theme.is3D ? 8 : 3, y: pressed ? 2 : 5)
        .offset(y: pressed ? 2 : 0)
    }

    private func screen(_ s: MachineStyle) -> some View {
        let lit = Int(((percent ?? 0) / 10).rounded())
        let shape = RoundedRectangle(cornerRadius: theme.isLuminous ? 5 : 10, style: .continuous)
        return VStack(alignment: .leading, spacing: 4) {
            Text("\(horizon == "24h" ? "24" : "48") 小时内全员重置")
                .font(.system(size: 9.5, weight: .medium, design: theme.isLuminous ? .monospaced : .rounded))
                .foregroundStyle(s.screenDim)
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                Text(percent.map { Fmt.trim($0) + "%" } ?? "--%")
                    .font(theme.number(28)).monospacedDigit()
                    .foregroundStyle(s.screenText)
                    .lineLimit(1).minimumScaleFactor(0.7)
                    .contentTransition(.numericText())
                if let secondary {
                    Text(secondary).font(.system(size: 9.5, design: theme.isLuminous ? .monospaced : .rounded))
                        .foregroundStyle(s.screenDim).lineLimit(1)
                }
            }
            HStack(spacing: 2.5) {
                ForEach(0..<10, id: \.self) { i in
                    RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                        .fill(i < lit ? s.led(i) : s.screenDim.opacity(0.22))
                        .frame(height: 5)
                }
            }
        }
        .padding(.horizontal, 9).padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(shape.fill(s.screen))
        .overlay(shape.strokeBorder(s.outline.opacity(0.7), lineWidth: s.line * 0.75))
        .overlay(alignment: .topLeading) {
            shape.stroke(Color.white.opacity(0.10), lineWidth: 2).blur(radius: 1).padding(1)
        }
        .shadow(color: .black.opacity(0.28), radius: 2, y: -1)
    }

    private func knob(_ s: MachineStyle, angle: Double) -> some View {
        Circle().fill(s.plate)
            .overlay(Circle().fill(RadialGradient(colors: [.white.opacity(0.42), .clear], center: .topLeading, startRadius: 0, endRadius: 18)))
            .overlay(Circle().strokeBorder(s.outline, lineWidth: s.line * 0.8))
            .overlay(Capsule().fill(s.outline).frame(width: 1.8, height: 6).offset(y: -3).rotationEffect(.degrees(angle)))
            .frame(width: 17, height: 17)
            .shadow(color: .black.opacity(0.25), radius: 1.5, y: 1)
    }

    private func rivet(_ s: MachineStyle) -> some View {
        Circle().fill(s.outline.opacity(0.5)).frame(width: 3.5, height: 3.5)
    }

    private func ticketStrip(_ s: MachineStyle) -> some View {
        HStack(spacing: 4) {
            Image(systemName: "ticket").font(.system(size: 8.5, weight: .semibold))
            Text(ticket).font(.system(size: 9.5, weight: .medium, design: theme == .neon ? .monospaced : .rounded))
                .monospacedDigit().lineLimit(1).minimumScaleFactor(0.8)
        }
        .foregroundStyle(s.paperText)
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background(TicketShape().fill(s.paper))
        .overlay(TicketShape().stroke(s.outline.opacity(0.6), style: StrokeStyle(lineWidth: 0.8, dash: theme == .minimal ? [2, 2] : [])))
        .padding(.horizontal, 22)
        .offset(y: -1)
    }
}

/// Paper strip with a zig-zag tear at the bottom.
private struct TicketShape: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX, y: r.maxY - 2))
        let teeth = max(4, Int(r.width / 6))
        let w = r.width / CGFloat(teeth)
        for i in 0..<teeth {
            let x = r.maxX - CGFloat(i) * w
            p.addLine(to: CGPoint(x: x - w / 2, y: r.maxY))
            p.addLine(to: CGPoint(x: x - w, y: r.maxY - 2))
        }
        p.closeSubpath()
        return p
    }
}

private struct MachineStyle {
    var body: AnyShapeStyle
    var rim: AnyShapeStyle
    var outline: Color
    var line: CGFloat
    var screen: Color
    var screenText: AnyShapeStyle
    var screenDim: Color
    var ledColors: [Color]
    var button: AnyShapeStyle
    var buttonGlow: Color
    var plate: Color
    var light: Color
    var label: Color
    var paper: Color
    var paperText: Color

    func led(_ i: Int) -> Color {
        ledColors.count == 1 ? ledColors[0] : ledColors[min(i * ledColors.count / 10, ledColors.count - 1)]
    }

    static func make(_ theme: PanelTheme, _ scheme: ColorScheme) -> MachineStyle {
        let dark = scheme == .dark
        switch theme {
        case .minimal:
            let paper = Color(nsColor: .textBackgroundColor)
            return MachineStyle(body: AnyShapeStyle(paper), rim: AnyShapeStyle(Color.primary), outline: .primary, line: 1.4,
                                screen: Color.primary.opacity(0.04), screenText: AnyShapeStyle(Color.primary), screenDim: .secondary,
                                ledColors: [.primary], button: AnyShapeStyle(Color.primary), buttonGlow: .clear,
                                plate: paper, light: .primary, label: .secondary, paper: paper, paperText: .primary)
        case .native:
            let red = Color(nsColor: .systemRed)
            return MachineStyle(body: AnyShapeStyle(Color(nsColor: .windowBackgroundColor)),
                                rim: AnyShapeStyle(Color(nsColor: .separatorColor)), outline: Color.primary.opacity(0.55), line: 1.2,
                                screen: Color(nsColor: .textBackgroundColor), screenText: AnyShapeStyle(Color.accentColor),
                                screenDim: .secondary, ledColors: [Color.accentColor], button: AnyShapeStyle(red), buttonGlow: red,
                                plate: Color(nsColor: .controlBackgroundColor), light: Color(nsColor: .systemGreen),
                                label: .secondary, paper: Color(nsColor: .textBackgroundColor), paperText: .secondary)
        case .porcelain:
            let ink = Color(red: 0.20, green: 0.26, blue: 0.36)
            let coral = Color(red: 0.91, green: 0.48, blue: 0.45)
            let blue = Color(red: 0.40, green: 0.60, blue: 0.78)
            return MachineStyle(body: AnyShapeStyle(LinearGradient(colors: [Color(red: 0.96, green: 0.96, blue: 0.94), Color(red: 0.72, green: 0.77, blue: 0.84)], startPoint: .topLeading, endPoint: .bottomTrailing)),
                                rim: AnyShapeStyle(LinearGradient(colors: [.white, blue.opacity(0.55)], startPoint: .top, endPoint: .bottom)),
                                outline: ink.opacity(0.58), line: 1.0, screen: Color(red: 0.08, green: 0.12, blue: 0.19),
                                screenText: AnyShapeStyle(Color(red: 0.62, green: 0.90, blue: 0.91)), screenDim: Color.white.opacity(0.58),
                                ledColors: [blue, Color(red: 0.55, green: 0.78, blue: 0.72), coral],
                                button: AnyShapeStyle(LinearGradient(colors: [Color(red: 1.0, green: 0.68, blue: 0.60), coral], startPoint: .top, endPoint: .bottom)),
                                buttonGlow: coral, plate: Color(red: 0.82, green: 0.85, blue: 0.88), light: Color(red: 0.40, green: 0.78, blue: 0.60),
                                label: ink.opacity(0.65), paper: Color(red: 0.91, green: 0.90, blue: 0.85), paperText: ink.opacity(0.72))
        case .titanium:
            let edge = Color(red: 0.50, green: 0.68, blue: 0.80)
            return MachineStyle(body: AnyShapeStyle(LinearGradient(colors: [Color(red: 0.28, green: 0.32, blue: 0.36), Color(red: 0.07, green: 0.09, blue: 0.12)], startPoint: .topLeading, endPoint: .bottomTrailing)),
                                rim: AnyShapeStyle(LinearGradient(colors: [Color.white.opacity(0.55), edge, Color.black], startPoint: .topLeading, endPoint: .bottomTrailing)),
                                outline: Color.white.opacity(0.30), line: 1.0, screen: Color(red: 0.025, green: 0.04, blue: 0.055),
                                screenText: AnyShapeStyle(LinearGradient(colors: [.white, edge], startPoint: .top, endPoint: .bottom)), screenDim: Color.white.opacity(0.70),
                                ledColors: [edge, Color.white], button: AnyShapeStyle(LinearGradient(colors: [Color(red: 0.48, green: 0.68, blue: 0.78), Color(red: 0.16, green: 0.29, blue: 0.39)], startPoint: .top, endPoint: .bottom)),
                                buttonGlow: edge, plate: Color(red: 0.18, green: 0.22, blue: 0.26), light: Color(red: 0.35, green: 0.90, blue: 0.68),
                                label: Color.white.opacity(0.68), paper: Color(red: 0.09, green: 0.12, blue: 0.15), paperText: Color.white.opacity(0.80))
        case .aurora:
            let violet = Color(red: 0.70, green: 0.36, blue: 0.98), indigo = Color(red: 0.40, green: 0.45, blue: 1.0)
            let mint = Color(red: 0.20, green: 0.88, blue: 0.70), cyan = Color(red: 0.18, green: 0.80, blue: 0.98)
            let pink = Color(red: 1.0, green: 0.45, blue: 0.62)
            return MachineStyle(body: AnyShapeStyle(LinearGradient(colors: [Color.white.opacity(dark ? 0.12 : 0.75), Color.white.opacity(dark ? 0.04 : 0.4)],
                                                                   startPoint: .top, endPoint: .bottom)),
                                rim: AnyShapeStyle(LinearGradient(colors: [indigo.opacity(0.7), violet.opacity(0.5), cyan.opacity(0.4)],
                                                                  startPoint: .topLeading, endPoint: .bottomTrailing)),
                                outline: Color(red: 0.16, green: 0.14, blue: 0.34).opacity(dark ? 0.9 : 0.75), line: 1.3,
                                screen: Color(red: 0.07, green: 0.08, blue: 0.20),
                                screenText: AnyShapeStyle(LinearGradient(colors: [mint, cyan], startPoint: .leading, endPoint: .trailing)),
                                screenDim: Color.white.opacity(0.6), ledColors: [mint, cyan, indigo, violet, pink],
                                button: AnyShapeStyle(LinearGradient(colors: [pink, violet], startPoint: .top, endPoint: .bottom)),
                                buttonGlow: pink, plate: Color(red: 0.86, green: 0.86, blue: 0.98), light: mint,
                                label: indigo, paper: dark ? Color(red: 0.16, green: 0.16, blue: 0.28) : .white,
                                paperText: dark ? Color.white.opacity(0.8) : Color(red: 0.25, green: 0.24, blue: 0.45))
        case .neon, .prism:
            return MachineStyle(body: AnyShapeStyle(Color.black.opacity(0.6)), rim: AnyShapeStyle(Neon.rim), outline: Neon.cyan, line: 1.2,
                                screen: Color.black.opacity(0.8), screenText: AnyShapeStyle(Neon.cyan), screenDim: Neon.cyan.opacity(0.6),
                                ledColors: [Neon.lime, Neon.yellow, Neon.orange, Neon.magenta], button: AnyShapeStyle(Neon.magenta),
                                buttonGlow: Neon.magenta, plate: Neon.ink, light: Neon.lime, label: Neon.magenta,
                                paper: Neon.ink, paperText: Neon.yellow)
        }
    }
}

// MARK: - Speech bubble

struct SpeechBubble: View {
    let title: String
    let detail: String
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.system(size: 12, weight: .bold, design: theme == .neon ? .monospaced : .rounded))
                .themeForeground()
            Text(detail).font(theme.font(10.5, weight: .medium))
                .themeForeground(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 11).padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(BubbleShape().fill(fill))
        .overlay(BubbleShape().stroke(stroke, lineWidth: theme == .minimal ? 1 : 0.7))
        .shadow(color: .black.opacity(scheme == .dark ? 0.16 : 0.05), radius: 3, y: 2)
        .padding(.bottom, 6)
    }

    private var fill: AnyShapeStyle {
        switch theme {
        case .minimal, .native: return AnyShapeStyle(Color(nsColor: .textBackgroundColor))
        case .porcelain: return AnyShapeStyle(Color.white.opacity(0.88))
        case .aurora: return AnyShapeStyle(scheme == .dark ? Color.white.opacity(0.10) : Color.white.opacity(0.72))
        case .titanium: return AnyShapeStyle(Color(red: 0.15, green: 0.19, blue: 0.24).opacity(0.82))
        case .neon, .prism: return AnyShapeStyle(Color(red: 0.025, green: 0.035, blue: 0.075).opacity(0.86))
        }
    }

    private var stroke: AnyShapeStyle {
        switch theme {
        case .minimal: return AnyShapeStyle(Color.primary.opacity(0.70))
        case .native: return AnyShapeStyle(Color(nsColor: .separatorColor))
        case .porcelain, .aurora: return AnyShapeStyle(LinearGradient(colors: [theme.accent[0].opacity(0.42), theme.accent[1].opacity(0.24)], startPoint: .leading, endPoint: .trailing))
        case .titanium: return AnyShapeStyle(Color.white.opacity(0.18))
        case .neon: return AnyShapeStyle(Neon.magenta.opacity(0.68))
        case .prism: return AnyShapeStyle(Neon.violet.opacity(0.48))
        }
    }
}

/// Rounded box with a tail at the lower left, pointing at Tibo's head.
private struct BubbleShape: Shape {
    func path(in r: CGRect) -> Path {
        let body = CGRect(x: r.minX, y: r.minY, width: r.width, height: r.height - 6)
        var p = Path(roundedRect: body, cornerRadius: 11, style: .continuous)
        var tail = Path()
        tail.move(to: CGPoint(x: r.minX + 34, y: body.maxY - 0.5))
        tail.addQuadCurve(to: CGPoint(x: r.minX + 30, y: r.maxY + 1), control: CGPoint(x: r.minX + 34, y: r.maxY - 2))
        tail.addQuadCurve(to: CGPoint(x: r.minX + 46, y: body.maxY - 0.5), control: CGPoint(x: r.minX + 40, y: body.maxY + 3))
        p.addPath(tail)
        return p.normalized()
    }
}

// MARK: - Small Q stickers

/// Round sticker icon in front of a section title.
struct QSticker: View {
    let symbol: String
    var tint: Color? = nil
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let color = tint ?? theme.accent[0]
        let darkIcon = theme == .titanium || theme == .prism
        Image(systemName: symbol)
            .font(.system(size: 9, weight: .bold))
            .foregroundStyle(theme == .minimal ? Color.primary : (theme == .neon ? color : (darkIcon ? Neon.ink : .white)))
            .frame(width: 18, height: 18)
            .background(Circle().fill(theme == .minimal || theme == .neon ? Color.clear : color))
            .overlay(Circle().strokeBorder(theme == .minimal ? Color.primary.opacity(0.5) : color.opacity(theme == .neon ? 0.65 : 0), lineWidth: 1))
            .themeGlow(color.opacity(0.24), radius: 2, theme: theme)
    }
}

struct QSectionTitle: View {
    let symbol: String
    let text: String
    var trailing: String? = nil
    var tint: Color? = nil

    var body: some View {
        HStack(spacing: 5) {
            QSticker(symbol: symbol, tint: tint)
            SectionTitle(text: text, trailing: trailing)
        }
    }
}

/// Mini head avatar for list rows.
struct TiboFace: View {
    var mood: TiboMood = .celebrate
    var size: CGFloat = 16

    var body: some View {
        TiboChibi(mood: mood, headOnly: true).frame(width: size, height: size)
    }
}
