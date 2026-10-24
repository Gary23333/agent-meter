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
        ZStack {
            (scheme == .dark ? Color(red: 0.045, green: 0.055, blue: 0.105) : Color(red: 0.95, green: 0.965, blue: 0.99))
            ZStack {
                blob(Color(red: 0.36, green: 0.42, blue: 1.0), x: drift ? -120 : -60, y: drift ? -240 : -170, size: 300)
                blob(Color(red: 0.78, green: 0.32, blue: 0.98), x: drift ? 165 : 110, y: drift ? -70 : -120, size: 260)
                blob(Color(red: 0.10, green: 0.86, blue: 0.80), x: drift ? -100 : -140, y: drift ? 275 : 200, size: 280)
                blob(Color(red: 1.0, green: 0.45, blue: 0.55), x: drift ? 175 : 120, y: drift ? 330 : 380, size: 220)
            }
            .opacity(scheme == .dark ? 0.60 : 0.38)
            .blur(radius: 70)
        }
        .clipped()
        .drawingGroup()
    }

    private func blob(_ color: Color, x: CGFloat, y: CGFloat, size: CGFloat) -> some View {
        Circle().fill(color.opacity(0.48)).frame(width: size, height: size).offset(x: x, y: y)
    }
}


// MARK: Cards

struct Card<Content: View>: View {
    var tint: Color? = nil
    @ViewBuilder var content: Content
    @Environment(\.colorScheme) private var scheme
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let stack = VStack(alignment: .leading, spacing: 11) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
        switch theme {
        case .minimal:
            stack
                .padding(.horizontal, 2)
                .padding(.vertical, 12)
                .overlay(alignment: .bottom) { Rectangle().fill(Color.primary.opacity(0.12)).frame(height: 0.5) }
        case .native:
            stack
                .padding(13)
                .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(Color(nsColor: .separatorColor).opacity(0.75), lineWidth: 0.5))
                .shadow(color: .black.opacity(scheme == .dark ? 0.20 : 0.045), radius: 2, y: 1)
        case .porcelain, .titanium:
            dimensional(stack)
        case .aurora:
            aurora(stack)
        case .neon, .prism:
            luminous(stack)
        }
    }

    private func dimensional(_ stack: some View) -> some View {
        let porcelain = theme == .porcelain
        let edge = tint ?? theme.accent[0]
        let shape = RoundedRectangle(cornerRadius: porcelain ? 16 : 14, style: .continuous)
        let fill = LinearGradient(colors: porcelain
                                  ? [Color.white.opacity(0.97), Color(red: 0.91, green: 0.93, blue: 0.96).opacity(0.96)]
                                  : [Color(red: 0.135, green: 0.17, blue: 0.21), Color(red: 0.065, green: 0.085, blue: 0.11)],
                                  startPoint: .topLeading, endPoint: .bottomTrailing)
        return stack
            .padding(14)
            .background(shape.fill(fill))
            .overlay(shape.strokeBorder(LinearGradient(colors: [Color.white.opacity(porcelain ? 0.90 : 0.24), edge.opacity(porcelain ? 0.15 : 0.20), Color.black.opacity(porcelain ? 0.08 : 0.34)], startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 0.8))
            .overlay(alignment: .top) {
                Capsule().fill(Color.white.opacity(porcelain ? 0.70 : 0.10)).frame(height: 1).padding(.horizontal, 24).padding(.top, 4)
            }
            .shadow(color: porcelain ? Color(red: 0.20, green: 0.27, blue: 0.38).opacity(0.13) : Color.black.opacity(0.34), radius: porcelain ? 9 : 10, x: 0, y: 5)
    }

    private func aurora(_ stack: some View) -> some View {
        let edge = tint ?? theme.accent[0]
        let shape = RoundedRectangle(cornerRadius: 14, style: .continuous)
        return stack
            .padding(14)
            .background {
                ZStack {
                    shape.fill(scheme == .dark ? Color(red: 0.075, green: 0.085, blue: 0.15).opacity(0.90) : Color.white.opacity(0.82))
                    shape.fill(.thinMaterial)
                    shape.fill(LinearGradient(colors: [edge.opacity(tint == nil ? 0.035 : 0.09), .clear], startPoint: .topLeading, endPoint: .bottomTrailing))
                }
            }
            .overlay(shape.strokeBorder(LinearGradient(colors: [Color.white.opacity(scheme == .dark ? 0.20 : 0.70), edge.opacity(tint == nil ? 0.20 : 0.38), Color.primary.opacity(0.08)], startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 0.7))
            .shadow(color: .black.opacity(scheme == .dark ? 0.24 : 0.08), radius: 9, y: 4)
    }

    /// Luminous themes keep their identity in the rim and charts, not in a
    /// competing glow around every paragraph. Prism is softer than Neon.
    private func luminous(_ stack: some View) -> some View {
        let edge = tint ?? (theme == .prism ? Neon.violet : Neon.cyan)
        let prism = theme == .prism
        let shape = RoundedRectangle(cornerRadius: prism ? 12 : 8, style: .continuous)
        return stack
            .padding(14)
            .background(
                shape.fill(Color(red: 0.025, green: 0.035, blue: 0.075).opacity(0.88))
                    .overlay(shape.fill(LinearGradient(colors: [edge.opacity(prism ? 0.10 : 0.07), .clear, Neon.magenta.opacity(prism ? 0.055 : 0.025)], startPoint: .topLeading, endPoint: .bottomTrailing)))
            )
            .overlay(shape.strokeBorder(prism ? AnyShapeStyle(Neon.rim.opacity(0.42)) : AnyShapeStyle(edge.opacity(0.48)), lineWidth: 0.8))
            .overlay {
                if !prism { CornerBrackets(length: 8).stroke(edge.opacity(0.72), lineWidth: 1.2).padding(-1.5) }
            }
            .shadow(color: .black.opacity(0.34), radius: 8, y: 4)
            .shadow(color: edge.opacity(prism ? 0.12 : 0.09), radius: 5)
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
            case .porcelain, .aurora, .titanium:
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.08))
                    Capsule()
                        .fill(LinearGradient(colors: [accent ?? tint.opacity(0.7), tint], startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(height, width))
                        .shadow(color: tint.opacity(0.6), radius: 4)
                }
            case .neon, .prism:
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
            case .porcelain, .aurora, .titanium:
                Circle().stroke(Color.primary.opacity(0.08), lineWidth: lineWidth)
                Circle().trim(from: 0, to: progress)
                    .stroke(AngularGradient(colors: [accent, tint, tint], center: .center,
                                            startAngle: .degrees(0), endAngle: .degrees(360 * max(shown / 100, 0.01))),
                            style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .shadow(color: tint.opacity(0.7), radius: lineWidth * 0.9)
            case .neon, .prism:
                neonRing(tint: tint, accent: accent, progress: progress)
            }
            if showsValue { VStack(spacing: 0) {
                (Text(Fmt.trim(remaining.rounded())).font(theme.number(size * 0.29))
                 + Text("%").font(.system(size: size * 0.16, weight: .semibold, design: theme.numberDesign)))
                    .monospacedDigit()
                    .themeForeground()
                if let caption {
                    Text(caption)
                        .font(.system(size: max(8.5, size * 0.15), weight: .medium, design: theme.numberDesign))
                        .themeForeground(.secondary)
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
                (Text(Fmt.trim(first.rounded())).font(theme.number(hole * 0.42))
                 + Text("%").font(.system(size: hole * 0.24, weight: .semibold, design: theme.numberDesign)))
                    .monospacedDigit()
                    .themeForeground()
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
                Text("└").font(theme.font(10)).themeForeground(.tertiary)
            } else if theme != .minimal {
                Image(systemName: symbol)
                    .font(.system(size: 11, weight: .medium))
                    .themeForeground(.tertiary)
                    .frame(width: 14)
            }
            Text(title)
                .font(theme.font(nested ? 11.5 : 12))
                .themeForeground(.secondary)
                .lineLimit(1)
            Spacer(minLength: 10)
            VStack(alignment: .trailing, spacing: 2) {
                Text(value)
                    .font(.system(size: nested ? 11.5 : 12.5, weight: nested ? .medium : .semibold, design: theme.numberDesign))
                    .foregroundStyle(theme.tint(valueTint))
                    .monospacedDigit()
                if let detail {
                    Text(detail).font(theme.font(10.5)).themeForeground(.tertiary).monospacedDigit()
                }
            }
            .frame(minWidth: 72, alignment: .trailing)
        }
        .frame(minHeight: nested ? 16 : 18)
    }
}

struct SectionTitle: View {
    let text: String
    var trailing: String? = nil
    @Environment(\.panelTheme) private var theme

    var body: some View {
        HStack(spacing: 8) {
            Text(theme == .neon ? "// " + text : text)
                .font(theme.font(11.5, weight: .semibold))
                .themeForeground(.secondary)
                .kerning(theme == .minimal ? 1.0 : 0.25)
            Spacer(minLength: 8)
            if let trailing {
                Text(trailing).font(theme.font(10.5, weight: .medium)).themeForeground(.tertiary).monospacedDigit()
            }
        }
        .padding(.horizontal, 2)
        .frame(minHeight: 17)
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
        case .porcelain, .aurora, .titanium:
            Circle().fill(.ultraThinMaterial)
                .overlay(Circle().strokeBorder(Color.primary.opacity(hovering ? 0.25 : 0.1), lineWidth: 0.6))
        case .neon, .prism:
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
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(spacing: theme == .minimal ? 14 : 2) {
            ForEach(items) { item in
                let selected = item == selection
                Button {
                    withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { selection = item }
                } label: {
                    Text(title(item))
                        .font(theme.font(small ? 11 : 12, weight: selected ? .semibold : .medium))
                        .foregroundStyle(foreground(selected))
                        .lineLimit(1)
                        .frame(maxWidth: theme == .minimal ? nil : .infinity)
                        .padding(.vertical, small ? 5 : 6)
                        .background { if selected { highlight } }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            if theme == .minimal { Spacer(minLength: 0) }
        }
        .padding(theme == .minimal ? 0 : 3)
        .background { container }
    }

    private func foreground(_ selected: Bool) -> AnyShapeStyle {
        if !selected { return AnyShapeStyle(theme.textColor(.secondary, scheme: scheme)) }
        switch theme {
        case .minimal, .native: return AnyShapeStyle(theme.textColor(.primary, scheme: scheme))
        case .porcelain, .aurora: return AnyShapeStyle(Color.white)
        case .titanium: return AnyShapeStyle(Color(red: 0.055, green: 0.08, blue: 0.11))
        case .neon, .prism: return AnyShapeStyle(Color(red: 0.025, green: 0.035, blue: 0.06))
        }
    }

    @ViewBuilder private var highlight: some View {
        switch theme {
        case .minimal:
            Rectangle().fill(Color.primary).frame(height: 1.5)
                .frame(maxHeight: .infinity, alignment: .bottom)
                .matchedGeometryEffect(id: "pill", in: ns)
        case .native:
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor))
                .shadow(color: .black.opacity(0.10), radius: 1.5, y: 0.5)
                .matchedGeometryEffect(id: "pill", in: ns)
        case .porcelain, .aurora, .titanium:
            Capsule()
                .fill(LinearGradient(colors: theme.accent, startPoint: .leading, endPoint: .trailing))
                .overlay(Capsule().strokeBorder(Color.white.opacity(theme == .porcelain ? 0.22 : 0.12), lineWidth: 0.5))
                .shadow(color: theme.accent[0].opacity(0.18), radius: 3, y: 1)
                .matchedGeometryEffect(id: "pill", in: ns)
        case .neon, .prism:
            RoundedRectangle(cornerRadius: 5, style: .continuous)
                .fill(LinearGradient(colors: theme == .prism ? [Neon.cyan, Color(red: 0.65, green: 0.55, blue: 1.0)] : [Neon.cyan, Neon.lime], startPoint: .leading, endPoint: .trailing))
                .shadow(color: Neon.cyan.opacity(0.30), radius: 4)
                .matchedGeometryEffect(id: "pill", in: ns)
        }
    }

    @ViewBuilder private var container: some View {
        switch theme {
        case .minimal:
            EmptyView()
        case .native:
            RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Color.primary.opacity(0.055))
        case .porcelain:
            Capsule().fill(Color(red: 0.84, green: 0.87, blue: 0.92).opacity(0.72))
                .overlay(Capsule().strokeBorder(Color.white.opacity(0.70), lineWidth: 0.6))
        case .aurora:
            Capsule().fill(scheme == .dark ? Color.white.opacity(0.08) : Color.white.opacity(0.48))
                .overlay(Capsule().strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.6))
        case .titanium:
            Capsule().fill(Color(red: 0.025, green: 0.04, blue: 0.055).opacity(0.70))
                .overlay(Capsule().strokeBorder(Color.white.opacity(0.12), lineWidth: 0.6))
        case .neon, .prism:
            RoundedRectangle(cornerRadius: 7, style: .continuous).fill(Color.black.opacity(0.48))
                .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous).strokeBorder(theme == .prism ? Neon.violet.opacity(0.45) : Neon.cyan.opacity(0.32), lineWidth: 0.7))
        }
    }
}
