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

    var body: some View {
        let edge = tint ?? Color.white
        VStack(alignment: .leading, spacing: 10) { content }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
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
}

/// The real app icon when installed, otherwise a gradient tile with a symbol.
struct BrandBadge: View {
    let brand: Catalog.Brand
    var size: CGFloat = 26
    var icon: NSImage? = nil

    var body: some View {
        Group {
            if let icon {
                Image(nsImage: icon).resizable().interpolation(.high).frame(width: size, height: size)
            } else {
                RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
                    .fill(LinearGradient(colors: [brand.tint, brand.tint.opacity(0.6)], startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: size, height: size)
                    .overlay(Image(systemName: brand.symbol).font(.system(size: size * 0.46, weight: .semibold)).foregroundStyle(.white))
            }
        }
        .shadow(color: brand.tint.opacity(0.45), radius: 5, y: 1)
    }
}

struct StatusPill: View {
    let status: String
    var text: String? = nil
    var body: some View {
        let color = Catalog.statusColor(status)
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 5, height: 5).shadow(color: color, radius: 2)
            Text(text ?? Catalog.statusLabel(status)).font(.system(size: 10, weight: .semibold))
        }
        .padding(.horizontal, 7).padding(.vertical, 3)
        .foregroundStyle(color)
        .background(Capsule().fill(color.opacity(0.13)))
        .overlay(Capsule().strokeBorder(color.opacity(0.3), lineWidth: 0.5))
    }
}

// MARK: Gauges

struct Meter: View {
    let fraction: Double
    let tint: Color
    var accent: Color? = nil
    var height: CGFloat = 6
    @State private var shown = 0.0

    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.08))
                Capsule()
                    .fill(LinearGradient(colors: [accent ?? tint.opacity(0.7), tint], startPoint: .leading, endPoint: .trailing))
                    .frame(width: max(height, g.size.width * min(max(shown, 0), 1)))
                    .shadow(color: tint.opacity(0.6), radius: 4)
            }
        }
        .frame(height: height)
        .onAppear { animate() }
        .onChange(of: fraction) { _, _ in animate() }
    }

    private func animate() {
        if PanelView.expandForPreview { shown = fraction; return }
        withAnimation(.spring(response: 0.9, dampingFraction: 0.85)) { shown = fraction }
    }
}

/// Neon ring: angular gradient, glow and an animated sweep.
struct Ring: View {
    let remaining: Double
    var size: CGFloat = 58
    var lineWidth: CGFloat = 6
    var caption: String? = "剩余"
    @State private var shown = 0.0

    var body: some View {
        let tint = healthTint(remaining)
        let accent = healthTintAccent(remaining)
        ZStack {
            Circle().stroke(Color.primary.opacity(0.08), lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: min(max(shown / 100, 0.001), 1))
                .stroke(AngularGradient(colors: [accent, tint, tint], center: .center,
                                        startAngle: .degrees(0), endAngle: .degrees(360 * max(shown / 100, 0.01))),
                        style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .shadow(color: tint.opacity(0.7), radius: lineWidth * 0.9)
            VStack(spacing: -1) {
                (Text(Fmt.trim(remaining.rounded())).font(.system(size: size * 0.29, weight: .heavy, design: .rounded))
                 + Text("%").font(.system(size: size * 0.17, weight: .bold, design: .rounded)))
                    .monospacedDigit()
                    .foregroundStyle(LinearGradient(colors: [tint, accent], startPoint: .top, endPoint: .bottom))
                if let caption {
                    Text(caption).font(.system(size: max(8, size * 0.15))).foregroundStyle(.secondary)
                }
            }
        }
        .frame(width: size, height: size)
        .onAppear {
            if PanelView.expandForPreview { shown = remaining; return }
            withAnimation(.spring(response: 1.1, dampingFraction: 0.8)) { shown = remaining }
        }
        .onChange(of: remaining) { _, v in withAnimation(.spring(response: 0.8)) { shown = v } }
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

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: symbol)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
                .frame(width: 14)
            Text(title).font(.system(size: 12)).foregroundStyle(.secondary)
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(value).font(.system(size: 12.5, weight: .semibold, design: .rounded)).foregroundStyle(valueTint).monospacedDigit()
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
    var body: some View {
        HStack {
            Text(text).font(.system(size: 11, weight: .bold)).foregroundStyle(.secondary).kerning(0.5)
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

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .semibold))
                .rotationEffect(.degrees(spinning ? 360 : 0))
                .animation(spinning ? .linear(duration: 0.9).repeatForever(autoreverses: false) : .default, value: spinning)
                .frame(width: 28, height: 28)
                .background(Circle().fill(.ultraThinMaterial))
                .overlay(Circle().strokeBorder(Color.primary.opacity(hovering ? 0.25 : 0.1), lineWidth: 0.6))
                .scaleEffect(hovering ? 1.08 : 1)
        }
        .buttonStyle(.plain)
        .onHover { h in withAnimation(.easeOut(duration: 0.15)) { hovering = h } }
        .help(help)
    }
}

/// Glass segmented control with a sliding glowing highlight.
struct PillTabs<T: Hashable & Identifiable>: View {
    let items: [T]
    let title: (T) -> String
    @Binding var selection: T
    var small = false
    @Namespace private var ns

    var body: some View {
        HStack(spacing: 2) {
            ForEach(items) { item in
                let selected = item == selection
                Text(title(item))
                    .font(.system(size: small ? 11 : 12, weight: selected ? .bold : .medium))
                    .foregroundStyle(selected ? Color.white : Color.secondary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, small ? 4 : 6)
                    .background {
                        if selected {
                            Capsule()
                                .fill(LinearGradient(colors: [Color(red: 0.40, green: 0.45, blue: 1.0), Color(red: 0.70, green: 0.36, blue: 0.98)],
                                                     startPoint: .leading, endPoint: .trailing))
                                .shadow(color: Color(red: 0.5, green: 0.4, blue: 1).opacity(0.55), radius: 6)
                                .matchedGeometryEffect(id: "pill", in: ns)
                        }
                    }
                    .contentShape(Capsule())
                    .onTapGesture { withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { selection = item } }
            }
        }
        .padding(3)
        .background(Capsule().fill(.ultraThinMaterial))
        .overlay(Capsule().strokeBorder(Color.primary.opacity(0.1), lineWidth: 0.6))
    }
}
