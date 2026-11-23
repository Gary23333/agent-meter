import AppKit
import SceneKit
import SwiftUI

// The cockpit's real-3D gauges: one glass/ceramic/metal puck per account, quota windows as
// concentric tubes (shortest window outside), lit and shadowed by one shared rig.

struct GaugeSpec: Equatable, Identifiable {
    let id: String
    /// Remaining percent per window, shortest window (outer ring) first. At most three are drawn.
    let remaining: [Double]
}

/// One tube gauge ring: a dark track, a lit fill and the two rounded ends.
/// Not main-actor isolated on purpose: SceneKit runs custom actions on its own thread, and the only
/// state they touch is the scene graph, which SceneKit synchronises.
private final class RingNode {
    static let start = CGFloat.pi * 1.25          // 225°: the gauge opens at the bottom, like the logo
    static let sweep = CGFloat.pi * 1.5           // 270°

    let root = SCNNode()
    private let fill = SCNNode()
    private let originCap = SCNNode()
    private let tipCap = SCNNode()
    private let radius: CGFloat
    private let tube: CGFloat
    private let zc: CGFloat
    private let look: Look3D
    private(set) var remaining: Double

    init(radius: CGFloat, tube: CGFloat, remaining: Double, look: Look3D) {
        self.radius = radius
        self.tube = tube
        self.zc = tube * 0.45
        self.look = look
        self.remaining = remaining

        let track = SCNNode(geometry: Mesh3D.tubeArc(radius: radius, tube: tube * 0.9, from: Self.start - Self.sweep, to: Self.start,
                                                    segments: 110, sides: 20))
        track.geometry?.materials = [Material3D.pbr(look.track, metal: look.trackMetal, rough: look.trackRough)]
        track.position.z = zc
        root.addChildNode(track)
        root.addChildNode(fill)
        root.addChildNode(originCap)
        root.addChildNode(tipCap)
        for cap in [originCap, tipCap] {
            let sphere = SCNSphere(radius: tube)
            sphere.segmentCount = 24
            cap.geometry = sphere
        }
        apply(progress: Self.fraction(remaining), colorFor: remaining)
    }

    static func fraction(_ remaining: Double) -> Double { min(max(remaining / 100, 0.012), 1) }

    /// Shows `progress` (0…1) of the sweep. The colour follows `colorFor`, the percentage the health palette reads.
    private func apply(progress p: Double, colorFor value: Double) {
        let (base, accent) = look.palette(value)
        let a0 = Self.start - Self.sweep * CGFloat(p)
        let segments = max(6, Int(110 * p))
        fill.geometry = Mesh3D.tubeArc(radius: radius, tube: tube, from: a0, to: Self.start, segments: segments, sides: 24,
                                       colors: (accent, base))
        fill.geometry?.materials = [Material3D.pbr(base, metal: look.fillMetal, rough: look.fillRough, coat: look.fillCoat,
                                                   emission: base, glow: look.glow, vertexColors: true)]
        fill.position.z = zc
        originCap.geometry?.materials = [Material3D.pbr(base, metal: look.fillMetal, rough: look.fillRough, coat: look.fillCoat,
                                                        emission: base, glow: look.glow)]
        tipCap.geometry?.materials = [Material3D.pbr(accent, metal: look.fillMetal, rough: look.fillRough, coat: look.fillCoat,
                                                     emission: accent, glow: look.glow)]
        originCap.position = SCNVector3(radius * cos(Self.start), radius * sin(Self.start), zc)
        tipCap.position = SCNVector3(radius * cos(a0), radius * sin(a0), zc)
    }

    /// Moves the fill to `value`; animated changes ease out like a needle settling.
    func update(remaining value: Double, animated: Bool) {
        let from = Self.fraction(remaining), to = Self.fraction(value)
        remaining = value
        fill.removeAction(forKey: "sweep")
        guard animated, abs(from - to) > 0.004 else {
            apply(progress: to, colorFor: value)
            return
        }
        let duration: TimeInterval = 0.9
        fill.runAction(SCNAction.customAction(duration: duration) { [weak self] _, elapsed in
            guard let self else { return }
            let t = min(1, Double(elapsed) / duration)
            let eased = 1 - pow(1 - t, 3)
            self.apply(progress: from + (to - from) * eased, colorFor: value)
        }, forKey: "sweep")
    }
}

@MainActor
final class GaugeSceneModel {
    let scene = SCNScene()
    let camera: SCNNode
    weak var view: PassiveSceneView?
    private let content = SCNNode()
    private var pucks: [SCNNode] = []
    private var rings: [[RingNode]] = []
    private var structure: [Int] = []
    private var signature = ""
    private var spacing: CGFloat = 0
    private var tilt: CGFloat = 0.34
    private var cellHeight: CGFloat = 2.3

    init() {
        camera = Rig3D.orthographicCamera(halfHeight: 1.15)
        scene.rootNode.addChildNode(camera)
        scene.rootNode.addChildNode(content)
    }

    private static func layout(_ count: Int) -> (radii: [CGFloat], tube: CGFloat) {
        switch count {
        case 1: return ([0.80], 0.11)
        case 2: return ([0.84, 0.58], 0.085)
        default: return ([0.87, 0.67, 0.47], 0.06)
        }
    }

    /// `spacing` is the horizontal distance between gauge centres in scene units (the view's cell aspect decides it).
    func configure(_ specs: [GaugeSpec], look: Look3D, signature: String, spacing: CGFloat, animated: Bool) {
        view?.wake(for: animated ? 1.1 : 0.2)
        let shape = specs.map { min($0.remaining.count, 3) }
        if signature == self.signature, shape == structure, spacing == self.spacing, !pucks.isEmpty {
            for (i, spec) in specs.enumerated() {
                for (j, value) in spec.remaining.prefix(3).enumerated() { rings[i][j].update(remaining: value, animated: animated) }
            }
            return
        }
        self.signature = signature
        self.structure = shape
        self.spacing = spacing
        self.tilt = look.tilt
        rebuild(specs, look: look, animated: animated)
    }

    private func rebuild(_ specs: [GaugeSpec], look: Look3D, animated: Bool) {
        content.childNodes.forEach { $0.removeFromParentNode() }
        for name in ["key", "rim"] { scene.rootNode.childNode(withName: name, recursively: false)?.removeFromParentNode() }
        Rig3D.install(in: scene, look: look)
        pucks = []
        rings = []
        let n = CGFloat(specs.count)
        for (i, spec) in specs.enumerated() {
            let puck = SCNNode()
            puck.position = SCNVector3((CGFloat(i) - (n - 1) / 2) * spacing, 0, 0)
            puck.eulerAngles = SCNVector3(-look.tilt, 0, 0)

            let plate = SCNNode(geometry: Mesh3D.puck(radius: 1.04, height: 0.2, bevel: 0.08))
            plate.geometry?.materials = [Material3D.pbr(look.plate, metal: look.plateMetal, rough: look.plateRough, coat: look.plateCoat)]
            plate.position.z = -0.1
            puck.addChildNode(plate)

            let values = Array(spec.remaining.prefix(3))
            let (radii, tube) = Self.layout(values.count)
            var row: [RingNode] = []
            for (j, value) in values.enumerated() {
                let ring = RingNode(radius: radii[j], tube: tube, remaining: animated ? 0 : value, look: look)
                puck.addChildNode(ring.root)
                row.append(ring)
            }
            content.addChildNode(puck)
            pucks.append(puck)
            rings.append(row)
            if animated {
                for (j, value) in values.enumerated() { row[j].update(remaining: value, animated: true) }
            }
        }
        content.addChildNode(Rig3D.shadowCatcher(width: n * spacing + 2, height: 3.4, z: -0.9))
    }

    /// The pointer over gauge `index` (unit square, y up) turns that puck toward it and lifts it a little.
    func hover(index: Int?, unit: CGPoint = .zero) {
        view?.wake(for: 0.35)
        SCNTransaction.begin()
        SCNTransaction.animationDuration = 0.18
        SCNTransaction.animationTimingFunction = CAMediaTimingFunction(name: .easeOut)
        for (i, puck) in pucks.enumerated() {
            if i == index {
                puck.eulerAngles = SCNVector3(-(tilt + unit.y * 0.2), unit.x * 0.3, 0)
                puck.position.z = 0.35
                puck.scale = SCNVector3(1.05, 1.05, 1.05)
            } else {
                puck.eulerAngles = SCNVector3(-tilt, 0, 0)
                puck.position.z = 0
                puck.scale = SCNVector3(1, 1, 1)
            }
        }
        SCNTransaction.commit()
    }
}

/// The 3D layer of the cockpit. Labels and click targets are SwiftUI views the parent lays over it.
struct Gauge3DStrip: View {
    let model: GaugeSceneModel
    let specs: [GaugeSpec]
    let cellWidth: CGFloat
    let height: CGFloat
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme

    private var look: Look3D { theme.look3D(dark: scheme == .dark) }
    private var signature: String { "\(theme.rawValue)-\(scheme == .dark ? "d" : "l")" }
    /// Scene units between gauge centres: the camera shows 2.3 units over `height` points.
    private var spacing: CGFloat { 2.3 * cellWidth / height }

    var body: some View {
        let size = CGSize(width: cellWidth * CGFloat(max(specs.count, 1)), height: height)
        Group {
            if PanelView.expandForPreview {
                snapshot(size)
            } else {
                SceneHost(scene: model.scene, camera: model.camera, onMake: { model.view = $0 })
                    .onAppear { configure(animated: true) }
                    .onChange(of: specs) { _, _ in configure(animated: true) }
                    .onChange(of: signature) { _, _ in configure(animated: false) }
            }
        }
        .frame(width: size.width, height: size.height)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func configure(animated: Bool) {
        model.configure(specs, look: look, signature: signature, spacing: spacing, animated: animated)
    }

    @ViewBuilder private func snapshot(_ size: CGSize) -> some View {
        let still = GaugeSceneModel()
        let _ = still.configure(specs, look: look, signature: signature, spacing: spacing, animated: false)
        if let image = Snapshot3D.image(scene: still.scene, camera: still.camera, size: size) {
            Image(nsImage: image).resizable().interpolation(.high)
        } else {
            Color.clear
        }
    }
}
