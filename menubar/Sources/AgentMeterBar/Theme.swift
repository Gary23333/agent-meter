import AppKit
import SwiftUI

/// Seven panel styles, from the plainest to the loudest. Components read the
/// theme from the environment and pick their own look; data views only ask
/// for tokens (tint, number font, glow) so the layout stays identical.
enum ThemeTextRole {
    case primary, secondary, tertiary
}

enum PanelTheme: String, CaseIterable, Identifiable {
    case minimal, native, porcelain, aurora, titanium, neon, prism
    var id: String { rawValue }

    var label: String {
        switch self {
        case .minimal: return "极简"
        case .native: return "原生"
        case .porcelain: return "瓷白"
        case .aurora: return "极光"
        case .titanium: return "钛影"
        case .neon: return "霓虹"
        case .prism: return "棱镜"
        }
    }

    var blurb: String {
        switch self {
        case .minimal: return "黑白排版，无卡片无阴影"
        case .native: return "macOS 系统风格，实色卡片"
        case .porcelain: return "柔和陶瓷，克制的浅浮雕"
        case .aurora: return "毛玻璃与彩色光斑"
        case .titanium: return "拉丝金属，深色机械层次"
        case .neon: return "赛博霓虹，动态光效"
        case .prism: return "全息晶体，炫彩空间光影"
        }
    }

    var symbol: String {
        switch self {
        case .minimal: return "circle"
        case .native: return "macwindow"
        case .porcelain: return "cube"
        case .aurora: return "sparkles"
        case .titanium: return "cube.fill"
        case .neon: return "bolt.fill"
        case .prism: return "diamond.fill"
        }
    }

    var is3D: Bool { self == .porcelain || self == .titanium || self == .prism }
    var isLuminous: Bool { self == .neon || self == .prism }
    var forcedScheme: ColorScheme? {
        if self == .porcelain { return .light }
        return isLuminous || self == .titanium ? .dark : nil
    }
    var numberDesign: Font.Design {
        switch self {
        case .minimal, .native: return .default
        case .porcelain, .aurora, .titanium: return .rounded
        case .neon, .prism: return .monospaced
        }
    }
    var glow: CGFloat {
        switch self {
        case .minimal, .native: return 0
        case .porcelain: return 0.35
        case .aurora, .titanium: return 1
        case .neon, .prism: return 1.7
        }
    }

    /// Explicit text roles keep secondary information readable on translucent,
    /// metallic and luminous surfaces instead of relying on low-contrast system
    /// tertiary labels. Primary data is always neutral; colour lives in charts.
    func textColor(_ role: ThemeTextRole, scheme: ColorScheme) -> Color {
        switch self {
        case .porcelain:
            switch role {
            case .primary: return Color(red: 0.09, green: 0.13, blue: 0.20)
            case .secondary: return Color(red: 0.29, green: 0.35, blue: 0.44)
            case .tertiary: return Color(red: 0.40, green: 0.46, blue: 0.55)
            }
        case .titanium:
            switch role {
            case .primary: return Color(red: 0.95, green: 0.97, blue: 0.99)
            case .secondary: return Color(red: 0.73, green: 0.79, blue: 0.85)
            case .tertiary: return Color(red: 0.58, green: 0.65, blue: 0.73)
            }
        case .neon, .prism:
            switch role {
            case .primary: return Color(red: 0.94, green: 0.97, blue: 1.0)
            case .secondary: return Color(red: 0.70, green: 0.77, blue: 0.87)
            case .tertiary: return Color(red: 0.54, green: 0.61, blue: 0.72)
            }
        case .aurora:
            let base = scheme == .dark ? Color.white : Color(red: 0.10, green: 0.12, blue: 0.22)
            return base.opacity(role == .primary ? 0.96 : role == .secondary ? 0.76 : 0.62)
        case .minimal, .native:
            return Color.primary.opacity(role == .primary ? 1 : role == .secondary ? 0.74 : 0.58)
        }
    }

    func font(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: self == .neon ? .monospaced : .default)
    }

    func number(_ size: CGFloat) -> Font {
        switch self {
        case .minimal: return .system(size: size, weight: .medium, design: .default)
        case .native: return .system(size: size, weight: .semibold, design: .default)
        case .porcelain, .aurora, .titanium: return .system(size: size, weight: .bold, design: .rounded)
        case .neon, .prism: return .system(size: size * 0.94, weight: .bold, design: .monospaced)
        }
    }

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
        case .porcelain, .aurora, .titanium:
            return healthTint(remaining)
        case .neon, .prism:
            if remaining < 20 { return Neon.red }
            if remaining < 50 { return Neon.yellow }
            return Neon.lime
        }
    }

    func healthText(_ remaining: Double, scheme: ColorScheme) -> Color {
        if self == .porcelain || (self == .aurora && scheme == .light) {
            if remaining < 20 { return Color(red: 0.72, green: 0.12, blue: 0.22) }
            if remaining < 50 { return Color(red: 0.65, green: 0.34, blue: 0.02) }
            return Color(red: 0.04, green: 0.43, blue: 0.32)
        }
        return health(remaining)
    }

    func healthAccent(_ remaining: Double) -> Color {
        switch self {
        case .minimal, .native: return health(remaining)
        case .porcelain, .aurora, .titanium: return healthTintAccent(remaining)
        case .neon, .prism:
            if remaining < 20 { return Neon.magenta }
            if remaining < 50 { return Neon.orange }
            return Neon.cyan
        }
    }

    func tint(_ color: Color) -> Color {
        self == .minimal ? (color == .secondary ? .secondary : .primary) : color
    }

    func figure(_ colors: [Color]) -> AnyShapeStyle {
        switch self {
        case .minimal: return AnyShapeStyle(Color.primary)
        case .native: return AnyShapeStyle(colors.first ?? .primary)
        case .porcelain:
            return AnyShapeStyle(LinearGradient(colors: [Color(red: 0.24, green: 0.35, blue: 0.55), Color(red: 0.54, green: 0.42, blue: 0.66)], startPoint: .top, endPoint: .bottom))
        case .aurora: return AnyShapeStyle(LinearGradient(colors: colors, startPoint: .leading, endPoint: .trailing))
        case .titanium:
            return AnyShapeStyle(LinearGradient(colors: [.white, Color(red: 0.48, green: 0.68, blue: 0.82)], startPoint: .top, endPoint: .bottom))
        case .neon: return AnyShapeStyle(LinearGradient(colors: [Neon.cyan, Neon.magenta], startPoint: .leading, endPoint: .trailing))
        case .prism:
            return AnyShapeStyle(LinearGradient(colors: [Neon.cyan, Color(red: 0.62, green: 0.46, blue: 1), Neon.magenta, Neon.yellow], startPoint: .topLeading, endPoint: .bottomTrailing))
        }
    }

    func series(_ color: Color, index: Int) -> Color {
        switch self {
        case .minimal: return Color.primary.opacity([0.85, 0.55, 0.32, 0.16][index % 4])
        case .neon, .prism: return [Neon.cyan, Neon.magenta, Neon.lime, Neon.yellow][index % 4]
        case .titanium: return color
        default: return color
        }
    }

    var accent: [Color] {
        switch self {
        case .minimal: return [.primary, .primary]
        case .native: return [.accentColor, .accentColor]
        case .porcelain: return [Color(red: 0.30, green: 0.39, blue: 0.58), Color(red: 0.48, green: 0.36, blue: 0.54)]
        case .aurora: return [Color(red: 0.32, green: 0.36, blue: 0.88), Color(red: 0.58, green: 0.28, blue: 0.84)]
        case .titanium: return [Color(red: 0.72, green: 0.81, blue: 0.88), Color(red: 0.44, green: 0.56, blue: 0.66)]
        case .neon: return [Neon.magenta, Neon.cyan]
        case .prism: return [Neon.cyan, Neon.magenta]
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
    func themeForeground(_ role: ThemeTextRole = .primary) -> some View {
        modifier(ThemeForeground(role: role))
    }
}

private struct ThemeForeground: ViewModifier {
    let role: ThemeTextRole
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme

    func body(content: Content) -> some View {
        content.foregroundStyle(theme.textColor(role, scheme: scheme))
    }
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
        case .porcelain, .titanium, .prism: DimensionalBackground(theme: theme)
        case .aurora: AuroraBackground()
        case .neon: NeonBackground()
        }
    }
}

/// Static, code-rendered depth: radial-lit spheres, a horizon and soft contact
/// shadows. It is deterministic enough for ImageRenderer and cheap in a panel.
struct DimensionalBackground: View {
    let theme: PanelTheme

    var body: some View {
        ZStack {
            base
            if theme == .porcelain {
                orb(Color(red: 0.72, green: 0.81, blue: 0.94).opacity(0.50), x: -170, y: -250, size: 250)
                orb(Color(red: 0.91, green: 0.76, blue: 0.79).opacity(0.38), x: 180, y: 210, size: 210)
            } else if theme == .titanium {
                orb(Color(red: 0.20, green: 0.31, blue: 0.41).opacity(0.42), x: 180, y: -260, size: 260)
                orb(Color(red: 0.08, green: 0.12, blue: 0.17).opacity(0.70), x: -180, y: 250, size: 230)
            } else {
                orb(Neon.cyan.opacity(0.30), x: -175, y: -235, size: 250)
                orb(Neon.magenta.opacity(0.25), x: 180, y: 70, size: 240)
                orb(Neon.violet.opacity(0.28), x: -120, y: 300, size: 220)
            }
            VStack {
                Spacer()
                Ellipse().fill(Color.black.opacity(theme == .porcelain ? 0.045 : 0.16))
                    .frame(width: 340, height: 54).blur(radius: 24).offset(y: 30)
            }
        }
        .clipped()
    }

    private var base: some View {
        switch theme {
        case .porcelain:
            return AnyView(LinearGradient(colors: [Color(red: 0.97, green: 0.98, blue: 0.995), Color(red: 0.89, green: 0.92, blue: 0.96)], startPoint: .topLeading, endPoint: .bottomTrailing))
        case .titanium:
            return AnyView(LinearGradient(colors: [Color(red: 0.045, green: 0.06, blue: 0.08), Color(red: 0.085, green: 0.11, blue: 0.14)], startPoint: .topLeading, endPoint: .bottomTrailing))
        default:
            return AnyView(ZStack {
                Color(red: 0.025, green: 0.025, blue: 0.065)
                AngularGradient(colors: [Neon.cyan, Neon.violet, Neon.magenta, Neon.cyan], center: .center)
                    .opacity(0.10).blur(radius: 55)
            })
        }
    }

    private func orb(_ color: Color, x: CGFloat, y: CGFloat, size: CGFloat) -> some View {
        Circle()
            .fill(RadialGradient(colors: [Color.white.opacity(theme == .porcelain ? 0.64 : 0.24), color, color.opacity(0.06)],
                                 center: .init(x: 0.32, y: 0.25), startRadius: 2, endRadius: size * 0.55))
            .frame(width: size, height: size)
            .shadow(color: color.opacity(0.18), radius: 28, x: 8, y: 18)
            .offset(x: x, y: y)
            .allowsHitTesting(false)
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
            ctx.stroke(floor, with: .linearGradient(Gradient(colors: [Neon.magenta.opacity(0), Neon.magenta.opacity(0.20)]),
                                                     startPoint: CGPoint(x: 0, y: horizon), endPoint: CGPoint(x: 0, y: size.height)),
                       lineWidth: 0.6)
            var crt = Path()
            var line: CGFloat = 0
            while line < size.height {
                crt.addRect(CGRect(x: 0, y: line, width: size.width, height: 1))
                line += 4
            }
            ctx.fill(crt, with: .color(.black.opacity(0.10)))
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
        case .neon, .prism:
            Rectangle()
                .fill(LinearGradient(colors: [Neon.magenta.opacity(0), Neon.magenta.opacity(0.32), Neon.cyan.opacity(0.36), Neon.cyan.opacity(0)], startPoint: .leading, endPoint: .trailing))
                .frame(height: 0.7)
        case .minimal:
            Rectangle().fill(Color.primary.opacity(0.12)).frame(height: 0.5)
        case .porcelain:
            Rectangle().fill(Color(red: 0.20, green: 0.27, blue: 0.38).opacity(0.10)).frame(height: 0.6)
        default:
            Rectangle().fill(Color.primary.opacity(0.09)).frame(height: 0.5)
        }
    }
}

extension View {
    @ViewBuilder func themeGlow(_ color: Color, radius: CGFloat, y: CGFloat = 0, theme: PanelTheme) -> some View {
        switch theme {
        case .minimal, .native: self
        case .porcelain: shadow(color: color.opacity(0.22), radius: radius * 0.6, y: y + 1)
        case .aurora, .titanium: shadow(color: color.opacity(0.55), radius: radius * 0.75, y: y)
        case .neon, .prism: shadow(color: color.opacity(0.60), radius: radius * 0.55, y: y)
        }
    }
}
