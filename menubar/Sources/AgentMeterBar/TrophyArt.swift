import AppKit
import CoreImage.CIFilterBuiltins
import SwiftUI

// MARK: - Project link and QR code

enum ProjectLink {
    static let url = "https://github.com/Gary23333/agent-meter"
    static let label = "github.com/Gary23333/agent-meter"
}

enum QRCode {
    private static var cache: [String: NSImage] = [:]

    /// Crisp black-on-white QR code; scale up with `.interpolation(.none)`.
    static func image(_ text: String) -> NSImage? {
        if let hit = cache[text] { return hit }
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 12, y: 12)),
              let cg = CIContext().createCGImage(output, from: output.extent) else { return nil }
        let image = NSImage(cgImage: cg, size: NSSize(width: output.extent.width, height: output.extent.height))
        cache[text] = image
        return image
    }
}

/// QR tile with a caption, for share images.
struct QRBadge: View {
    var size: CGFloat = 66
    var title = "扫码获取 AgentMeter"
    var subtitle = ProjectLink.label
    /// Text colors for the background the badge sits on.
    var ink: Color = .white
    var muted: Color = .white.opacity(0.6)

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .trailing, spacing: 3) {
                Text(title).font(.system(size: 11.5, weight: .bold)).foregroundStyle(ink)
                Text("开源 · 免费 · macOS 菜单栏").font(.system(size: 9.5)).foregroundStyle(muted)
                Text(subtitle).font(.system(size: 9, design: .monospaced)).foregroundStyle(muted)
            }
            .lineLimit(1)
            .fixedSize()
            ZStack {
                RoundedRectangle(cornerRadius: 8, style: .continuous).fill(.white)
                if let image = QRCode.image(ProjectLink.url) {
                    Image(nsImage: image).interpolation(.none).resizable().padding(5)
                }
            }
            .frame(width: size, height: size)
            .shadow(color: .black.opacity(0.25), radius: 4, y: 2)
        }
    }
}

// MARK: - Medal

/// A struck medal: scalloped metal rim, engraved ring, embossed emblem; big
/// variants add ribbon tails. Locked medals show a progress ring.
struct MedalView: View {
    let medal: CollectionData.Medal
    var showsCaption = true
    /// The disc tilts toward the pointer; off where a parent already tilts.
    var tilts = false
    /// Ribbons and finer engraving for detail pages and share images.
    var ornate = false
    @State private var shine = false
    @State private var sheen = false
    @Environment(\.tilt) private var tilt

    var body: some View {
        VStack(spacing: 4) {
            disc
                .frame(width: 52, height: 52)
                .modifier(OptionalTilt(enabled: tilts, glare: medal.earned ? 0.8 : 0.25))
            if showsCaption {
                Text(medal.name).font(.system(size: 9.5, weight: medal.earned ? .semibold : .regular))
                    .foregroundStyle(medal.earned ? .primary : .secondary).lineLimit(1).minimumScaleFactor(0.8)
                Text(medal.earned ? (medal.earnedOn.map { String($0.dropFirst(5)) } ?? "") : "\(Int(medal.progress * 100))%")
                    .font(.system(size: 8.5, design: .rounded)).foregroundStyle(.tertiary).monospacedDigit()
            }
        }
        .onAppear {
            guard medal.earned, !Motion.isStatic else { return }
            if medal.tier == .gold || medal.tier == .platinum {
                withAnimation(.linear(duration: 6).repeatForever(autoreverses: false)) { shine = true }
            }
            let delay = Double(medal.id.unicodeScalars.reduce(0) { $0 + Int($1.value) } % 40) / 10
            withAnimation(.easeInOut(duration: 1.6).delay(3 + delay).repeatForever(autoreverses: false)) { sheen = true }
        }
    }

    private var c: [Color] { medal.tier.colors }

    private var disc: some View {
        ZStack {
            if medal.earned { earnedDisc } else { lockedDisc }
            if medal.earned && medal.count > 1 {
                Text("×\(medal.count)")
                    .font(.system(size: 8.5, weight: .heavy, design: .rounded))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 4).padding(.vertical, 1.5)
                    .background(Capsule().fill(LinearGradient(colors: [Color(red: 1, green: 0.35, blue: 0.5), Color(red: 0.9, green: 0.15, blue: 0.35)],
                                                              startPoint: .top, endPoint: .bottom)))
                    .overlay(Capsule().strokeBorder(.white.opacity(0.6), lineWidth: 0.5))
                    .offset(x: 19, y: -20)
            }
        }
    }

    @ViewBuilder private var earnedDisc: some View {
        if ornate { ribbons }
        // Coin thickness: darker copies of the rim stacked away from the viewer.
        ForEach(1...5, id: \.self) { i in
            Scallop(points: 24, depth: 0.045)
                .fill(c[0])
                .brightness(-0.08 - 0.05 * Double(i))
                .offset(x: -tilt.x * CGFloat(i) * 1.5, y: CGFloat(i) * 0.35 - tilt.y * CGFloat(i) * 1.5)
        }
        // Scalloped rim, metal turning with the light.
        Scallop(points: 24, depth: 0.045)
            .fill(AngularGradient(colors: c + [c[0]] + (medal.tier == .platinum ? [.pink.opacity(0.8), .cyan.opacity(0.8), c[0]] : []),
                                  center: .center, angle: .degrees(shine ? 360 : 0)))
            .shadow(color: c[1].opacity(0.55), radius: 5)
        Scallop(points: 24, depth: 0.045).stroke(.white.opacity(0.35), lineWidth: 0.5)
        // Face.
        Circle().inset(by: 5)
            .fill(RadialGradient(colors: [c[1], c[2], c[0]], center: UnitPoint(x: 0.3, y: 0.25), startRadius: 1, endRadius: 50))
        Circle().inset(by: 5).strokeBorder(LinearGradient(colors: [.white.opacity(0.9), c[0].opacity(0.6)], startPoint: .top, endPoint: .bottom),
                                           lineWidth: 1)
        // Engraved inner ring with ticks.
        Circle().inset(by: 9).strokeBorder(c[0].opacity(0.45), style: StrokeStyle(lineWidth: 0.7, dash: ornate ? [1, 1.6] : [1.2, 2.2]))
        // Embossed emblem: dark lower edge, light upper edge.
        ZStack {
            Image(systemName: medal.symbol).foregroundStyle(.white.opacity(0.7)).offset(y: -0.6)
            Image(systemName: medal.symbol).foregroundStyle(c[0].opacity(0.9)).offset(y: 0.6)
            Image(systemName: medal.symbol).foregroundStyle(LinearGradient(colors: [c[0], c[0].opacity(0.75)], startPoint: .top, endPoint: .bottom))
        }
        .font(.system(size: 18, weight: .bold))
        .parallax(tilt, depth: 5)
        // Glint slides toward the light (the pointer).
        Ellipse().fill(LinearGradient(colors: [.white.opacity(0.55), .clear], startPoint: .top, endPoint: .bottom))
            .frame(width: 30, height: 14)
            .offset(x: tilt.x * 14, y: -13 + tilt.y * 14)
            .blendMode(.plusLighter)
        // A slanted band crossing from fully off the left edge to fully off
        // the right edge: both ends are invisible, so the loop never jumps.
        GeometryReader { g in
            LinearGradient(colors: [.clear, .white.opacity(0.55), .clear], startPoint: .leading, endPoint: .trailing)
                .frame(width: g.size.width * 0.38, height: g.size.height * 1.6)
                .rotationEffect(.degrees(22))
                .position(x: g.size.width / 2, y: g.size.height / 2)
                .offset(x: g.size.width * (sheen ? 1.15 : -1.15))
        }
        .blendMode(.plusLighter)
        .clipShape(Circle().inset(by: 5))
        .allowsHitTesting(false)
    }

    private var ribbons: some View {
        HStack(spacing: 4) {
            RibbonTail().fill(LinearGradient(colors: [c[0], c[2]], startPoint: .top, endPoint: .bottom))
                .frame(width: 13, height: 26).rotationEffect(.degrees(16))
            RibbonTail().fill(LinearGradient(colors: [c[2], c[0]], startPoint: .top, endPoint: .bottom))
                .frame(width: 13, height: 26).rotationEffect(.degrees(-16))
        }
        .offset(y: 26)
    }

    @ViewBuilder private var lockedDisc: some View {
        Scallop(points: 24, depth: 0.045).fill(Color.primary.opacity(0.06))
        Circle().inset(by: 5).fill(Color.primary.opacity(0.04))
        Circle().stroke(Color.primary.opacity(0.10), lineWidth: 3.5).padding(3)
        Circle().trim(from: 0, to: max(0.001, medal.progress))
            .stroke(LinearGradient(colors: [c[1], c[2]], startPoint: .top, endPoint: .bottom),
                    style: StrokeStyle(lineWidth: 3.5, lineCap: .round))
            .rotationEffect(.degrees(-90)).padding(3)
        Image(systemName: medal.symbol).font(.system(size: 17, weight: .semibold))
            .foregroundStyle(LinearGradient(colors: [c[1].opacity(0.45), Color.primary.opacity(0.18)], startPoint: .top, endPoint: .bottom))
    }
}

/// A circle with a scalloped (coin-like) edge.
struct Scallop: Shape {
    let points: Int
    let depth: CGFloat

    func path(in rect: CGRect) -> Path {
        let c = CGPoint(x: rect.midX, y: rect.midY)
        let r = min(rect.width, rect.height) / 2
        var p = Path()
        let steps = points * 8
        for i in 0...steps {
            let a = Double(i) / Double(steps) * 2 * .pi
            let rr = r * (1 - depth * (1 - CGFloat(cos(Double(points) * a))) / 2)
            let pt = CGPoint(x: c.x + rr * CGFloat(sin(a)), y: c.y - rr * CGFloat(cos(a)))
            if i == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
        }
        p.closeSubpath()
        return p
    }
}

private struct RibbonTail: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: rect.minX, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        p.addLine(to: CGPoint(x: rect.midX, y: rect.maxY - rect.width * 0.45))
        p.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        p.closeSubpath()
        return p
    }
}

private struct OptionalTilt: ViewModifier {
    let enabled: Bool
    let glare: Double

    func body(content: Content) -> some View {
        if enabled { content.holoTilt(Circle(), maxAngle: 24, glare: glare) } else { content }
    }
}

// MARK: - Trading card

/// A trading card: rarity face with a series pattern in the art window, a
/// name plate, serial and rarity gem; holo foil for epic and legendary; a
/// locked silhouette until the first copy drops.
struct TradingCard: View {
    let def: CollectionData.CardDef
    let owned: CollectionData.Owned?
    var large = false
    var serial: String? = nil
    @State private var sweep = false
    @Environment(\.tilt) private var tilt

    private var unlocked: Bool { owned != nil }
    private var radius: CGFloat { large ? 12 : 8 }
    private var k: CGFloat { large ? 1.6 : 1 }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        ZStack {
            if unlocked {
                // Card stock edge, visible as the card leans.
                ForEach(1...3, id: \.self) { i in
                    shape.fill(def.rarity.colors[0]).brightness(-0.15 - 0.06 * Double(i))
                        .offset(x: -tilt.x * CGFloat(i) * 2.2 * k, y: -tilt.y * CGFloat(i) * 2.2 * k)
                }
                face(shape)
            } else { locked(shape) }
        }
        .aspectRatio(0.70, contentMode: .fit)
        .shadow(color: unlocked ? def.rarity.glow.opacity(def.rarity.holo ? 0.55 : 0.25) : .clear, radius: large ? 8 : 4, y: 2)
        .onAppear {
            guard unlocked, def.rarity.holo, !Motion.isStatic else { return }
            withAnimation(.easeInOut(duration: 2.6).repeatForever(autoreverses: true)) { sweep = true }
        }
    }

    private func face(_ shape: RoundedRectangle) -> some View {
        let colors = def.rarity.colors
        return ZStack {
            shape.fill(LinearGradient(colors: colors, startPoint: .bottomLeading, endPoint: .topTrailing))
            VStack(spacing: 3 * k) {
                // Header: stars and copies.
                HStack(spacing: 1) {
                    Text(String(repeating: "★", count: def.rarity.stars)).font(.system(size: 6 * k, weight: .black))
                    Spacer(minLength: 0)
                    if let count = owned?.count, count > 1 {
                        Text("×\(count)").font(.system(size: 8 * k, weight: .heavy, design: .rounded))
                    }
                }
                .foregroundStyle(.white.opacity(0.95))
                // Art window.
                ZStack {
                    RoundedRectangle(cornerRadius: 5 * k, style: .continuous)
                        .fill(LinearGradient(colors: [colors[0].opacity(0.9), colors[1].opacity(0.55)], startPoint: .top, endPoint: .bottom))
                    SeriesPattern(series: def.series)
                        .stroke(.white.opacity(0.22), lineWidth: 0.7)
                        .scaleEffect(1.15)
                        .parallax(tilt, depth: -6 * k)
                        .clipShape(RoundedRectangle(cornerRadius: 5 * k, style: .continuous))
                    RadialGradient(colors: [.white.opacity(0.35), .clear], center: .center, startRadius: 1, endRadius: 26 * k)
                        .parallax(tilt, depth: 4 * k)
                    // The emblem floats above the window and casts a shadow onto it.
                    Image(systemName: def.symbol)
                        .font(.system(size: 18 * k, weight: .bold))
                        .foregroundStyle(.black.opacity(0.28))
                        .blur(radius: 1.5 * k)
                        .parallax(tilt, depth: 2 * k)
                        .offset(y: 2 * k)
                    Image(systemName: def.symbol)
                        .font(.system(size: 18 * k, weight: .bold))
                        .foregroundStyle(LinearGradient(colors: [.white, .white.opacity(0.8)], startPoint: .top, endPoint: .bottom))
                        .shadow(color: colors[0].opacity(0.9), radius: 2 * k, y: 1)
                        .parallax(tilt, depth: 9 * k)
                    RoundedRectangle(cornerRadius: 5 * k, style: .continuous)
                        .strokeBorder(.white.opacity(0.5), lineWidth: 0.7 * k)
                }
                .frame(maxHeight: .infinity)
                // Name plate.
                VStack(spacing: 1) {
                    Text(def.name).font(.system(size: 9.5 * k, weight: .heavy)).foregroundStyle(.white)
                        .shadow(color: .black.opacity(0.45), radius: 1, y: 0.5)
                        .lineLimit(1).minimumScaleFactor(0.7)
                    HStack(spacing: 3) {
                        Text(serial ?? def.rarity.label).font(.system(size: 6 * k, weight: .semibold, design: .monospaced))
                        Spacer(minLength: 0)
                        Gem(color: colors[1]).frame(width: 6 * k, height: 6 * k)
                    }
                    .foregroundStyle(.white.opacity(0.75))
                }
                .padding(.horizontal, 4 * k).padding(.vertical, 2.5 * k)
                .background(RoundedRectangle(cornerRadius: 4 * k, style: .continuous).fill(.black.opacity(0.42)))
            }
            .padding(5 * k)
            if def.rarity.holo {
                foil(shape).mask(LinearGradient(stops: [.init(color: .white, location: 0), .init(color: .white, location: 0.62),
                                                        .init(color: .white.opacity(0.15), location: 0.8)],
                                                startPoint: .top, endPoint: .bottom))
            }
            if def.rarity == .legendary { sparkles }
            // Double frame: bright outer edge, thin inner rule.
            shape.strokeBorder(LinearGradient(colors: [.white.opacity(0.9), def.rarity.glow, .white.opacity(0.4)],
                                              startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1.4 * k)
            shape.inset(by: 2.6 * k).stroke(.white.opacity(0.25), lineWidth: 0.5)
        }
        .saturation(def.rarity == .faded ? 0.15 : 1)
    }

    private func foil(_ shape: RoundedRectangle) -> some View {
        // Under the pointer the rainbow follows the tilt; otherwise it drifts.
        let shift = (sweep ? -0.8 : 0) + Double(tilt.x + tilt.y) * 1.6
        return ZStack {
            LinearGradient(colors: [.clear, .pink.opacity(0.35), .yellow.opacity(0.35), .green.opacity(0.3),
                                    .cyan.opacity(0.35), .purple.opacity(0.35), .clear],
                           startPoint: UnitPoint(x: 0.6 + shift, y: 0), endPoint: UnitPoint(x: 1.4 + shift, y: 1))
                .blendMode(.overlay)
            // The idle white sweep yields to the pointer's own light while tilted.
            LinearGradient(colors: [.clear, .white.opacity(0.26 * Double(1 - min(1, (abs(tilt.x) + abs(tilt.y)) * 1.6))), .clear],
                           startPoint: UnitPoint(x: sweep ? 0 : 0.8, y: 0), endPoint: UnitPoint(x: sweep ? 0.4 : 1.2, y: 1))
                .blendMode(.plusLighter)
        }
        .clipShape(shape)
        .allowsHitTesting(false)
    }

    private var sparkles: some View {
        GeometryReader { geo in
            ForEach(Array(Self.spots.enumerated()), id: \.offset) { _, p in
                Image(systemName: "sparkle")
                    .font(.system(size: 6 * p.z * k, weight: .bold))
                    .foregroundStyle(.white.opacity(sweep ? 0.95 : 0.35))
                    .position(x: geo.size.width * p.x, y: geo.size.height * p.y)
            }
        }
        .allowsHitTesting(false)
    }

    private static let spots: [(x: CGFloat, y: CGFloat, z: CGFloat)] =
        [(0.16, 0.24, 1.2), (0.84, 0.18, 0.8), (0.86, 0.55, 1.3), (0.14, 0.62, 0.9), (0.6, 0.3, 0.7)]

    private func locked(_ shape: RoundedRectangle) -> some View {
        ZStack {
            shape.fill(Color.primary.opacity(0.06))
            SeriesPattern(series: def.series).stroke(Color.primary.opacity(0.06), lineWidth: 0.7).clipShape(shape).padding(6 * k)
            shape.strokeBorder(style: StrokeStyle(lineWidth: 1, dash: [3, 3])).foregroundStyle(Color.primary.opacity(0.2))
            VStack(spacing: 4 * k) {
                Image(systemName: def.symbol).font(.system(size: 16 * k, weight: .semibold)).foregroundStyle(Color.primary.opacity(0.15))
                Text("?").font(.system(size: 13 * k, weight: .black, design: .rounded)).foregroundStyle(Color.primary.opacity(0.25))
                Text(def.rarity.label).font(.system(size: 7.5 * k, weight: .semibold)).foregroundStyle(def.rarity.glow.opacity(0.7))
            }
        }
    }
}

/// Line art behind a card's emblem, one motif per series.
struct SeriesPattern: Shape {
    let series: String

    func path(in rect: CGRect) -> Path {
        var p = Path()
        let c = CGPoint(x: rect.midX, y: rect.midY)
        let r = max(rect.width, rect.height)
        switch series {
        case "five_hour":
            // Clock face: rings and five hour ticks.
            for f in stride(from: 0.18, through: 0.7, by: 0.13) {
                p.addEllipse(in: CGRect(x: c.x - r * f, y: c.y - r * f, width: r * f * 2, height: r * f * 2))
            }
            for i in 0..<12 {
                let a = Double(i) / 12 * 2 * .pi
                p.move(to: CGPoint(x: c.x + r * 0.42 * CGFloat(sin(a)), y: c.y - r * 0.42 * CGFloat(cos(a))))
                p.addLine(to: CGPoint(x: c.x + r * (i % 3 == 0 ? 0.52 : 0.47) * CGFloat(sin(a)), y: c.y - r * (i % 3 == 0 ? 0.52 : 0.47) * CGFloat(cos(a))))
            }
        case "seven_day":
            // Seven rising bars.
            let w = rect.width / 9
            for i in 0..<7 {
                let h = rect.height * (0.25 + 0.08 * CGFloat(i))
                p.addRect(CGRect(x: rect.minX + w * CGFloat(i + 1), y: rect.maxY - h, width: w * 0.55, height: h))
            }
        case "reset_card":
            // Ticket perforations and diagonal hatching.
            for y in stride(from: rect.minY, to: rect.maxY, by: 5) {
                p.addEllipse(in: CGRect(x: rect.minX + 2, y: y, width: 2, height: 2))
                p.addEllipse(in: CGRect(x: rect.maxX - 4, y: y, width: 2, height: 2))
            }
            for x in stride(from: -rect.height, to: rect.width, by: 7) {
                p.move(to: CGPoint(x: rect.minX + x, y: rect.maxY))
                p.addLine(to: CGPoint(x: rect.minX + x + rect.height, y: rect.minY))
            }
        case "checkin":
            // Calendar grid.
            let cols = 7, rows = 5
            for i in 0...cols { let x = rect.minX + rect.width * CGFloat(i) / CGFloat(cols); p.move(to: CGPoint(x: x, y: rect.minY)); p.addLine(to: CGPoint(x: x, y: rect.maxY)) }
            for j in 0...rows { let y = rect.minY + rect.height * CGFloat(j) / CGFloat(rows); p.move(to: CGPoint(x: rect.minX, y: y)); p.addLine(to: CGPoint(x: rect.maxX, y: y)) }
        default:
            // Starburst.
            for i in 0..<18 {
                let a = Double(i) / 18 * 2 * .pi
                p.move(to: c)
                p.addLine(to: CGPoint(x: c.x + r * CGFloat(sin(a)), y: c.y - r * CGFloat(cos(a))))
            }
        }
        return p
    }
}

private struct Gem: View {
    let color: Color

    var body: some View {
        Rectangle()
            .fill(LinearGradient(colors: [.white, color, color.opacity(0.6)], startPoint: .topLeading, endPoint: .bottomTrailing))
            .rotationEffect(.degrees(45))
            .scaleEffect(0.75)
            .shadow(color: color, radius: 1.5)
    }
}
