import SwiftUI

// MARK: - Tilt environment

/// How far the pointer pulls a tilting trophy, -0.5…0.5 on each axis. Inner
/// layers read it to move at different depths (parallax) and to draw edges.
private struct TiltKey: EnvironmentKey {
    static let defaultValue = CGPoint.zero
}

extension EnvironmentValues {
    var tilt: CGPoint {
        get { self[TiltKey.self] }
        set { self[TiltKey.self] = newValue }
    }
}

extension View {
    /// Moves a layer with the tilt; positive depth comes toward the viewer.
    func parallax(_ tilt: CGPoint, depth: CGFloat) -> some View {
        offset(x: tilt.x * depth, y: tilt.y * depth)
    }
}

// MARK: - Particles

/// Deterministic pseudo-random numbers, so particles never jump between frames.
struct Seeded {
    private var state: UInt64
    init(_ seed: Int) { state = UInt64(truncatingIfNeeded: seed &* 2_654_435_761 &+ 97) }
    mutating func next() -> Double {
        state = state &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
        return Double(state >> 11) / Double(1 << 53)
    }
}

/// Particles on a tilted 3D ring around a trophy. Draw the `.back` half behind
/// the trophy and the `.front` half over it, so the ring passes through.
struct OrbitParticles: View {
    enum Half { case back, front }
    let color: Color
    var count = 36
    var radius: CGFloat = 120
    var tilt: CGPoint = .zero
    let half: Half

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 40, paused: Motion.isStatic)) { context in
            let t = Motion.isStatic ? 1.2 : context.date.timeIntervalSinceReferenceDate
            Canvas { ctx, size in
                let c = CGPoint(x: size.width / 2, y: size.height / 2)
                var rng = Seeded(11)
                for i in 0..<count {
                    let lane = rng.next()
                    let speed = 0.25 + rng.next() * 0.35
                    let a = Double(i) / Double(count) * 2 * .pi + t * speed
                    let r = radius * (0.82 + 0.3 * lane)
                    // Ring leans with the pointer.
                    let lean = 0.28 + Double(tilt.y) * 0.5
                    let z = sin(a)
                    if (half == .back) != (z < 0) { continue }
                    let x = c.x + CGFloat(cos(a)) * r + tilt.x * CGFloat(z) * 18
                    let y = c.y + CGFloat(z * lean) * r - CGFloat(lane - 0.5) * 30
                    let depth = (z + 1) / 2   // 0 far … 1 near
                    let s = CGFloat(0.8 + 1.8 * depth)
                    var glow = ctx
                    glow.opacity = 0.25 + 0.75 * depth
                    let rect = CGRect(x: x - s, y: y - s, width: s * 2, height: s * 2)
                    glow.fill(Path(ellipseIn: rect.insetBy(dx: -s * 1.6, dy: -s * 1.6)), with: .color(color.opacity(0.18)))
                    glow.fill(Path(ellipseIn: rect), with: .color(.white))
                }
            }
        }
        .allowsHitTesting(false)
    }
}

/// Glowing sparks thrown out from the center once, when `start` changes.
struct SparkBurst: View {
    let colors: [Color]
    let start: Date
    var count = 46
    var duration = 1.1

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 60, paused: Motion.isStatic)) { context in
            let t = context.date.timeIntervalSince(start)
            Canvas { ctx, size in
                guard t >= 0, t < duration, !Motion.isStatic else { return }
                let c = CGPoint(x: size.width / 2, y: size.height * 0.36)
                var rng = Seeded(5)
                let p = t / duration
                let ease = 1 - pow(1 - p, 3)
                for i in 0..<count {
                    let a = rng.next() * 2 * .pi
                    let dist = (60 + rng.next() * 160) * ease
                    let len = 10 * (1 - p) + 2
                    let from = CGPoint(x: c.x + CGFloat(cos(a) * dist), y: c.y + CGFloat(sin(a) * dist))
                    let to = CGPoint(x: c.x + CGFloat(cos(a) * (dist - len)), y: c.y + CGFloat(sin(a) * (dist - len)))
                    var line = Path()
                    line.move(to: from)
                    line.addLine(to: to)
                    ctx.stroke(line, with: .color(colors[i % colors.count].opacity(1 - p)), style: StrokeStyle(lineWidth: 2, lineCap: .round))
                }
            }
        }
        .allowsHitTesting(false)
    }
}

/// Slow drifting dust that shifts against the pointer for depth.
struct FloatingDust: View {
    let color: Color
    var count = 28
    var shift: CGPoint = .zero

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: Motion.isStatic)) { context in
            let t = Motion.isStatic ? 0 : context.date.timeIntervalSinceReferenceDate
            Canvas { ctx, size in
                var rng = Seeded(23)
                for _ in 0..<count {
                    let depth = rng.next()
                    let x0 = rng.next() * Double(size.width), y0 = rng.next() * Double(size.height)
                    let speed = 4 + rng.next() * 10
                    let phase = rng.next() * 6
                    let x = (x0 + sin(t * 0.3 + phase) * 10 - Double(shift.x) * 30 * depth)
                    var y = (y0 - t * speed).truncatingRemainder(dividingBy: Double(size.height))
                    if y < 0 { y += Double(size.height) }
                    y -= Double(shift.y) * 20 * depth
                    let r = 0.6 + depth * 1.8
                    let twinkle = 0.35 + 0.65 * (0.5 + 0.5 * sin(t * 2 + phase * 3))
                    ctx.fill(Path(ellipseIn: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2)),
                             with: .color(color.opacity(0.18 + 0.5 * depth * twinkle)))
                }
            }
        }
        .allowsHitTesting(false)
    }
}

/// Reports the pointer over a view as -0.5…0.5 per axis (zero when it leaves).
struct PointerTracker: ViewModifier {
    @Binding var pointer: CGPoint
    @State private var size: CGSize = .zero

    func body(content: Content) -> some View {
        content
            .background(GeometryReader { geo in
                Color.clear.onAppear { size = geo.size }.onChange(of: geo.size) { _, s in size = s }
            })
            .onContinuousHover(coordinateSpace: .local) { phase in
                guard case .active(let p) = phase, size.width > 0 else {
                    withAnimation(.spring(response: 0.6, dampingFraction: 0.9)) { pointer = .zero }
                    return
                }
                let next = CGPoint(x: p.x / size.width - 0.5, y: p.y / size.height - 0.5)
                guard abs(next.x - pointer.x) > 0.01 || abs(next.y - pointer.y) > 0.01 else { return }
                withAnimation(.interactiveSpring(response: 0.5, dampingFraction: 0.9)) { pointer = next }
            }
    }
}

// MARK: - 3D energy rings

/// Two glowing rings spinning in 3D behind a trophy, leaning toward the pointer.
struct EnergyRings: View {
    let colors: [Color]
    var tilt: CGPoint = .zero
    @State private var spin = false

    var body: some View {
        ZStack {
            ring(width: 250, line: 2.2, opacity: 0.55, axis: (x: 1, y: 0.15, z: 0), angle: 72, speed: spin ? 360 : 0)
            ring(width: 210, line: 1.2, opacity: 0.4, axis: (x: 0.3, y: 1, z: 0), angle: 64, speed: spin ? -360 : 0)
            ring(width: 290, line: 0.8, opacity: 0.25, axis: (x: 1, y: -0.4, z: 0), angle: 78, speed: spin ? 180 : 0)
        }
        .rotation3DEffect(.degrees(Double(tilt.x) * 30), axis: (x: 0, y: 1, z: 0))
        .rotation3DEffect(.degrees(Double(-tilt.y) * 30), axis: (x: 1, y: 0, z: 0))
        .onAppear {
            guard !Motion.isStatic else { return }
            withAnimation(.linear(duration: 14).repeatForever(autoreverses: false)) { spin = true }
        }
        .allowsHitTesting(false)
    }

    private func ring(width: CGFloat, line: CGFloat, opacity: Double, axis: (x: CGFloat, y: CGFloat, z: CGFloat),
                      angle: Double, speed: Double) -> some View {
        Circle()
            .stroke(AngularGradient(colors: [colors[1].opacity(0), colors[1], .white, colors[1], colors[1].opacity(0)], center: .center),
                    style: StrokeStyle(lineWidth: line, lineCap: .round))
            .rotationEffect(.degrees(speed))
            .frame(width: width, height: width)
            .rotation3DEffect(.degrees(angle), axis: axis, perspective: 0.6)
            .shadow(color: colors[1].opacity(0.8), radius: 4)
            .opacity(opacity)
    }
}
