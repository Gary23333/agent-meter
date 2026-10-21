import AppKit
import SwiftUI

/// 离屏渲染的分享卡：宽度固定、高度随内容自适应，无动画、无材质、无窗口状态，保证 ImageRenderer 结果稳定。
struct ShareCard: View {
    let data: ReportData
    let theme: PanelTheme

    /// 横版固定宽度，高度随内容自适应。
    static let width: CGFloat = 800

    private var outerPad: CGFloat { 18 }
    private var heroSize: CGFloat { 54 }
    private var costSize: CGFloat { 22 }
    private var sectionSize: CGFloat { 10 }
    private var rowSize: CGFloat { 13 }
    private var smallSize: CGFloat { 9.5 }
    private var radius: CGFloat { 12 }
    /// 霓虹主题的等宽字体行高更高，纵向间距收紧一点，保证不压到卡片边缘。
    private var rowGap: CGFloat { theme == .neon ? 5 : 7 }
    private var modelGap: CGFloat { theme == .neon ? 4 : 6 }
    private var landscapeDividerPad: CGFloat { theme == .neon ? 6 : 10 }

    var body: some View {
        landscapeBody
        .frame(width: Self.width, alignment: .topLeading)
        .background(cardBackground)
        .environment(\.colorScheme, theme == .neon ? .dark : .light)
        .overlay {
            if theme == .neon {
                CornerBrackets(length: 18).stroke(Neon.cyan.opacity(0.65), lineWidth: 1.5).padding(12)
            }
        }
        .clipShape(Rectangle())
    }

    // MARK: 版式

    private var landscapeBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 20) {
                VStack(alignment: .leading, spacing: 10) {
                    brandRow
                    surface(pad: 16) {
                        VStack(alignment: .leading, spacing: 0) {
                            heroFigures
                            Spacer(minLength: 14)
                            metricStrip
                            Spacer(minLength: 16)
                            divider
                            compositionBlock.padding(.top, 12)
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    }
                    .frame(maxHeight: .infinity)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

                surface(pad: 16) {
                    VStack(alignment: .leading, spacing: 0) {
                        appList
                        Spacer(minLength: 10)
                        divider.padding(.vertical, landscapeDividerPad)
                        modelList
                        Spacer(minLength: 10)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            Spacer().frame(height: 8)
            footerRow
        }
        .padding(.horizontal, 26)
        .padding(.vertical, outerPad)
    }

    // MARK: 品牌行 / 页脚

    private var brandRow: some View {
        HStack(spacing: 10) {
            mark(size: 26)
            HStack(spacing: 4) {
                Text("AgentMeter")
                    .font(.system(size: 12, weight: theme == .minimal ? .medium : .bold, design: theme.numberDesign))
                Text("· 用量报告")
                    .font(.system(size: 11, weight: .regular))
            }
            .foregroundStyle(ink)
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 2) {
                Text("\(data.period.label) · 本机消耗")
                Text(Fmt.day(data.generatedAt, now: data.generatedAt) + " 生成")
            }
            .font(.system(size: smallSize))
            .foregroundStyle(muted)
        }
    }

    private var footerRow: some View {
        HStack(spacing: 8) {
            Text("数据来自本机账本 · 只读聚合 · 不含对话内容")
            Spacer(minLength: 6)
            Text("费用为 API 等价估算")
        }
        .font(.system(size: 8.5))
        .foregroundStyle(faint)
        .lineLimit(1)
        .minimumScaleFactor(0.7)
    }

    // MARK: 主数字

    private var heroFigures: some View {
        VStack(alignment: .leading, spacing: 11) {
            HStack(alignment: .bottom, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("TOKEN 总量")
                        .font(.system(size: smallSize, weight: theme == .minimal ? .regular : .semibold, design: theme.numberDesign))
                        .kerning(1.2)
                        .foregroundStyle(muted)
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Text(Fmt.tokens(data.totalTokens))
                            .font(theme.number(heroSize))
                            .monospacedDigit()
                            .lineLimit(1)
                            .minimumScaleFactor(0.6)
                            .foregroundStyle(heroStyle)
                            .themeGlow(theme == .neon ? Neon.cyan.opacity(0.55) : .clear, radius: 6,
                                       theme: theme == .neon ? .neon : .minimal)
                        Text("tokens")
                            .font(.system(size: smallSize))
                            .foregroundStyle(muted)
                    }
                }
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 3) {
                    Text("估算费用")
                        .font(.system(size: smallSize, weight: theme == .minimal ? .regular : .semibold, design: theme.numberDesign))
                        .foregroundStyle(muted)
                    Text(data.costText)
                        .font(theme.number(costSize))
                        .monospacedDigit()
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                        .foregroundStyle(costStyle)
                        .themeGlow(theme == .neon ? Neon.lime.opacity(0.45) : .clear, radius: 5,
                                   theme: theme == .neon ? .neon : .minimal)
                    Text("API 等价")
                        .font(.system(size: smallSize - 1))
                        .foregroundStyle(faint)
                }
            }
            if let note = heroNote {
                Text(note)
                    .font(.system(size: smallSize))
                    .foregroundStyle(theme == .neon ? Neon.yellow.opacity(0.85) : Color.orange)
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }
        }
    }

    private var heroNote: String? {
        var parts: [String] = []
        if data.totalIsLowerBound { parts.append("总量为下界") }
        if !data.unpricedModels.isEmpty {
            let names = data.unpricedModels.prefix(2).joined(separator: "、")
            let more = data.unpricedModels.count > 2 ? " 等 \(data.unpricedModels.count) 个" : ""
            parts.append("未计价 " + names + more)
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private var metricStrip: some View {
        HStack(spacing: 0) {
            metric("请求", Fmt.grouped(data.requests))
            metricDivider
            metric("缓存命中", data.cacheHitText)
            metricDivider
            metric("新输入 / 输出", "\(Fmt.tokens(data.freshInput)) / \(Fmt.tokens(data.output))")
            metricDivider
            metric("活跃应用", "\(data.appCount)")
        }
        .padding(.top, 2)
        .overlay(alignment: .top) { hairline.frame(height: 0.6) }
    }

    private func metric(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.system(size: smallSize - 0.5))
                .foregroundStyle(muted)
                .lineLimit(1)
            Text(value)
                .font(.system(size: 12.5, weight: theme == .minimal ? .regular : .semibold, design: theme.numberDesign))
                .monospacedDigit()
                .foregroundStyle(ink)
                .lineLimit(1)
                .minimumScaleFactor(0.65)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.trailing, 6)
    }

    private var metricDivider: some View {
        Rectangle().fill(hairline).frame(width: 0.6, height: 22).padding(.horizontal, 6)
    }

    // MARK: 明细

    private var compositionBlock: some View {
        VStack(alignment: .leading, spacing: 7) {
            sectionTitle("构成", trailing: data.totalTokens > 0 ? "共 \(Fmt.tokens(data.totalTokens))" : nil)
            if data.totalTokens > 0 {
                compositionBar.frame(height: 9)
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(parts) { part in
                        legendItem(part, showsTokens: true)
                    }
                }
            } else {
                Text("暂无 Token 记录").font(.system(size: smallSize)).foregroundStyle(muted)
            }
        }
    }

    private func legendItem(_ part: Part, showsTokens: Bool) -> some View {
        HStack(spacing: 5) {
            RoundedRectangle(cornerRadius: 1.5)
                .fill(part.color)
                .frame(width: 6, height: 6)
            Text(part.label)
                .font(.system(size: smallSize - 0.5))
                .foregroundStyle(muted)
                .lineLimit(1)
            Text(Fmt.percent((part.share * 1000).rounded() / 10))
                .font(.system(size: smallSize - 0.5, weight: theme == .minimal ? .regular : .semibold, design: theme.numberDesign))
                .monospacedDigit()
                .foregroundStyle(ink)
            if showsTokens {
                Spacer(minLength: 4)
                Text(Fmt.tokens(part.value))
                    .font(.system(size: smallSize - 0.5, weight: .medium, design: theme.numberDesign))
                    .monospacedDigit()
                    .foregroundStyle(muted)
            }
        }
    }

    private var appList: some View {
        VStack(alignment: .leading, spacing: rowGap) {
            sectionTitle("Top 应用", trailing: "Token 占比")
            if data.apps.isEmpty {
                Text("暂无应用记录").font(.system(size: smallSize)).foregroundStyle(muted)
            }
            ForEach(Array(data.apps.prefix(4))) { app in
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        RoundedRectangle(cornerRadius: 1.5)
                            .fill(theme.tint(app.tint))
                            .frame(width: 6, height: 6)
                        Text(app.name)
                            .font(.system(size: rowSize, weight: theme == .minimal ? .regular : .medium))
                            .foregroundStyle(ink)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer(minLength: 6)
                        Text(Fmt.tokens(app.tokens))
                            .font(.system(size: rowSize, weight: .semibold, design: theme.numberDesign))
                            .monospacedDigit()
                            .foregroundStyle(ink)
                    }
                    fractionBar(app.fraction, tint: theme.tint(app.tint), height: 3.5)
                }
            }
        }
    }

    private var modelList: some View {
        VStack(alignment: .leading, spacing: modelGap) {
            sectionTitle("Top 模型", trailing: nil)
            if data.models.isEmpty {
                Text("暂无模型记录").font(.system(size: smallSize)).foregroundStyle(muted)
            }
            ForEach(Array(data.models.prefix(3))) { model in
                HStack(spacing: 6) {
                    Text(model.name)
                        .font(.system(size: rowSize))
                        .foregroundStyle(ink)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Text(model.appLabel)
                        .font(.system(size: smallSize - 1, weight: .medium))
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .foregroundStyle(theme.tint(model.tint))
                        .background(Capsule().fill(theme.tint(model.tint).opacity(theme == .minimal ? 0.08 : 0.16)))
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    if model.cost != "—" {
                        Text(model.cost)
                            .font(.system(size: smallSize))
                            .monospacedDigit()
                            .foregroundStyle(muted)
                            .lineLimit(1)
                    }
                    Text(Fmt.tokens(model.tokens))
                        .font(.system(size: rowSize, weight: .semibold, design: theme.numberDesign))
                        .monospacedDigit()
                        .foregroundStyle(ink)
                }
            }
        }
    }

    // MARK: 组合条

    private struct Part: Identifiable {
        let id: String
        let label: String
        let value: Double
        let color: Color
        let share: Double
    }

    private var parts: [Part] {
        let total = data.totalTokens
        let raw: [(String, String, Double)] = [
            ("in", "新输入", data.freshInput),
            ("out", "输出", data.output),
            ("read", "缓存读", data.cacheRead),
            ("write", "缓存写", data.cacheWrite)
        ]
        let base: [Color] = [
            Color(red: 0.30, green: 0.56, blue: 0.98),
            Color(red: 0.58, green: 0.40, blue: 0.97),
            Color(red: 0.22, green: 0.76, blue: 0.70),
            Color(red: 0.98, green: 0.64, blue: 0.24)
        ]
        return raw.enumerated().map { index, item in
            Part(id: item.0, label: item.1, value: item.2,
                 color: theme.series(base[index], index: index),
                 share: total > 0 ? max(item.2, 0) / total : 0)
        }
    }

    @ViewBuilder private var compositionBar: some View {
        if theme == .neon {
            ledCompositionBar
        } else {
            GeometryReader { geo in
                let gap: CGFloat = theme == .minimal ? 1 : 2
                let available = max(geo.size.width - gap * 3, 0)
                HStack(spacing: gap) {
                    ForEach(parts) { part in
                        RoundedRectangle(cornerRadius: theme == .minimal ? 0 : 4, style: .continuous)
                            .fill(fillStyle(part.color))
                            .frame(width: max(available * part.share, 0))
                            .themeGlow(theme == .aurora ? part.color.opacity(0.5) : .clear, radius: 3,
                                       theme: theme == .aurora ? .aurora : .minimal)
                    }
                }
            }
        }
    }

    private func fillStyle(_ color: Color) -> AnyShapeStyle {
        switch theme {
        case .minimal: return AnyShapeStyle(Color(white: 0.20).opacity(0.85))
        case .native: return AnyShapeStyle(color)
        case .aurora: return AnyShapeStyle(LinearGradient(colors: [color.opacity(0.65), color], startPoint: .leading, endPoint: .trailing))
        case .neon: return AnyShapeStyle(color)
        }
    }

    private var ledCompositionBar: some View {
        Canvas { ctx, size in
            let cell: CGFloat = 4, gap: CGFloat = 2
            let count = max(1, Int((size.width + gap) / (cell + gap)))
            var colorIndex = 0
            var upper = 0.0
            for i in 0..<count {
                let pos = (Double(i) + 0.5) / Double(count)
                while colorIndex < parts.count - 1 && pos > upper + parts[colorIndex].share {
                    upper += parts[colorIndex].share
                    colorIndex += 1
                }
                let rect = CGRect(x: CGFloat(i) * (cell + gap), y: 0, width: cell, height: size.height)
                ctx.fill(Path(rect), with: .color(parts[colorIndex].color))
            }
        }
        .shadow(color: Neon.cyan.opacity(0.35), radius: 3)
    }

    @ViewBuilder
    private func fractionBar(_ fraction: Double, tint: Color, height: CGFloat) -> some View {
        let f = min(max(fraction, 0), 1)
        switch theme {
        case .minimal:
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Rectangle().fill(Color.black.opacity(0.08))
                    Rectangle().fill(Color.black.opacity(0.5)).frame(width: geo.size.width * f)
                }
            }
            .frame(height: 3)
        case .native:
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.black.opacity(0.07))
                    Capsule().fill(tint).frame(width: max(height, geo.size.width * f))
                }
            }
            .frame(height: height)
        case .aurora:
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.55))
                    Capsule()
                        .fill(LinearGradient(colors: [tint.opacity(0.6), tint], startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(height, geo.size.width * f))
                        .shadow(color: tint.opacity(0.5), radius: 3)
                }
            }
            .frame(height: height)
        case .neon:
            Canvas { ctx, size in
                let cell: CGFloat = 3, gap: CGFloat = 2
                let count = max(1, Int((size.width + gap) / (cell + gap)))
                let lit = Int((Double(count) * f).rounded())
                for i in 0..<count {
                    let rect = CGRect(x: CGFloat(i) * (cell + gap), y: 0, width: cell, height: size.height)
                    ctx.fill(Path(rect), with: .color(i < lit ? tint : tint.opacity(0.14)))
                }
            }
            .frame(height: height)
            .shadow(color: tint.opacity(0.5), radius: 2)
        }
    }

    // MARK: 标题 / 分隔线

    private func sectionTitle(_ text: String, trailing: String?) -> some View {
        HStack(spacing: 6) {
            Text(theme == .neon ? "// " + text : text)
                .font(.system(size: sectionSize, weight: theme == .minimal ? .medium : .bold, design: theme.numberDesign))
                .foregroundStyle(theme == .neon ? AnyShapeStyle(Neon.magenta) : AnyShapeStyle(ink))
                .kerning(theme == .minimal ? 1.1 : 0.4)
            Spacer(minLength: 4)
            if let trailing {
                Text(trailing)
                    .font(.system(size: smallSize - 0.5))
                    .foregroundStyle(faint)
                    .lineLimit(1)
            }
        }
    }

    @ViewBuilder private var divider: some View {
        switch theme {
        case .neon:
            Rectangle()
                .fill(LinearGradient(colors: [Neon.magenta.opacity(0.1), Neon.cyan, Neon.lime.opacity(0.1)],
                                     startPoint: .leading, endPoint: .trailing))
                .frame(height: 1)
                .shadow(color: Neon.cyan.opacity(0.5), radius: 3)
        case .minimal:
            Rectangle().fill(Color.black.opacity(0.14)).frame(height: 0.6)
        default:
            Rectangle().fill(Color.black.opacity(0.07)).frame(height: 0.6)
        }
    }

    // MARK: 皮肤

    private var ink: Color {
        switch theme {
        case .minimal: return Color(white: 0.10)
        case .native: return Color(white: 0.10)
        case .aurora: return Color(red: 0.12, green: 0.10, blue: 0.22)
        case .neon: return Color.white
        }
    }

    private var muted: Color {
        switch theme {
        case .minimal: return Color(white: 0.44)
        case .native: return Color(white: 0.43)
        case .aurora: return Color(red: 0.18, green: 0.16, blue: 0.30).opacity(0.62)
        case .neon: return Color.white.opacity(0.58)
        }
    }

    private var faint: Color {
        switch theme {
        case .minimal: return Color(white: 0.58)
        case .native: return Color(white: 0.56)
        case .aurora: return Color(red: 0.18, green: 0.16, blue: 0.30).opacity(0.42)
        case .neon: return Neon.cyan.opacity(0.45)
        }
    }

    private var hairline: Color {
        switch theme {
        case .minimal: return Color.black.opacity(0.14)
        case .native: return Color.black.opacity(0.08)
        case .aurora: return Color.white.opacity(0.65)
        case .neon: return Neon.cyan.opacity(0.28)
        }
    }

    private var heroStyle: AnyShapeStyle {
        switch theme {
        case .minimal: return AnyShapeStyle(Color(white: 0.12))
        case .native: return AnyShapeStyle(Color(nsColor: .systemBlue))
        case .aurora:
            return AnyShapeStyle(LinearGradient(colors: [Color(red: 0.30, green: 0.36, blue: 0.98),
                                                        Color(red: 0.62, green: 0.30, blue: 0.95),
                                                        Color(red: 0.95, green: 0.36, blue: 0.72)],
                                               startPoint: .leading, endPoint: .trailing))
        case .neon:
            return AnyShapeStyle(LinearGradient(colors: [Neon.cyan, Neon.magenta], startPoint: .leading, endPoint: .trailing))
        }
    }

    private var costStyle: AnyShapeStyle {
        switch theme {
        case .minimal: return AnyShapeStyle(Color(white: 0.22))
        case .native: return AnyShapeStyle(Color(nsColor: .systemGreen))
        case .aurora:
            return AnyShapeStyle(LinearGradient(colors: [Color(red: 0.16, green: 0.72, blue: 0.60),
                                                        Color(red: 0.22, green: 0.52, blue: 0.95)],
                                               startPoint: .leading, endPoint: .trailing))
        case .neon:
            return AnyShapeStyle(LinearGradient(colors: [Neon.lime, Neon.cyan], startPoint: .leading, endPoint: .trailing))
        }
    }

    @ViewBuilder private var cardBackground: some View {
        switch theme {
        case .minimal:
            Color.white
        case .native:
            Color(red: 0.955, green: 0.955, blue: 0.972)
        case .aurora:
            AuroraShareBackground()
        case .neon:
            NeonShareBackground()
        }
    }

    @ViewBuilder private func surface<C: View>(pad: CGFloat, @ViewBuilder content: () -> C) -> some View {
        switch theme {
        case .minimal:
            content()
        case .native:
            content()
                .padding(pad)
                .background(RoundedRectangle(cornerRadius: radius, style: .continuous).fill(Color.white))
                .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(Color.black.opacity(0.06), lineWidth: 0.6))
                .shadow(color: .black.opacity(0.06), radius: 7, y: 2)
        case .aurora:
            content()
                .padding(pad)
                .background(
                    RoundedRectangle(cornerRadius: radius, style: .continuous)
                        .fill(Color.white.opacity(0.55))
                        .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous)
                            .strokeBorder(LinearGradient(colors: [Color.white.opacity(0.95), Color.white.opacity(0.30)],
                                                         startPoint: .topLeading, endPoint: .bottomTrailing),
                                          lineWidth: 0.9))
                )
                .shadow(color: Color(red: 0.45, green: 0.36, blue: 0.95).opacity(0.16), radius: 12, y: 4)
        case .neon:
            content()
                .padding(pad)
                .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(Color.black.opacity(0.5)))
                .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).strokeBorder(Neon.rim, lineWidth: 1))
                .overlay(CornerBrackets(length: 9).stroke(Neon.cyan, lineWidth: 1.4).padding(-2))
                .shadow(color: Neon.cyan.opacity(0.35), radius: 8)
        }
    }

    @ViewBuilder private func mark(size: CGFloat) -> some View {
        switch theme {
        case .minimal:
            BrandMark(outer: Color(white: 0.10), inner: Color(white: 0.42),
                      sparkle: Color(white: 0.10), trackOpacity: 0.18)
                .frame(width: size, height: size)
        case .native:
            BrandMark(outer: Color.white, inner: Color.white, trackOpacity: 0.3)
                .frame(width: size * 0.8, height: size * 0.8)
                .padding(size * 0.1)
                .background(RoundedRectangle(cornerRadius: size * 0.26, style: .continuous).fill(Color(nsColor: .systemBlue)))
        case .aurora:
            BrandMark(outer: Color.white, inner: Brand.mint)
                .frame(width: size * 0.8, height: size * 0.8)
                .padding(size * 0.1)
                .background(RoundedRectangle(cornerRadius: size * 0.26, style: .continuous).fill(Brand.plate))
                .shadow(color: Color(red: 0.55, green: 0.40, blue: 1).opacity(0.5), radius: 6)
        case .neon:
            ZStack {
                RoundedRectangle(cornerRadius: 4, style: .continuous).fill(Color.black.opacity(0.65))
                RoundedRectangle(cornerRadius: 4, style: .continuous).strokeBorder(Neon.rim, lineWidth: 1.2)
                BrandMark(outer: Neon.magenta, inner: Neon.cyan, sparkle: Neon.cyan, trackOpacity: 0.25)
                    .frame(width: size * 0.72, height: size * 0.72)
            }
            .frame(width: size, height: size)
            .shadow(color: Neon.magenta.opacity(0.7), radius: 4)
            .shadow(color: Neon.cyan.opacity(0.5), radius: 10)
        }
    }
}

// MARK: 背景

/// 浅色多色渐变 + 光斑；不使用材质，保证离屏渲染稳定。
private struct AuroraShareBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.88, green: 0.93, blue: 1.0),
                                    Color(red: 0.93, green: 0.89, blue: 1.0),
                                    Color(red: 0.86, green: 0.97, blue: 0.98),
                                    Color(red: 1.0, green: 0.91, blue: 0.95)],
                           startPoint: .topLeading, endPoint: .bottomTrailing)
            Circle().fill(Color(red: 0.36, green: 0.42, blue: 1.0).opacity(0.30))
                .frame(width: 420, height: 420).blur(radius: 80).offset(x: -170, y: -230)
            Circle().fill(Color(red: 0.78, green: 0.32, blue: 0.98).opacity(0.26))
                .frame(width: 380, height: 380).blur(radius: 80).offset(x: 190, y: -80)
            Circle().fill(Color(red: 0.10, green: 0.86, blue: 0.80).opacity(0.24))
                .frame(width: 360, height: 360).blur(radius: 80).offset(x: -150, y: 260)
            Circle().fill(Color(red: 1.0, green: 0.45, blue: 0.55).opacity(0.24))
                .frame(width: 320, height: 320).blur(radius: 80).offset(x: 210, y: 300)
        }
        .clipped()
    }
}

/// 深色底 + 网格 + 边角光晕。
private struct NeonShareBackground: View {
    var body: some View {
        ZStack {
            Neon.ink
            RadialGradient(colors: [Neon.violet.opacity(0.40), .clear],
                           center: .topLeading, startRadius: 8, endRadius: 540)
            RadialGradient(colors: [Neon.cyan.opacity(0.20), .clear],
                           center: .bottomTrailing, startRadius: 8, endRadius: 500)
            Canvas { ctx, size in
                var grid = Path()
                var x: CGFloat = 0
                while x <= size.width {
                    grid.move(to: CGPoint(x: x, y: 0))
                    grid.addLine(to: CGPoint(x: x, y: size.height))
                    x += 36
                }
                var y: CGFloat = 0
                while y <= size.height {
                    grid.move(to: CGPoint(x: 0, y: y))
                    grid.addLine(to: CGPoint(x: size.width, y: y))
                    y += 36
                }
                ctx.stroke(grid, with: .color(Neon.cyan.opacity(0.09)), lineWidth: 0.6)
            }
        }
    }
}

// MARK: 渲染

/// 把分享卡离屏渲染成 PNG。优先 ImageRenderer（2x），失败时回退 1x 宿主视图路线。
@MainActor
enum ShareCardRenderer {
    struct Rendered {
        let png: Data
        /// 实际输出像素尺寸：宽度固定，高度由内容决定。
        let pixels: CGSize
    }

    /// 卡片实际逻辑尺寸：宽度固定，高度用宿主视图量出内容的理想高度。
    static func cardSize(data: ReportData, theme: PanelTheme) -> CGSize {
        let host = NSHostingView(rootView: ShareCard(data: data, theme: theme))
        host.layoutSubtreeIfNeeded()
        return host.fittingSize
    }

    static func render(data: ReportData, theme: PanelTheme, scale: CGFloat = 2) -> Rendered? {
        let size = cardSize(data: data, theme: theme)
        guard size.width > 0, size.height > 0 else { return nil }
        let card = ShareCard(data: data, theme: theme)
        let renderer = ImageRenderer(content: card)
        renderer.scale = scale
        renderer.isOpaque = true
        renderer.proposedSize = ProposedViewSize(size)
        if let cg = renderer.cgImage {
            let rep = NSBitmapImageRep(cgImage: cg)
            rep.size = size
            if let png = rep.representation(using: .png, properties: [:]) {
                return Rendered(png: png, pixels: CGSize(width: size.width * scale, height: size.height * scale))
            }
        }
        // 1x 兜底：与 PreviewRenderer 使用的宿主视图路线一致。
        let host = NSHostingView(rootView: card)
        host.frame = NSRect(origin: .zero, size: size)
        host.layoutSubtreeIfNeeded()
        guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return nil }
        host.cacheDisplay(in: host.bounds, to: rep)
        guard let png = rep.representation(using: .png, properties: [:]) else { return nil }
        return Rendered(png: png, pixels: size)
    }

    static func pngData(data: ReportData, theme: PanelTheme, scale: CGFloat = 2) -> Data? {
        render(data: data, theme: theme, scale: scale)?.png
    }
}
