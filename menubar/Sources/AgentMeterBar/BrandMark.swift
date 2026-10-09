import SwiftUI

/// The AgentMeter mark (docs/images/logo/agentmeter-icon.svg): two 270° gauge
/// rings (5-hour outside, 7-day inside) around an agent sparkle. All sizes are
/// fractions of the frame, taken from the SVG's 824-unit plate.
struct BrandMark<Outer: ShapeStyle, Inner: ShapeStyle>: View {
    var outer: Outer
    var inner: Inner
    var sparkle: Color = .white
    var trackOpacity: Double = 0.2

    var body: some View {
        GeometryReader { geo in
            let s = min(geo.size.width, geo.size.height)
            ZStack {
                ring(diameter: 580 / 824 * s, width: 64 / 824 * s, progress: 0.72, style: outer)
                ring(diameter: 380 / 824 * s, width: 52 / 824 * s, progress: 0.46, style: inner)
                Sparkle().fill(sparkle).frame(width: 186 / 824 * s, height: 186 / 824 * s)
            }
            .offset(y: 43 / 824 * s)
            .frame(width: geo.size.width, height: geo.size.height)
        }
    }

    private func ring<S: ShapeStyle>(diameter: CGFloat, width: CGFloat, progress: CGFloat, style: S) -> some View {
        let stroke = StrokeStyle(lineWidth: width, lineCap: .round)
        // Circle trims start at 3 o'clock and run clockwise; rotate so the gauge opens at the bottom.
        return ZStack {
            Circle().trim(from: 0, to: 0.75).stroke(style, style: stroke).opacity(trackOpacity)
            Circle().trim(from: 0, to: 0.75 * progress).stroke(style, style: stroke)
        }
        .rotationEffect(.degrees(135))
        .frame(width: diameter, height: diameter)
    }
}

/// Four-point star with concave sides.
struct Sparkle: Shape {
    func path(in r: CGRect) -> Path {
        let c = CGPoint(x: r.midX, y: r.midY)
        let w = r.width, h = r.height
        func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: c.x + x * w, y: c.y + y * h) }
        var p = Path()
        p.move(to: pt(0, -0.5))
        p.addCurve(to: pt(0.5, 0), control1: pt(0.048, -0.172), control2: pt(0.172, -0.048))
        p.addCurve(to: pt(0, 0.5), control1: pt(0.172, 0.048), control2: pt(0.048, 0.172))
        p.addCurve(to: pt(-0.5, 0), control1: pt(-0.048, 0.172), control2: pt(-0.172, 0.048))
        p.addCurve(to: pt(0, -0.5), control1: pt(-0.172, -0.048), control2: pt(-0.048, -0.172))
        p.closeSubpath()
        return p
    }
}

enum Brand {
    static let plate = LinearGradient(colors: [Color(red: 0x5B / 255, green: 0x74 / 255, blue: 1),
                                               Color(red: 0xB4 / 255, green: 0x5C / 255, blue: 0xFA / 255)],
                                      startPoint: .topLeading, endPoint: .bottomTrailing)
    static let mint = LinearGradient(colors: [Color(red: 0x5F / 255, green: 0xF2 / 255, blue: 0xD6 / 255),
                                              Color(red: 0xB8 / 255, green: 1, blue: 0xF0 / 255)],
                                     startPoint: .bottomLeading, endPoint: .topTrailing)
}
