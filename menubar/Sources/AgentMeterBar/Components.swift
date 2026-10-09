import SwiftUI

func healthTint(_ remaining: Double) -> Color {
    if remaining < 20 { return Color(red: 1.0, green: 0.30, blue: 0.36) }
    if remaining < 50 { return Color(red: 1.0, green: 0.70, blue: 0.20) }
    return Color(red: 0.20, green: 0.88, blue: 0.56)
}

/// Second stop for gauge gradients: the same mood, shifted toward cyan/pink.
func healthTintAccent(_ remaining: Double) -> Color {
    if remaining < 20 { return Color(red: 1.0, green: 0.42, blue: 0.75) }
    if remaining < 50 { return Color(red: 1.0, green: 0.48, blue: 0.30) }
    return Color(red: 0.18, green: 0.80, blue: 0.98)
}

// MARK: Background

/// Colour blobs behind the glass cards. Static on purpose: animating a
/// 60pt blur redraws every frame (~20% CPU while the panel is open).
struct AuroraBackground: View {
    @Environment(\.colorScheme) private var scheme
    private let drift = true

    var body: some View {
        let strength = scheme == .dark ? 0.55 : 0.28
        ZStack {
            (scheme == .dark ? Color(red: 0.05, green: 0.06, blue: 0.11) : Color(red: 0.96, green: 0.97, blue: 1.0))
            blob(Color(red: 0.36, green: 0.42, blue: 1.0), x: drift ? -110 : -60, y: drift ? -230 : -170, size: 320)
            blob(Color(red: 0.78, green: 0.32, blue: 0.98), x: drift ? 150 : 110, y: drift ? -60 : -120, size: 280)
            blob(Color(red: 0.10, green: 0.86, blue: 0.80), x: drift ? -80 : -140, y: drift ? 260 : 200, size: 300)
            blob(Color(red: 1.0, green: 0.45, blue: 0.55), x: drift ? 160 : 120, y: drift ? 320 : 380, size: 240)
        }
        .opacity(strength / 0.55)
        .blur(radius: 60)
        .clipped()
        .drawingGroup()
    }

    private func blob(_ color: Color, x: CGFloat, y: CGFloat, size: CGFloat) -> some View {
        Circle().fill(color.opacity(0.55)).frame(width: size, height: size).offset(x: x, y: y)
    }
}


// MARK: Cards

struct Card<Content: View>: View {
    var tint: Color? = nil
    @ViewBuilder var content: Content
    @Environment(\.colorScheme) private var scheme
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let stack = VStack(alignment: .leading, spacing: 10) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
        switch theme {
        case .minimal:
            // No container at all: content separated by a hairline below.
            stack
                .padding(.horizontal, 2)
                .padding(.vertical, 10)
                .overlay(alignment: .bottom) { Rectangle().fill(Color.primary.opacity(0.1)).frame(height: 0.5) }
        case .native:
            stack
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(Color(nsColor: .separatorColor), lineWidth: 0.5))
                .shadow(color: .black.opacity(scheme == .dark ? 0.25 : 0.05), radius: 2, y: 1)
        case .aurora:
            aurora(stack)
        case .neon:
            neon(stack)
        }
    }

    private func aurora(_ stack: some View) -> some View {
        let edge = tint ?? Color.white
        return stack
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(.ultraThinMaterial)
                    .overlay(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .fill(LinearGradient(colors: [edge.opacity(tint == nil ? 0.04 : 0.12), .clear],
                                                 startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(LinearGradient(colors: [edge.opacity(tint == nil ? 0.25 : 0.55),
                                                          Color.white.opacity(scheme == .dark ? 0.06 : 0.3),
                                                          edge.opacity(0.12)],
                                                 startPoint: .topLeading, endPoint: .bottomTrailing),
                                  lineWidth: 0.8)
            )
            .shadow(color: (tint ?? .black).opacity(scheme == .dark ? 0.28 : 0.12), radius: 12, y: 4)
    }

    /// Dark glass slab, rainbow rim, HUD corner brackets in the brand colour.
    private func neon(_ stack: some View) -> some View {
        let edge = tint ?? Neon.cyan
        let shape = RoundedRectangle(cornerRadius: 5, style: .continuous)
        return stack
            .padding(12)
            .background(
                shape.fill(Color.black.opacity(0.55))
                    .overlay(shape.fill(LinearGradient(colors: [edge.opacity(0.22), .clear, Neon.magenta.opacity(0.08)],
                                                       startPoint: .topLeading, endPoint: .bottomTrailing)))
            )
            .overlay(shape.strokeBorder(Neon.rim, lineWidth: 1).opacity(0.85))
            .overlay(CornerBrackets(length: 10).stroke(edge, lineWidth: 2).padding(-2.5))
            .shadow(color: edge.opacity(0.45), radius: 10)
            .shadow(color: Neon.magenta.opacity(0.25), radius: 18, y: 6)
    }
}

/// The real app icon when installed, otherwise a gradient tile with a symbol.
struct BrandBadge: View {
    let brand: Catalog.Brand
    var size: CGFloat = 26
    var icon: NSImage? = nil
    @Environment(\.panelTheme) private var theme

    var body: some View {
        Group {
            if let icon {
                Image(nsImage: icon).resizable().interpolation(.high).frame(width: size, height: size)
            } else {
                RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
                    .fill(theme == .native
                          ? AnyShapeStyle(brand.tint)
                          : AnyShapeStyle(LinearGradient(colors: [brand.tint, brand.tint.opacity(0.6)], startPoint: .topLeading, endPoint: .bottomTrailing)))
                    .frame(width: size, height: size)
                    .overlay(Image(systemName: brand.symbol).font(.system(size: size * 0.46, weight: .semibold)).foregroundStyle(.white))
            }
        }
        .saturation(theme == .minimal ? 0 : 1)
        .themeGlow(brand.tint.opacity(0.45), radius: 5, y: 1, theme: theme)
    }
}

struct StatusPill: View {
    let status: String
    var text: String? = nil
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let color = Catalog.statusColor(status)
        let label = HStack(spacing: 4) {
            Circle().fill(color).frame(width: 5, height: 5).themeGlow(color, radius: 2, theme: theme)
            Text(text ?? Catalog.statusLabel(status))
                .font(.system(size: 10, weight: theme == .minimal ? .regular : .semibold, design: theme == .neon ? .monospaced : .default))
        }
        .foregroundStyle(color)
        if theme == .minimal {
            label
        } else {
            label
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(Capsule().fill(color.opacity(0.13)))
                .overlay(Capsule().strokeBorder(color.opacity(theme == .neon ? 0.8 : 0.3), lineWidth: theme == .neon ? 0.8 : 0.5))
        }
    }
}

// MARK: Gauges

struct Meter: View {
    let fraction: Double
    let tint: Color
    var accent: Color? = nil
    var height: CGFloat = 6
    @State private var shown = 0.0
    @Environment(\.panelTheme) private var theme

    var body: some View {
        GeometryReader { g in
            let width = g.size.width * min(max(shown, 0), 1)
            switch theme {
            case .minimal:
                ZStack(alignment: .leading) {
                    Rectangle().fill(Color.primary.opacity(0.08))
                    Rectangle().fill(tint).frame(width: width)
                }
                .frame(height: 2)
                .frame(maxHeight: .infinity, alignment: .bottom)
            case .native:
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.1))
                    Capsule().fill(tint).frame(width: max(height, width))
                }
            case .aurora:
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.08))
                    Capsule()
                        .fill(LinearGradient(colors: [accent ?? tint.opacity(0.7), tint], startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(height, width))
                        .shadow(color: tint.opacity(0.6), radius: 4)
                }
            case .neon:
                ledBar(size: g.size)
            }
        }
        .frame(height: theme == .minimal ? max(4, height - 2) : height)
        .onAppear { animate() }
        .onChange(of: fraction) { _, _ in animate() }
    }

    /// Segmented LED strip: lit cells take a gradient, dim cells stay outlined.
    private func ledBar(size: CGSize) -> some View {
        let cell: CGFloat = max(3, height * 0.75)
        let gap: CGFloat = 1.5
        let count = max(1, Int((size.width + gap) / (cell + gap)))
        let lit = Int((Double(count) * min(max(shown, 0), 1)).rounded())
        return Canvas { ctx, _ in
            let gradient = Gradient(colors: [accent ?? tint.opacity(0.7), tint])
            for i in 0..<count {
                let rect = CGRect(x: CGFloat(i) * (cell + gap), y: 0, width: cell, height: size.height)
                if i < lit {
                    ctx.fill(Path(rect), with: .linearGradient(gradient, startPoint: .zero, endPoint: CGPoint(x: size.width, y: 0)))
                } else {
                    ctx.fill(Path(rect), with: .color(tint.opacity(0.12)))
                }
            }
        }
        .shadow(color: tint.opacity(0.9), radius: 3)
        .shadow(color: tint.opacity(0.5), radius: 8)
    }

    private func animate() {
        if PanelView.expandForPreview { shown = fraction; return }
        withAnimation(.spring(response: 0.9, dampingFraction: 0.85)) { shown = fraction }
    }
}

/// Remaining-percentage ring; each theme draws its own arc.
struct Ring: View {
    let remaining: Double
    var size: CGFloat = 58
    var lineWidth: CGFloat = 6
    var caption: String? = "剩余"
    /// False for the inner rings of a StackedRing, which draws one centre label.
    var showsValue = true
    @State private var shown = 0.0
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let tint = theme.health(remaining)
        let accent = theme.healthAccent(remaining)
        let progress = min(max(shown / 100, 0.001), 1)
        ZStack {
            switch theme {
            case .minimal:
                Circle().stroke(Color.primary.opacity(0.08), lineWidth: 1)
                Circle().trim(from: 0, to: progress)
                    .stroke(tint, style: StrokeStyle(lineWidth: max(1.5, lineWidth * 0.3)))
                    .rotationEffect(.degrees(-90))
            case .native:
                Circle().stroke(Color.primary.opacity(0.1), lineWidth: lineWidth)
                Circle().trim(from: 0, to: progress)
                    .stroke(tint, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                    .rotationEffect(.degrees(-90))
            case .aurora:
                Circle().stroke(Color.primary.opacity(0.08), lineWidth: lineWidth)
                Circle().trim(from: 0, to: progress)
                    .stroke(AngularGradient(colors: [accent, tint, tint], center: .center,
                                            startAngle: .degrees(0), endAngle: .degrees(360 * max(shown / 100, 0.01))),
                            style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .shadow(color: tint.opacity(0.7), radius: lineWidth * 0.9)
            case .neon:
                neonRing(tint: tint, accent: accent, progress: progress)
            }
            if showsValue { VStack(spacing: -1) {
                (Text(Fmt.trim(remaining.rounded())).font(theme.number(size * 0.29))
                 + Text("%").font(.system(size: size * 0.17, weight: theme == .minimal ? .light : .bold, design: theme.numberDesign)))
                    .monospacedDigit()
                    .foregroundStyle(theme == .aurora || theme == .neon
                                     ? AnyShapeStyle(LinearGradient(colors: [tint, accent], startPoint: .top, endPoint: .bottom))
                                     : AnyShapeStyle(theme == .minimal ? Color.primary : tint))
                    .themeGlow(tint.opacity(0.8), radius: 3, theme: theme == .neon ? .neon : .minimal)
                if let caption {
                    Text(caption).font(.system(size: max(8, size * 0.15), design: theme.numberDesign)).foregroundStyle(.secondary)
                }
            } }
        }
        .frame(width: size, height: size)
        .onAppear {
            if PanelView.expandForPreview { shown = remaining; return }
            withAnimation(.spring(response: 1.1, dampingFraction: 0.8)) { shown = remaining }
        }
        .onChange(of: remaining) { _, v in withAnimation(.spring(response: 0.8)) { shown = v } }
    }

    /// Dashed tick track, segmented gradient arc and an outer hairline orbit.
    @ViewBuilder private func neonRing(tint: Color, accent: Color, progress: Double) -> some View {
        let circumference = .pi * (size - lineWidth)
        let segments = max(16.0, (circumference / 5).rounded())
        let dash = [circumference / segments * 0.62, circumference / segments * 0.38]
        Circle()
            .stroke(tint.opacity(0.14), style: StrokeStyle(lineWidth: lineWidth, dash: dash))
        Circle().trim(from: 0, to: progress)
            .stroke(AngularGradient(colors: [accent, tint, tint], center: .center,
                                    startAngle: .degrees(0), endAngle: .degrees(360 * max(progress, 0.01))),
                    style: StrokeStyle(lineWidth: lineWidth, dash: dash))
            .rotationEffect(.degrees(-90))
            .shadow(color: tint, radius: lineWidth * 0.5)
            .shadow(color: accent.opacity(0.8), radius: lineWidth * 1.6)
        Circle()
            .stroke(Neon.rim, lineWidth: 0.6)
            .padding(-lineWidth * 0.9)
            .opacity(0.7)
    }
}

/// Several windows of one account as concentric rings (outer = shortest
/// window), so 5 小时 and 7 天 share one gauge. The centre shows the outer ring.
struct StackedRing: View {
    let remaining: [Double]
    var size: CGFloat = 54
    var lineWidth: CGFloat = 4
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let step = lineWidth + (theme == .neon ? 3 : 2)
        let rings = Array(remaining.prefix(3))
        let hole = size - 2 * step * CGFloat(rings.count - 1) - 2 * lineWidth
        ZStack {
            ForEach(rings.indices, id: \.self) { i in
                Ring(remaining: rings[i], size: size - 2 * step * CGFloat(i), lineWidth: lineWidth,
                     caption: nil, showsValue: false)
            }
            if let first = rings.first {
                let tint = theme.health(first)
                (Text(Fmt.trim(first.rounded())).font(theme.number(hole * 0.42))
                 + Text("%").font(.system(size: hole * 0.24, weight: theme == .minimal ? .light : .bold, design: theme.numberDesign)))
                    .monospacedDigit()
                    .foregroundStyle(theme == .minimal ? AnyShapeStyle(Color.primary) : AnyShapeStyle(tint))
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
                    .frame(maxWidth: hole - 2)
            }
        }
        .frame(width: size, height: size)
    }
}

// MARK: Rows and controls

/// Label on the left, value on the right, optional detail beneath the value.
struct InfoRow: View {
    let symbol: String
    let title: String
    let value: String
    var detail: String? = nil
    var valueTint: Color = .primary
    /// A part of the row above (e.g. one credit bucket of a balance).
    var nested = false
    @Environment(\.panelTheme) private var theme

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            if nested {
                Color.clear.frame(width: theme == .minimal ? 8 : 14, height: 1)
                Text("└").font(.system(size: 10)).foregroundStyle(.tertiary)
            } else if theme != .minimal {
                Image(systemName: symbol)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(theme == .neon ? AnyShapeStyle(Neon.cyan) : AnyShapeStyle(.secondary))
                    .frame(width: 14)
            }
            Text(title).font(.system(size: nested ? 11 : 12)).foregroundStyle(.secondary)
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(value)
                    .font(.system(size: nested ? 11.5 : 12.5, weight: theme == .minimal || nested ? .regular : .semibold, design: theme.numberDesign))
                    .foregroundStyle(theme.tint(valueTint)).monospacedDigit()
                if let detail {
                    Text(detail).font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                }
            }
        }
    }
}

struct SectionTitle: View {
    let text: String
    var trailing: String? = nil
    @Environment(\.panelTheme) private var theme

    var body: some View {
        HStack {
            Text(theme == .neon ? "// " + text : text)
                .font(.system(size: 11, weight: theme == .minimal ? .medium : .bold, design: theme == .neon ? .monospaced : .default))
                .foregroundStyle(theme == .neon ? AnyShapeStyle(Neon.magenta) : AnyShapeStyle(.secondary))
                .kerning(theme == .minimal ? 1.2 : 0.5)
            Spacer()
            if let trailing { Text(trailing).font(.system(size: 10.5)).foregroundStyle(.tertiary) }
        }
        .padding(.horizontal, 2)
    }
}

struct IconButton: View {
    let symbol: String
    let help: String
    var spinning = false
    let action: () -> Void
    @State private var hovering = false
    @Environment(\.panelTheme) private var theme

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: theme == .minimal ? .regular : .semibold))
                .rotationEffect(.degrees(spinning ? 360 : 0))
                .animation(spinning ? .linear(duration: 0.9).repeatForever(autoreverses: false) : .default, value: spinning)
                .frame(width: 28, height: 28)
                .foregroundStyle(theme == .neon ? AnyShapeStyle(Neon.cyan) : AnyShapeStyle(theme == .minimal && !hovering ? .secondary : .primary))
                .background { chrome }
                .scaleEffect(hovering && theme != .minimal ? 1.08 : 1)
        }
        .buttonStyle(.plain)
        .onHover { h in withAnimation(.easeOut(duration: 0.15)) { hovering = h } }
        .help(help)
    }

    @ViewBuilder private var chrome: some View {
        switch theme {
        case .minimal:
            EmptyView()
        case .native:
            Circle().fill(Color.primary.opacity(hovering ? 0.1 : 0.05))
        case .aurora:
            Circle().fill(.ultraThinMaterial)
                .overlay(Circle().strokeBorder(Color.primary.opacity(hovering ? 0.25 : 0.1), lineWidth: 0.6))
        case .neon:
            RoundedRectangle(cornerRadius: 5, style: .continuous).fill(Color.black.opacity(0.5))
                .overlay(RoundedRectangle(cornerRadius: 5, style: .continuous).strokeBorder(Neon.cyan.opacity(hovering ? 1 : 0.55), lineWidth: 1))
                .shadow(color: Neon.cyan.opacity(hovering ? 0.9 : 0.4), radius: hovering ? 8 : 4)
        }
    }
}

/// Segmented control; the selection slides between items in every theme.
struct PillTabs<T: Hashable & Identifiable>: View {
    let items: [T]
    let title: (T) -> String
    @Binding var selection: T
    var small = false
    @Namespace private var ns
    @Environment(\.panelTheme) private var theme

    var body: some View {
        HStack(spacing: theme == .minimal ? 14 : 2) {
            ForEach(items) { item in
                let selected = item == selection
                Text(title(item))
                    .font(.system(size: small ? 11 : 12, weight: selected ? (theme == .minimal ? .semibold : .bold) : .medium,
                                  design: theme == .neon ? .monospaced : .default))
                    .foregroundStyle(foreground(selected))
                    .frame(maxWidth: theme == .minimal ? nil : .infinity)
                    .padding(.vertical, small ? 4 : 6)
                    .background { if selected { highlight } }
                    .contentShape(Rectangle())
                    .onTapGesture { withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { selection = item } }
            }
            if theme == .minimal { Spacer(minLength: 0) }
        }
        .padding(theme == .minimal ? 0 : 3)
        .background { container }
    }

    private func foreground(_ selected: Bool) -> AnyShapeStyle {
        switch theme {
        case .minimal: return selected ? AnyShapeStyle(.primary) : AnyShapeStyle(.tertiary)
        case .native: return selected ? AnyShapeStyle(.primary) : AnyShapeStyle(.secondary)
        case .aurora: return selected ? AnyShapeStyle(Color.white) : AnyShapeStyle(.secondary)
        case .neon: return selected ? AnyShapeStyle(Color.black) : AnyShapeStyle(Neon.cyan.opacity(0.75))
        }
    }

    @ViewBuilder private var highlight: some View {
        switch theme {
        case .minimal:
            Rectangle().fill(Color.primary).frame(height: 1.5)
                .frame(maxHeight: .infinity, alignment: .bottom)
                .matchedGeometryEffect(id: "pill", in: ns)
        case .native:
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor))
                .shadow(color: .black.opacity(0.12), radius: 1.5, y: 0.5)
                .matchedGeometryEffect(id: "pill", in: ns)
        case .aurora:
            Capsule()
                .fill(LinearGradient(colors: theme.accent, startPoint: .leading, endPoint: .trailing))
                .shadow(color: Color(red: 0.5, green: 0.4, blue: 1).opacity(0.55), radius: 6)
                .matchedGeometryEffect(id: "pill", in: ns)
        case .neon:
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(LinearGradient(colors: [Neon.cyan, Neon.lime], startPoint: .leading, endPoint: .trailing))
                .shadow(color: Neon.cyan.opacity(0.9), radius: 6)
                .shadow(color: Neon.magenta.opacity(0.6), radius: 14)
                .matchedGeometryEffect(id: "pill", in: ns)
        }
    }

    @ViewBuilder private var container: some View {
        switch theme {
        case .minimal:
            EmptyView()
        case .native:
            RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.primary.opacity(0.06))
        case .aurora:
            Capsule().fill(.ultraThinMaterial)
                .overlay(Capsule().strokeBorder(Color.primary.opacity(0.1), lineWidth: 0.6))
        case .neon:
            RoundedRectangle(cornerRadius: 5, style: .continuous).fill(Color.black.opacity(0.55))
                .overlay(RoundedRectangle(cornerRadius: 5, style: .continuous).strokeBorder(Neon.rim, lineWidth: 1))
        }
    }
}
