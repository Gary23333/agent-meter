import AppKit
import SceneKit
import SwiftUI

// The process constellation: every harness is a glowing core, every process it started a node in orbit.
// Depth carries meaning: distance from the core is how many forks away a process is, a node's size is its
// memory and its glow is its CPU. Leftovers of a harness that has exited drift as hollow wireframes.

struct ConstellationNode: Equatable {
    let pid: Int
    /// nil when the process hangs directly below the harness core.
    let parent: Int?
    let kind: ProcessKind
    let cpu: Double
    let rss: Double
}

struct ConstellationGroup: Equatable, Identifiable {
    let id: String
    let tint: NSColor
    let alive: Bool
    let nodes: [ConstellationNode]
}

@MainActor
final class ConstellationSceneModel {
    let scene = SCNScene()
    let camera: SCNNode
    private let world = SCNNode()
    private var signature = ""
    private var yaw: CGFloat = 0.5
    private var pitch: CGFloat = -0.32

    init() {
        camera = Rig3D.perspectiveCamera(fov: 30, distance: 9)
        scene.rootNode.addChildNode(camera)
        scene.rootNode.addChildNode(world)
        applyRotation()
    }

    // MARK: Layout

    /// Even directions on a sphere (golden-angle spiral); `phase` keeps two clusters from looking identical.
    private static func fibonacci(_ i: Int, _ n: Int, phase: CGFloat) -> SCNVector3 {
        let y = 1 - 2 * (CGFloat(i) + 0.5) / CGFloat(max(n, 1))
        let r = sqrt(max(0, 1 - y * y))
        let a = CGFloat(i) * 2.399963 + phase
        return SCNVector3(cos(a) * r, y, sin(a) * r)
    }

    private static func normalized(_ v: SCNVector3) -> SCNVector3 {
        let l = sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        return l < 1e-6 ? SCNVector3(0, 1, 0) : SCNVector3(v.x / l, v.y / l, v.z / l)
    }

    /// Positions relative to the core and the cluster's horizontal / vertical reach. Clusters are lens-shaped
    /// (orbits around a core), which keeps a row of them inside a wide, short view.
    private static func layout(_ group: ConstellationGroup) -> (positions: [Int: SCNVector3], reach: CGFloat, height: CGFloat) {
        var kids: [Int?: [ConstellationNode]] = [:]
        for n in group.nodes { kids[n.parent, default: []].append(n) }
        let phase = CGFloat(abs(group.id.hashValue % 628)) / 100
        var positions: [Int: SCNVector3] = [:]
        var reach: CGFloat = 0.8, height: CGFloat = 0.5
        func flatten(_ v: SCNVector3) -> SCNVector3 { normalized(SCNVector3(v.x, v.y * 0.42, v.z)) }
        func place(parent: Int?, origin: SCNVector3, depth: Int) {
            let list = kids[parent] ?? []
            for (k, node) in list.enumerated() {
                let spread = fibonacci(k, list.count, phase: phase + CGFloat(depth))
                var dir = flatten(spread)
                if depth > 1 {
                    let out = normalized(origin)
                    dir = flatten(SCNVector3(out.x * 0.9 + spread.x * 0.7, out.y * 0.9 + spread.y * 0.7, out.z * 0.9 + spread.z * 0.7))
                }
                let dist: CGFloat = depth == 1 ? 1.15 + CGFloat(node.pid % 5) * 0.03 : 0.6 * pow(0.9, CGFloat(depth - 2))
                let p = SCNVector3(origin.x + dir.x * dist, origin.y + dir.y * dist, origin.z + dir.z * dist)
                positions[node.pid] = p
                reach = max(reach, sqrt(p.x * p.x + p.z * p.z) + 0.25)
                height = max(height, abs(p.y) + 0.25)
                if depth < 8 { place(parent: node.pid, origin: p, depth: depth + 1) }
            }
        }
        place(parent: nil, origin: SCNVector3(0, 0, 0), depth: 1)
        return (positions, reach, height)
    }

    // MARK: Build

    func configure(_ groups: [ConstellationGroup], look: Look3D, signature: String, spin: Bool) {
        guard signature != self.signature else { return }
        self.signature = signature
        world.childNodes.forEach { $0.removeFromParentNode() }
        for name in ["key", "rim"] { scene.rootNode.childNode(withName: name, recursively: false)?.removeFromParentNode() }
        Rig3D.install(in: scene, look: look)
        scene.lightingEnvironment.intensity = look.dark ? look.env * 0.9 : look.env * 0.6   // a bright studio flattens small spheres

        let layouts = groups.map { Self.layout($0) }
        let n = groups.count
        let cellW = (layouts.map(\.reach).max() ?? 0.8) * 2 + 0.4
        let cellH = (layouts.map(\.height).max() ?? 0.5) * 2 + 0.9
        // Up to three clusters share one row; more go in two rows, the back row a little deeper.
        let rows = n > 3 ? 2 : 1
        let cols = Int((Double(n) / Double(rows)).rounded(.up))
        var reachX = cellW * CGFloat(cols) / 2
        // The world leans back by `pitch`, so a cluster's horizontal reach adds to its apparent height.
        let lean = abs(sin(pitch))
        var reachY = (layouts.map(\.height).max() ?? 0.5) * cos(pitch) + (layouts.map(\.reach).max() ?? 0.8) * lean + 0.2
        if rows == 2 { reachY += cellH / 2 }
        for (index, group) in groups.enumerated() {
            let row = rows == 1 ? 0 : index / cols, col = rows == 1 ? index : index % cols
            let inRow = rows == 1 ? n : min(cols, n - row * cols)
            let cluster = SCNNode()
            cluster.position = SCNVector3((CGFloat(col) - CGFloat(inRow - 1) / 2) * cellW,
                                          rows == 1 ? 0 : (row == 0 ? cellH / 2 : -cellH / 2),
                                          rows == 1 ? 0 : (row == 0 ? 0.4 : -0.6))
            build(group, positions: layouts[index].positions, in: cluster, look: look)
            if spin {
                let turn = SCNAction.rotateBy(x: 0, y: .pi * 2, z: 0, duration: 46 + Double(index) * 7)
                cluster.runAction(.repeatForever(turn), forKey: "spin")
            } else {
                cluster.eulerAngles.y = 0.6 + CGFloat(index) * 0.9
            }
            world.addChildNode(cluster)
        }
        reachX *= 1.12
        reachY *= 1.12
        // Fit the widest extent in view: the camera sits as far back as the arrangement needs.
        let fov = (camera.camera?.fieldOfView ?? 30) * .pi / 180
        let aspect: CGFloat = 2.2
        let needed = max(reachX / aspect, reachY) / tan(fov / 2)
        camera.position = SCNVector3(0, 0, max(4.5, needed))
    }

    private func build(_ group: ConstellationGroup, positions: [Int: SCNVector3], in cluster: SCNNode, look: Look3D) {
        let maxRss = max(group.nodes.map(\.rss).max() ?? 1, 1)
        // The core: a glossy sphere in the harness colour, or a hollow ghost when the harness has gone.
        let core = SCNNode(geometry: SCNSphere(radius: 0.5))
        (core.geometry as? SCNSphere)?.segmentCount = 48
        if group.alive {
            core.geometry?.materials = [Material3D.pbr(group.tint, metal: 0.1, rough: 0.18, coat: 1, emission: group.tint, glow: look.dark ? 0.35 + look.glow * 0.3 : 0.12)]
            let halo = SCNNode(geometry: SCNSphere(radius: 0.8))
            let glow = SCNMaterial()
            glow.lightingModel = .constant
            glow.diffuse.contents = group.tint.withAlphaComponent(look.dark ? 0.14 : 0.16)
            glow.blendMode = look.dark ? .add : .alpha
            glow.writesToDepthBuffer = false
            halo.geometry?.materials = [glow]
            core.addChildNode(halo)
        } else {
            let ghost = SCNMaterial()
            ghost.lightingModel = .constant
            ghost.diffuse.contents = NSColor(white: look.dark ? 0.75 : 0.35, alpha: 0.5)
            ghost.fillMode = .lines
            core.geometry?.materials = [ghost]
        }
        cluster.addChildNode(core)
        // An orbit line at the first shell: where the harness's own children circle.
        if !group.nodes.isEmpty {
            let orbit = SCNTorus(ringRadius: 1.17, pipeRadius: 0.005)
            orbit.ringSegmentCount = 96
            orbit.pipeSegmentCount = 6
            let line = SCNMaterial()
            line.lightingModel = .constant
            line.diffuse.contents = (group.alive ? group.tint : NSColor.gray).withAlphaComponent(look.dark ? 0.32 : 0.40)
            line.writesToDepthBuffer = false
            orbit.materials = [line]
            cluster.addChildNode(SCNNode(geometry: orbit))
        }

        for node in group.nodes {
            guard let p = positions[node.pid] else { continue }
            let size = 0.05 + 0.13 * sqrt(node.rss / maxRss)
            let sphere = SCNSphere(radius: CGFloat(size))
            sphere.segmentCount = 28
            let color = node.kind.nsColor
            let heat = min(1, node.cpu / 50)
            let body = SCNNode(geometry: sphere)
            body.position = p
            if group.alive {
                body.geometry?.materials = [Material3D.pbr(color, metal: 0.05, rough: 0.22, coat: 0.7, emission: color, glow: (look.dark ? 0.12 : 0.04) + CGFloat(heat) * (look.dark ? 1.1 : 0.45))]
            } else {
                let ghost = SCNMaterial()
                ghost.lightingModel = .constant
                ghost.diffuse.contents = color.withAlphaComponent(0.55)
                ghost.fillMode = .lines
                body.geometry?.materials = [ghost]
            }
            cluster.addChildNode(body)
            if heat > 0.25 {                       // busy processes get a soft halo
                let halo = SCNNode(geometry: SCNSphere(radius: CGFloat(size) * (1.7 + CGFloat(heat))))
                let glow = SCNMaterial()
                glow.lightingModel = .constant
                glow.diffuse.contents = color.withAlphaComponent((look.dark ? 0.10 : 0.12) + 0.14 * CGFloat(heat))
                glow.blendMode = look.dark ? .add : .alpha
                glow.writesToDepthBuffer = false
                halo.geometry?.materials = [glow]
                body.addChildNode(halo)
            }
            let from = node.parent.flatMap { positions[$0] } ?? SCNVector3(0, 0, 0)
            cluster.addChildNode(Self.edge(from: from, to: p, color: color, solid: group.alive))
        }
    }

    private static func edge(from a: SCNVector3, to b: SCNVector3, color: NSColor, solid: Bool) -> SCNNode {
        let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z
        let length = sqrt(dx * dx + dy * dy + dz * dz)
        let cylinder = SCNCylinder(radius: 0.013, height: max(length, 0.001))
        cylinder.radialSegmentCount = 8
        let m = SCNMaterial()
        m.lightingModel = .constant
        m.diffuse.contents = color.withAlphaComponent(solid ? 0.38 : 0.22)
        m.writesToDepthBuffer = false
        cylinder.materials = [m]
        let node = SCNNode(geometry: cylinder)
        node.position = SCNVector3((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2)
        node.look(at: b, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 1, 0))
        return node
    }

    // MARK: Drag

    private func applyRotation() {
        world.eulerAngles = SCNVector3(pitch, yaw, 0)
    }

    /// Dragging turns the whole constellation; the clusters keep spinning on their own axes.
    func drag(dx: CGFloat, dy: CGFloat) {
        yaw += dx * 0.012
        pitch = min(0.7, max(-1.1, pitch + dy * 0.012))
        applyRotation()
    }
}

/// The constellation view. A drag turns it; with nothing to show it rests as a dim core.
struct ProcessConstellation: View {
    let groups: [ConstellationGroup]
    let height: CGFloat
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme
    @State private var model = ConstellationSceneModel()
    @State private var lastDrag: CGSize = .zero

    private var look: Look3D { theme.look3D(dark: scheme == .dark) }
    private var signature: String {
        "\(theme.rawValue)-\(scheme == .dark ? "d" : "l")-" + groups.map { g in
            g.id + (g.alive ? "+" : "-") + g.nodes.map { "\($0.pid):\($0.parent ?? 0):\($0.kind.rawValue):\(Int($0.cpu / 10)):\(Int($0.rss / 4_000_000))" }.joined(separator: ",")
        }.joined(separator: "|")
    }

    var body: some View {
        ZStack {
            if PanelView.expandForPreview {
                snapshot
            } else {
                SceneHost(scene: model.scene, camera: model.camera, continuous: true, fps: 30)
                    .onAppear { model.configure(groups, look: look, signature: signature, spin: true) }
                    .onChange(of: signature) { _, _ in model.configure(groups, look: look, signature: signature, spin: true) }
                Color.clear.contentShape(Rectangle())
                    .gesture(DragGesture(minimumDistance: 2)
                        .onChanged { v in
                            model.drag(dx: v.translation.width - lastDrag.width, dy: v.translation.height - lastDrag.height)
                            lastDrag = v.translation
                        }
                        .onEnded { _ in lastDrag = .zero })
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: height)
        .accessibilityHidden(true)
    }

    @ViewBuilder private var snapshot: some View {
        GeometryReader { geo in
            let still = ConstellationSceneModel()
            let _ = still.configure(groups, look: look, signature: signature, spin: false)
            if let image = Snapshot3D.image(scene: still.scene, camera: still.camera, size: CGSize(width: max(geo.size.width, 100), height: height)) {
                Image(nsImage: image).resizable().interpolation(.high)
            }
        }
    }
}
