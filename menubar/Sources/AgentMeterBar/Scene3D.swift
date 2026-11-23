import AppKit
import Metal
import SceneKit
import SwiftUI

// Real-time 3D for the panel (SceneKit, Metal-backed, transparent background).
//
// One renderer, seven looks: the theme picks materials and lights through `Look3D`,
// never a different drawing path. Text always stays in SwiftUI on top of the 3D
// objects (crisp, selectable, accessible); the objects themselves carry depth that
// means something: gauge rings, medals, process topology.
//
// Cost model: views render on demand (no idle loops). Scenes that rotate on their
// own (the process constellation) run at 30 fps only while their window is on screen.

enum Scene3D {
    /// Without a Metal device the 2D gauges stay in place.
    static let device: MTLDevice? = MTLCreateSystemDefaultDevice()
    static var isAvailable: Bool { device != nil }
}

// MARK: - Look

/// Materials and lighting for one theme in one appearance.
struct Look3D {
    var dark: Bool
    var plate: NSColor
    var plateMetal: CGFloat
    var plateRough: CGFloat
    var plateCoat: CGFloat
    var track: NSColor
    var trackMetal: CGFloat
    var trackRough: CGFloat
    var fillMetal: CGFloat = 0
    var fillRough: CGFloat = 0.24
    var fillCoat: CGFloat = 0
    /// Emission of a lit tube, 0 (none) … 1.4 (neon).
    var glow: CGFloat
    /// Image-based lighting strength.
    var env: CGFloat
    /// Directional key light, in SceneKit lumens.
    var key: CGFloat
    /// Contact shadow opacity on the panel behind the object.
    var shadow: CGFloat
    /// How far the puck leans back, radians.
    var tilt: CGFloat
    /// Health colour pair (start, end) for a remaining percentage.
    var palette: (Double) -> (NSColor, NSColor)

    static func rgb(_ r: Double, _ g: Double, _ b: Double, _ a: Double = 1) -> NSColor {
        NSColor(srgbRed: r, green: g, blue: b, alpha: a)
    }

    /// Soft health colours shared by the glass, ceramic and metal looks.
    static func softHealth(_ remaining: Double) -> (NSColor, NSColor) {
        if remaining < 20 { return (rgb(1.0, 0.30, 0.36), rgb(1.0, 0.42, 0.75)) }
        if remaining < 50 { return (rgb(1.0, 0.70, 0.20), rgb(1.0, 0.48, 0.30)) }
        return (rgb(0.20, 0.88, 0.56), rgb(0.18, 0.80, 0.98))
    }

    static func neonHealth(_ remaining: Double) -> (NSColor, NSColor) {
        if remaining < 20 { return (rgb(1.0, 0.12, 0.40), rgb(1.0, 0.16, 0.82)) }
        if remaining < 50 { return (rgb(1.0, 0.92, 0.10), rgb(1.0, 0.45, 0.05)) }
        return (rgb(0.30, 1.0, 0.24), rgb(0.0, 0.94, 1.0))
    }
}

extension PanelTheme {
    func look3D(dark: Bool) -> Look3D {
        typealias L = Look3D
        switch self {
        case .minimal:
            return L(dark: dark,
                     plate: dark ? L.rgb(0.17, 0.17, 0.18) : L.rgb(1.0, 1.0, 1.0), plateMetal: 0, plateRough: 0.85, plateCoat: 0,
                     track: dark ? L.rgb(0.27, 0.27, 0.28) : L.rgb(0.78, 0.78, 0.80), trackMetal: 0, trackRough: 0.8,
                     fillRough: 0.5, glow: 0, env: dark ? 0.9 : 1.0, key: dark ? 700 : 480, shadow: dark ? 0.35 : 0.18, tilt: 0.30,
                     palette: { r in
                         let ink = dark ? L.rgb(0.94, 0.94, 0.95) : L.rgb(0.09, 0.09, 0.10)
                         if r < 20 { return (L.rgb(1.0, 0.27, 0.23), L.rgb(1.0, 0.27, 0.23)) }
                         if r < 50 { return (L.rgb(1.0, 0.62, 0.04), L.rgb(1.0, 0.62, 0.04)) }
                         return (ink, ink)
                     })
        case .native:
            return L(dark: dark,
                     plate: dark ? L.rgb(0.18, 0.19, 0.21) : L.rgb(1.0, 1.0, 1.0), plateMetal: 0, plateRough: 0.5, plateCoat: 0.3,
                     track: dark ? L.rgb(0.30, 0.31, 0.34) : L.rgb(0.76, 0.78, 0.82), trackMetal: 0, trackRough: 0.5,
                     fillRough: 0.3, fillCoat: 0.4, glow: 0.12, env: 1.0, key: dark ? 800 : 500, shadow: dark ? 0.4 : 0.2, tilt: 0.32,
                     palette: { r in
                         if r < 20 { let c = L.rgb(1.0, 0.27, 0.23); return (c, c) }
                         if r < 50 { let c = L.rgb(1.0, 0.62, 0.04); return (c, c) }
                         let c = L.rgb(0.20, 0.78, 0.35); return (c, c)
                     })
        case .porcelain:
            return L(dark: false,
                     plate: L.rgb(1.0, 1.0, 1.0), plateMetal: 0, plateRough: 0.22, plateCoat: 1,
                     track: L.rgb(0.72, 0.77, 0.87), trackMetal: 0, trackRough: 0.4,
                     fillRough: 0.2, fillCoat: 1, glow: 0.10, env: 1.0, key: 520, shadow: 0.22, tilt: 0.34,
                     palette: L.softHealth)
        case .aurora:
            return L(dark: dark,
                     plate: dark ? L.rgb(0.10, 0.12, 0.22) : L.rgb(1.0, 1.0, 1.0), plateMetal: dark ? 0.35 : 0, plateRough: 0.18, plateCoat: 1,
                     track: dark ? L.rgb(0.22, 0.25, 0.40) : L.rgb(0.70, 0.74, 0.88), trackMetal: 0, trackRough: dark ? 0.22 : 0.45,
                     fillRough: 0.18, fillCoat: 1, glow: dark ? 0.50 : 0.22, env: dark ? 1.05 : 1.0, key: dark ? 820 : 520,
                     shadow: dark ? 0.42 : 0.22, tilt: 0.34, palette: L.softHealth)
        case .titanium:
            return L(dark: true,
                     plate: L.rgb(0.62, 0.66, 0.70), plateMetal: 1, plateRough: 0.34, plateCoat: 0,
                     track: L.rgb(0.10, 0.12, 0.15), trackMetal: 0.9, trackRough: 0.30,
                     fillMetal: 0.0, fillRough: 0.16, fillCoat: 1, glow: 0.34, env: 1.25, key: 900, shadow: 0.45, tilt: 0.36,
                     palette: L.softHealth)
        case .neon:
            return L(dark: true,
                     plate: L.rgb(0.025, 0.012, 0.06), plateMetal: 0.4, plateRough: 0.55, plateCoat: 0,
                     track: L.rgb(0.20, 0.07, 0.28), trackMetal: 0, trackRough: 0.5,
                     fillRough: 0.35, glow: 1.25, env: 0.55, key: 520, shadow: 0.5, tilt: 0.30,
                     palette: L.neonHealth)
        case .prism:
            return L(dark: true,
                     plate: L.rgb(0.05, 0.06, 0.16), plateMetal: 0.7, plateRough: 0.14, plateCoat: 1,
                     track: L.rgb(0.20, 0.17, 0.42), trackMetal: 0.3, trackRough: 0.2,
                     fillMetal: 0.0, fillRough: 0.14, fillCoat: 1, glow: 0.85, env: 1.15, key: 800, shadow: 0.45, tilt: 0.34,
                     palette: L.neonHealth)
        }
    }
}

// MARK: - Environment

/// Procedural studio for reflections: a graded dome with a few softboxes. Cached per appearance.
@MainActor
enum Studio3D {
    private static var cache: [Bool: NSImage] = [:]

    static func environment(dark: Bool) -> NSImage {
        if let hit = cache[dark] { return hit }
        let size = CGSize(width: 1024, height: 512)
        let image = NSImage(size: size)
        image.lockFocus()
        if let ctx = NSGraphicsContext.current?.cgContext {
            // A light panel needs a bright studio, or ceramic and frosted glass read as dull grey.
            let top = dark ? 0.46 : 1.0, mid = dark ? 0.14 : 0.86, bottom = dark ? 0.03 : 0.58
            let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                                      colors: [NSColor(white: top, alpha: 1).cgColor, NSColor(white: mid, alpha: 1).cgColor,
                                               NSColor(white: bottom, alpha: 1).cgColor] as CFArray,
                                      locations: [0, 0.55, 1])!
            ctx.drawLinearGradient(gradient, start: CGPoint(x: 0, y: size.height), end: .zero, options: [])
            func softbox(_ rect: CGRect, _ alpha: CGFloat, tint: NSColor = .white) {
                tint.withAlphaComponent(alpha).setFill()
                NSBezierPath(roundedRect: rect, xRadius: 40, yRadius: 40).fill()
            }
            softbox(CGRect(x: 160, y: 300, width: 250, height: 130), dark ? 0.85 : 0.95)
            softbox(CGRect(x: 650, y: 250, width: 290, height: 170), dark ? 0.70 : 0.90, tint: NSColor(srgbRed: 0.86, green: 0.92, blue: 1, alpha: 1))
            softbox(CGRect(x: 400, y: 70, width: 330, height: 54), dark ? 0.28 : 0.45)
        }
        image.unlockFocus()
        cache[dark] = image
        return image
    }
}

// MARK: - Meshes

enum Mesh3D {
    /// A tube swept along a circular arc (angles in radians, counter-clockwise from +x).
    /// Optional vertex colours blend `colors.0` at `a0` into `colors.1` at `a1`.
    static func tubeArc(radius R: CGFloat, tube r: CGFloat, from a0: CGFloat, to a1: CGFloat,
                        segments: Int = 96, sides: Int = 24, colors: (NSColor, NSColor)? = nil) -> SCNGeometry {
        let segments = max(2, segments)
        var vertices: [SCNVector3] = [], normals: [SCNVector3] = [], indices: [Int32] = [], tints: [Float] = []
        vertices.reserveCapacity((segments + 1) * sides)
        let c0 = colors?.0.usingColorSpace(.sRGB), c1 = colors?.1.usingColorSpace(.sRGB)
        for i in 0...segments {
            let t = CGFloat(i) / CGFloat(segments)
            let a = a0 + (a1 - a0) * t
            let cx = R * cos(a), cy = R * sin(a)
            for j in 0..<sides {
                let b = 2 * CGFloat.pi * CGFloat(j) / CGFloat(sides)
                let n = SCNVector3(cos(a) * cos(b), sin(a) * cos(b), sin(b))
                vertices.append(SCNVector3(cx + r * n.x, cy + r * n.y, r * n.z))
                normals.append(n)
                if let c0, let c1 {
                    tints += [Float(c0.redComponent + (c1.redComponent - c0.redComponent) * t),
                              Float(c0.greenComponent + (c1.greenComponent - c0.greenComponent) * t),
                              Float(c0.blueComponent + (c1.blueComponent - c0.blueComponent) * t), 1]
                }
            }
        }
        for i in 0..<segments {
            for j in 0..<sides {
                let p = Int32(i * sides + j), q = Int32(i * sides + (j + 1) % sides)
                let s = Int32((i + 1) * sides + j), t = Int32((i + 1) * sides + (j + 1) % sides)
                indices += [p, s, q, q, s, t]
            }
        }
        var sources = [SCNGeometrySource(vertices: vertices), SCNGeometrySource(normals: normals)]
        if !tints.isEmpty {
            sources.append(SCNGeometrySource(data: tints.withUnsafeBufferPointer { Data(buffer: $0) }, semantic: .color,
                                             vectorCount: vertices.count, usesFloatComponents: true, componentsPerVector: 4,
                                             bytesPerComponent: MemoryLayout<Float>.size, dataOffset: 0,
                                             dataStride: MemoryLayout<Float>.size * 4))
        }
        return SCNGeometry(sources: sources, elements: [SCNGeometryElement(indices: indices, primitiveType: .triangles)])
    }

    /// A solid of revolution around the z axis. Each profile point carries its own normal so
    /// flats stay flat and bevels stay smooth.
    static func lathe(profile: [(r: CGFloat, z: CGFloat, nr: CGFloat, nz: CGFloat)], segments: Int = 96) -> SCNGeometry {
        var vertices: [SCNVector3] = [], normals: [SCNVector3] = [], indices: [Int32] = []
        let k = profile.count
        for i in 0...segments {
            let a = 2 * CGFloat.pi * CGFloat(i) / CGFloat(segments)
            let ca = cos(a), sa = sin(a)
            for p in profile {
                vertices.append(SCNVector3(p.r * ca, p.r * sa, p.z))
                normals.append(SCNVector3(p.nr * ca, p.nr * sa, p.nz))
            }
        }
        for i in 0..<segments {
            for j in 0..<(k - 1) {
                let a = Int32(i * k + j), b = Int32(i * k + j + 1)
                let c = Int32((i + 1) * k + j), d = Int32((i + 1) * k + j + 1)
                indices += [a, c, b, b, c, d]
            }
        }
        return SCNGeometry(sources: [SCNGeometrySource(vertices: vertices), SCNGeometrySource(normals: normals)],
                           elements: [SCNGeometryElement(indices: indices, primitiveType: .triangles)])
    }

    /// A flat disc with rounded edges, facing +z.
    static func puck(radius R: CGFloat, height h: CGFloat, bevel b: CGFloat, segments: Int = 96) -> SCNGeometry {
        var profile: [(r: CGFloat, z: CGFloat, nr: CGFloat, nz: CGFloat)] = [(0, h / 2, 0, 1)]
        let steps = 8
        for s in 0...steps {   // top bevel: normal swings from up to out
            let phi = (CGFloat.pi / 2) * (1 - CGFloat(s) / CGFloat(steps))
            profile.append((R - b + b * cos(phi), h / 2 - b + b * sin(phi), cos(phi), sin(phi)))
        }
        for s in 0...steps {   // bottom bevel: out to down
            let phi = -(CGFloat.pi / 2) * CGFloat(s) / CGFloat(steps)
            profile.append((R - b + b * cos(phi), -h / 2 + b + b * sin(phi), cos(phi), sin(phi)))
        }
        profile.append((0, -h / 2, 0, -1))
        return lathe(profile: profile, segments: segments)
    }
}

// MARK: - Materials

enum Material3D {
    static func pbr(_ color: NSColor, metal: CGFloat, rough: CGFloat, coat: CGFloat = 0,
                    emission: NSColor? = nil, glow: CGFloat = 0, vertexColors: Bool = false) -> SCNMaterial {
        let m = SCNMaterial()
        m.lightingModel = .physicallyBased
        m.diffuse.contents = vertexColors ? NSColor.white : color
        m.metalness.contents = metal
        m.roughness.contents = rough
        if coat > 0 {
            m.clearCoat.contents = coat
            m.clearCoatRoughness.contents = 0.06
        }
        if let emission, glow > 0 {
            m.emission.contents = emission
            m.emission.intensity = glow
        }
        m.isDoubleSided = true
        return m
    }
}

// MARK: - Lights and camera

enum Rig3D {
    /// Key light from the upper left, plus a cool rim from behind. Shadows land on `shadowCatcher`.
    @MainActor
    static func install(in scene: SCNScene, look: Look3D) {
        scene.background.contents = NSColor.clear
        scene.lightingEnvironment.contents = Studio3D.environment(dark: look.dark)
        scene.lightingEnvironment.intensity = look.env

        let key = SCNNode()
        key.light = SCNLight()
        key.light?.type = .directional
        key.light?.intensity = look.key
        key.light?.castsShadow = look.shadow > 0
        key.light?.shadowRadius = 7
        key.light?.shadowSampleCount = 8
        key.light?.shadowColor = NSColor(white: 0, alpha: look.shadow)
        key.light?.shadowMode = .deferred
        key.eulerAngles = SCNVector3(-0.85, -0.55, 0)
        key.name = "key"
        scene.rootNode.addChildNode(key)

        let rim = SCNNode()
        rim.light = SCNLight()
        rim.light?.type = .directional
        rim.light?.intensity = look.key * 0.35
        rim.light?.color = look.dark ? NSColor(srgbRed: 0.62, green: 0.72, blue: 1, alpha: 1) : NSColor(srgbRed: 0.85, green: 0.90, blue: 1, alpha: 1)
        rim.eulerAngles = SCNVector3(0.6, 2.6, 0)
        rim.name = "rim"
        scene.rootNode.addChildNode(rim)
    }

    /// An invisible plane that only receives shadows, so a floating object leaves a soft shadow on the panel.
    static func shadowCatcher(width: CGFloat, height: CGFloat, z: CGFloat) -> SCNNode {
        let plane = SCNPlane(width: width, height: height)
        let m = SCNMaterial()
        m.lightingModel = .shadowOnly
        plane.materials = [m]
        let node = SCNNode(geometry: plane)
        node.position = SCNVector3(0, 0, z)
        node.name = "shadowCatcher"
        return node
    }

    static func orthographicCamera(halfHeight: CGFloat, distance: CGFloat = 10) -> SCNNode {
        let node = SCNNode()
        node.camera = SCNCamera()
        node.camera?.usesOrthographicProjection = true
        node.camera?.orthographicScale = Double(halfHeight)
        node.camera?.zNear = 0.1
        node.camera?.zFar = 60
        node.position = SCNVector3(0, 0, distance)
        node.name = "camera"
        return node
    }

    static func perspectiveCamera(fov: CGFloat, distance: CGFloat) -> SCNNode {
        let node = SCNNode()
        node.camera = SCNCamera()
        node.camera?.fieldOfView = fov
        node.camera?.zNear = 0.1
        node.camera?.zFar = 200
        node.position = SCNVector3(0, 0, distance)
        node.name = "camera"
        return node
    }
}

// MARK: - SwiftUI host

/// A SceneKit view that never takes events: scrolling, hovering and clicking stay with the
/// SwiftUI layer above it (a scroll wheel over the 3D area must still scroll the panel).
///
/// It also stops rendering whenever its window is not visible: a popover that is closed keeps its
/// SwiftUI content alive, and a rotating scene must not keep the GPU awake behind it.
final class PassiveSceneView: SCNView {
    /// True for scenes that move on their own; they render at `preferredFramesPerSecond` while visible.
    var wantsContinuous = false { didSet { applyVisibility() } }
    private var observer: NSObjectProtocol?
    private var awakeUntil = Date.distantPast
    private var sleepTimer: Timer?

    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override var acceptsFirstResponder: Bool { false }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if let observer { NotificationCenter.default.removeObserver(observer) }
        observer = nil
        guard let window else { return }
        observer = NotificationCenter.default.addObserver(forName: NSWindow.didChangeOcclusionStateNotification, object: window,
                                                          queue: .main) { [weak self] _ in self?.applyVisibility() }
        applyVisibility()
    }

    deinit {
        if let observer { NotificationCenter.default.removeObserver(observer) }
        sleepTimer?.invalidate()
    }

    func applyVisibility() {
        let visible = window?.occlusionState.contains(.visible) ?? false
        rendersContinuously = wantsContinuous && visible
        // A playing SCNView redraws every frame even with nothing moving (measured: ~7% of a core), so an
        // on-demand scene plays only during a `wake`.
        isPlaying = wantsContinuous ? visible : (visible && Date() < awakeUntil)
    }

    /// Lets an on-demand scene run its animations for `seconds`, then returns it to zero idle cost.
    func wake(for seconds: TimeInterval) {
        guard !wantsContinuous else { return }
        awakeUntil = max(awakeUntil, Date().addingTimeInterval(seconds))
        applyVisibility()
        sleepTimer?.invalidate()
        sleepTimer = Timer.scheduledTimer(withTimeInterval: awakeUntil.timeIntervalSinceNow + 0.05, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.applyVisibility() }
        }
    }
}

struct SceneHost: NSViewRepresentable {
    let scene: SCNScene
    let camera: SCNNode
    /// True for scenes that move on their own; they render at `fps` while on screen.
    var continuous = false
    var fps = 30
    /// Hands the view to its scene model, which wakes it when something animates.
    var onMake: ((PassiveSceneView) -> Void)? = nil

    func makeNSView(context: Context) -> PassiveSceneView {
        let view = PassiveSceneView(frame: .zero)   // Metal is SceneKit's renderer on every supported macOS
        view.wantsLayer = true
        view.layer?.isOpaque = false
        view.backgroundColor = .clear
        view.antialiasingMode = .multisampling4X
        view.autoenablesDefaultLighting = false
        view.allowsCameraControl = false
        configure(view)
        view.scene = scene
        view.pointOfView = camera
        onMake?(view)
        return view
    }

    func updateNSView(_ view: PassiveSceneView, context: Context) {
        configure(view)
        if view.scene !== scene {
            view.scene = scene
            view.pointOfView = camera
        }
    }

    private func configure(_ view: PassiveSceneView) {
        view.preferredFramesPerSecond = continuous ? fps : 60
        view.wantsContinuous = continuous
    }
}

// MARK: - Offscreen snapshots

/// Renders a scene to an image without a view: used by the offline preview (GPU layers are not part of
/// `cacheDisplay`) and by share cards.
@MainActor
enum Snapshot3D {
    static func image(scene: SCNScene, camera: SCNNode, size: CGSize, scale: CGFloat = 2) -> NSImage? {
        guard let device = Scene3D.device else { return nil }
        let renderer = SCNRenderer(device: device, options: nil)
        renderer.scene = scene
        renderer.pointOfView = camera
        let pixels = CGSize(width: size.width * scale, height: size.height * scale)
        let image = renderer.snapshot(atTime: 0, with: pixels, antialiasingMode: .multisampling4X)
        image.size = size
        return image
    }
}
