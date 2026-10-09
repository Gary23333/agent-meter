import AppKit
import SwiftUI

/// Four panel styles, from the plainest to the loudest. Components read the
/// theme from the environment and pick their own look; data views only ask
/// for tokens (tint, number font, glow) so the layout stays identical.
enum PanelTheme: String, CaseIterable, Identifiable {
    case minimal, native, aurora, neon
    var id: String { rawValue }

    var label: String {
        switch self {
        case .minimal: return "极简"
        case .native: return "原生"
        case .aurora: return "极光"
        case .neon: return "霓虹"
        }
    }

    var blurb: String {
        switch self {
        case .minimal: return "黑白排版，无卡片无阴影"
        case .native: return "macOS 系统风格，实色卡片"
        case .aurora: return "毛玻璃与彩色光斑"
        case .neon: return "赛博霓虹，动态光效"
        }
    }

    var symbol: String {
        switch self {
        case .minimal: return "circle"
        case .native: return "macwindow"
        case .aurora: return "sparkles"
        case .neon: return "bolt.fill"
        }
    }

    /// Neon is designed for a dark room; the other three follow the system.
    var forcedScheme: ColorScheme? { self == .neon ? .dark : nil }

    /// Multiplier for coloured shadows.
    var glow: CGFloat {
        switch self {
        case .minimal, .native: return 0
        case .aurora: return 1
        case .neon: return 1.7
        }
    }

    var numberDesign: Font.Design {
        switch self {
        case .minimal, .native: return .default
        case .aurora: return .rounded
        case .neon: return .monospaced
        }
    }

    /// Font for headline figures (token totals, ring percentages).
    func number(_ size: CGFloat) -> Font {
        switch self {
        case .minimal: return .system(size: size, weight: .light, design: .default)
        case .native: return .system(size: size, weight: .semibold, design: .default)
        case .aurora: return .system(size: size, weight: .heavy, design: .rounded)
        case .neon: return .system(size: size * 0.92, weight: .bold, design: .monospaced)
        }
    }

    // MARK: Colour

    func health(_ remaining: Double) -> Color {
        switch self {
        case .minimal:
            if remaining < 20 { return .red }
            if remaining < 50 { return .orange }
            return .primary
        case .native:
            if remaining < 20 { return Color(nsColor: .systemRed) }
            if remaining < 50 { return Color(nsColor: .systemOrange) }
            return Color(nsColor: .systemGreen)
        case .aurora:
            return healthTint(remaining)
        case .neon:
            if remaining < 20 { return Neon.red }
            if remaining < 50 { return Neon.yellow }
            return Neon.lime
        }
    }

    func healthAccent(_ remaining: Double) -> Color {
        switch self {
        case .minimal, .native: return health(remaining)
        case .aurora: return healthTintAccent(remaining)
        case .neon:
            if remaining < 20 { return Neon.magenta }
            if remaining < 50 { return Neon.orange }
            return Neon.cyan
        }
    }

    /// Brand / series colour as this theme shows it (minimal drops colour).
    func tint(_ color: Color) -> Color {
        self == .minimal ? (color == .secondary ? .secondary : .primary) : color
    }

    /// Fill for a headline figure that would otherwise be a gradient.
    func figure(_ colors: [Color]) -> AnyShapeStyle {
        switch self {
        case .minimal: return AnyShapeStyle(Color.primary)
        case .native: return AnyShapeStyle(colors.first ?? .primary)
        case .aurora: return AnyShapeStyle(LinearGradient(colors: colors, startPoint: .leading, endPoint: .trailing))
        case .neon: return AnyShapeStyle(LinearGradient(colors: [Neon.cyan, Neon.magenta], startPoint: .leading, endPoint: .trailing))
        }
    }

    /// Colour for the n-th part of a breakdown (donut, legend).
    func series(_ color: Color, index: Int) -> Color {
        switch self {
        case .minimal: return Color.primary.opacity([0.85, 0.55, 0.32, 0.16][index % 4])
        case .neon: return [Neon.cyan, Neon.magenta, Neon.lime, Neon.yellow][index % 4]
        default: return color
        }
    }

    /// Main accent pair for highlights (selected tab, logo).
    var accent: [Color] {
        switch self {
        case .minimal: return [.primary, .primary]
        case .native: return [.accentColor, .accentColor]
        case .aurora: return [Color(red: 0.40, green: 0.45, blue: 1.0), Color(red: 0.70, green: 0.36, blue: 0.98)]
        case .neon: return [Neon.magenta, Neon.cyan]
        }
    }
}

enum Neon {
    static let magenta = Color(red: 1.0, green: 0.16, blue: 0.82)
    static let cyan = Color(red: 0.0, green: 0.94, blue: 1.0)
    static let lime = Color(red: 0.30, green: 1.0, blue: 0.24)
    static let yellow = Color(red: 1.0, green: 0.92, blue: 0.10)
    static let orange = Color(red: 1.0, green: 0.45, blue: 0.05)
    static let red = Color(red: 1.0, green: 0.12, blue: 0.40)
    static let violet = Color(red: 0.55, green: 0.20, blue: 1.0)
    static let ink = Color(red: 0.03, green: 0.01, blue: 0.08)
    static let rim = AngularGradient(colors: [magenta, violet, cyan, lime, yellow, magenta], center: .center)
}

private struct PanelThemeKey: EnvironmentKey {
    static let defaultValue = PanelTheme.aurora
}

extension EnvironmentValues {
    var panelTheme: PanelTheme {
        get { self[PanelThemeKey.self] }
        set { self[PanelThemeKey.self] = newValue }
    }
}

extension View {
    /// Applies a theme to a whole window: tokens, forced appearance, backdrop.
    func themedRoot(_ theme: PanelTheme) -> some View { modifier(ThemedRoot(theme: theme)) }
}

private struct ThemedRoot: ViewModifier {
    let theme: PanelTheme
    @Environment(\.colorScheme) private var scheme

    func body(content: Content) -> some View {
        content
            .background(ThemeBackground())
            .tint(theme.accent[0])
            .environment(\.panelTheme, theme)
            .environment(\.colorScheme, theme.forcedScheme ?? scheme)
    }
}

// MARK: Backgrounds

struct ThemeBackground: View {
    @Environment(\.panelTheme) private var theme

    var body: some View {
        switch theme {
        case .minimal: Color(nsColor: .textBackgroundColor)
        case .native: Color(nsColor: .windowBackgroundColor)
        case .aurora: AuroraBackground()
        case .neon: NeonBackground()
        }
    }
}

/// Dark violet base, a slowly turning conic glow, a synthwave floor grid and
/// a scan band. Motion runs in Core Animation (render server), so the open
/// panel costs about the same CPU as the static themes.
struct NeonBackground: View {
    var body: some View {
        ZStack {
            Neon.ink
            if PanelView.expandForPreview {
                AngularGradient(colors: [Neon.magenta, Neon.violet, Neon.cyan, Neon.magenta], center: .center)
                    .opacity(0.22)
                    .blur(radius: 40)
            } else {
                NeonMotionLayer()
            }
            RadialGradient(colors: [.clear, Neon.ink.opacity(0.85)], center: .center, startRadius: 120, endRadius: 520)
            NeonGrid()
        }
        .clipped()
    }
}

/// Perspective floor plus CRT lines, drawn once.
private struct NeonGrid: View {
    var body: some View {
        Canvas { ctx, size in
            // Horizon about two thirds down; lines fan out toward the viewer.
            let horizon = size.height * 0.62
            let vanishing = CGPoint(x: size.width / 2, y: horizon)
            var floor = Path()
            for i in -12...12 {
                floor.move(to: vanishing)
                floor.addLine(to: CGPoint(x: size.width / 2 + CGFloat(i) * size.width / 7, y: size.height))
            }
            var y = horizon
            var step: CGFloat = 4
            while y < size.height {
                floor.move(to: CGPoint(x: 0, y: y))
                floor.addLine(to: CGPoint(x: size.width, y: y))
                y += step
                step *= 1.35
            }
            ctx.stroke(floor, with: .linearGradient(Gradient(colors: [Neon.magenta.opacity(0), Neon.magenta.opacity(0.32)]),
                                                     startPoint: CGPoint(x: 0, y: horizon), endPoint: CGPoint(x: 0, y: size.height)),
                       lineWidth: 0.7)
            var crt = Path()
            var line: CGFloat = 0
            while line < size.height {
                crt.addRect(CGRect(x: 0, y: line, width: size.width, height: 1))
                line += 3
            }
            ctx.fill(crt, with: .color(.black.opacity(0.18)))
        }
        .allowsHitTesting(false)
        .drawingGroup()
    }
}

/// Core Animation layers: a rotating conic gradient and a sweeping scan band.
private struct NeonMotionLayer: NSViewRepresentable {
    func makeNSView(context: Context) -> NeonMotionView { NeonMotionView() }
    func updateNSView(_ view: NeonMotionView, context: Context) {}
}

final class NeonMotionView: NSView {
    private let conic = CAGradientLayer()
    private let band = CAGradientLayer()
    private var laidOut = CGSize.zero

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.masksToBounds = true

        conic.type = .conic
        conic.startPoint = CGPoint(x: 0.5, y: 0.5)
        conic.endPoint = CGPoint(x: 0.5, y: 0)
        conic.colors = [NSColor(Neon.magenta), NSColor(Neon.violet), NSColor(Neon.cyan),
                        NSColor(Neon.lime), NSColor(Neon.magenta)].map { $0.withAlphaComponent(0.5).cgColor }
        conic.opacity = 0.32
        layer?.addSublayer(conic)

        band.colors = [NSColor(Neon.cyan).withAlphaComponent(0).cgColor,
                       NSColor(Neon.cyan).withAlphaComponent(0.10).cgColor,
                       NSColor(Neon.cyan).withAlphaComponent(0).cgColor]
        band.startPoint = CGPoint(x: 0.5, y: 0)
        band.endPoint = CGPoint(x: 0.5, y: 1)
        layer?.addSublayer(band)
    }

    required init?(coder: NSCoder) { fatalError() }

    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    override func layout() {
        super.layout()
        guard bounds.size != laidOut, bounds.width > 0 else { return }
        laidOut = bounds.size
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        let side = hypot(bounds.width, bounds.height) * 1.1
        conic.bounds = CGRect(x: 0, y: 0, width: side, height: side)
        conic.position = CGPoint(x: bounds.midX, y: bounds.midY)
        let bandHeight: CGFloat = 90
        band.bounds = CGRect(x: 0, y: 0, width: bounds.width, height: bandHeight)
        band.position = CGPoint(x: bounds.midX, y: bounds.maxY + bandHeight)
        CATransaction.commit()

        if conic.animation(forKey: "spin") == nil {
            let spin = CABasicAnimation(keyPath: "transform.rotation.z")
            spin.fromValue = 0
            spin.toValue = -Double.pi * 2
            spin.duration = 28
            spin.repeatCount = .infinity
            conic.add(spin, forKey: "spin")
        }
        let sweep = CABasicAnimation(keyPath: "position.y")
        sweep.fromValue = bounds.maxY + bandHeight
        sweep.toValue = -bandHeight
        sweep.duration = 5.5
        sweep.repeatCount = .infinity
        sweep.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        band.add(sweep, forKey: "sweep")
    }
}

// MARK: Shapes

/// HUD-style L brackets at the four corners.
struct CornerBrackets: Shape {
    var length: CGFloat = 9

    func path(in r: CGRect) -> Path {
        var p = Path()
        let l = min(length, r.width / 3, r.height / 3)
        p.move(to: CGPoint(x: r.minX, y: r.minY + l)); p.addLine(to: CGPoint(x: r.minX, y: r.minY)); p.addLine(to: CGPoint(x: r.minX + l, y: r.minY))
        p.move(to: CGPoint(x: r.maxX - l, y: r.minY)); p.addLine(to: CGPoint(x: r.maxX, y: r.minY)); p.addLine(to: CGPoint(x: r.maxX, y: r.minY + l))
        p.move(to: CGPoint(x: r.maxX, y: r.maxY - l)); p.addLine(to: CGPoint(x: r.maxX, y: r.maxY)); p.addLine(to: CGPoint(x: r.maxX - l, y: r.maxY))
        p.move(to: CGPoint(x: r.minX + l, y: r.maxY)); p.addLine(to: CGPoint(x: r.minX, y: r.maxY)); p.addLine(to: CGPoint(x: r.minX, y: r.maxY - l))
        return p
    }
}

/// Hairline between header, content and footer.
struct ThemeDivider: View {
    @Environment(\.panelTheme) private var theme

    var body: some View {
        switch theme {
        case .neon:
            Rectangle()
                .fill(LinearGradient(colors: [Neon.magenta.opacity(0), Neon.magenta, Neon.cyan, Neon.cyan.opacity(0)],
                                     startPoint: .leading, endPoint: .trailing))
                .frame(height: 1)
                .shadow(color: Neon.magenta.opacity(0.8), radius: 4)
        case .minimal:
            Rectangle().fill(Color.primary.opacity(0.12)).frame(height: 0.5)
        default:
            Rectangle().fill(Color.primary.opacity(0.08)).frame(height: 0.5)
        }
    }
}

extension View {
    /// Coloured shadow scaled by the theme's glow (none for flat themes).
    /// Neon stacks a tight core glow under a wide halo.
    @ViewBuilder func themeGlow(_ color: Color, radius: CGFloat, y: CGFloat = 0, theme: PanelTheme) -> some View {
        switch theme {
        case .minimal, .native: self
        case .aurora: shadow(color: color, radius: radius, y: y)
        case .neon: shadow(color: color, radius: radius * 0.6, y: y).shadow(color: color.opacity(0.7), radius: radius * 1.8)
        }
    }
}
