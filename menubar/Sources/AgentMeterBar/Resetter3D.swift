import AppKit
import SceneKit
import SwiftUI

/// The Tibo resetter's body as a real object: chassis, screen bezel, dome button, knobs and antenna.
/// The LCD and its numbers stay in SwiftUI on top. One scene unit is one point, so the two line up.
struct Resetter3DChassis: View {
    let size: CGSize
    let pressed: Bool
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        if let image = Resetter3DRenderer.image(size: size, theme: theme, dark: scheme == .dark, pressed: pressed) {
            Image(nsImage: image).resizable().interpolation(.high)
                .frame(width: size.width, height: size.height)
                .id(pressed)
                .transition(.opacity)
                .accessibilityHidden(true)
        }
    }
}

@MainActor
enum Resetter3DRenderer {
    static let topHeight: CGFloat = 30
    static let knobColumn: CGFloat = 22
    private static var cache: [String: NSImage] = [:]

    private struct Paint {
        var shell: NSColor, shellMetal: CGFloat, shellRough: CGFloat
        var bezel: NSColor
        var button: NSColor, buttonGlow: CGFloat
        var knob: NSColor
        var light: NSColor
    }

    private static func paint(_ theme: PanelTheme, dark: Bool) -> Paint {
        let rgb = Look3D.rgb
        switch theme {
        case .minimal, .native:
            return Paint(shell: dark ? rgb(0.24, 0.25, 0.27, 1) : rgb(0.93, 0.94, 0.95, 1), shellMetal: 0, shellRough: 0.42,
                         bezel: rgb(0.10, 0.11, 0.13, 1), button: rgb(1, 0.23, 0.19, 1), buttonGlow: 0.12,
                         knob: rgb(0.72, 0.74, 0.77, 1), light: rgb(0.20, 0.82, 0.40, 1))
        case .porcelain:
            return Paint(shell: rgb(0.95, 0.96, 0.97, 1), shellMetal: 0, shellRough: 0.2,
                         bezel: rgb(0.20, 0.27, 0.38, 1), button: rgb(0.96, 0.50, 0.46, 1), buttonGlow: 0.14,
                         knob: rgb(0.74, 0.79, 0.86, 1), light: rgb(0.40, 0.82, 0.62, 1))
        case .aurora:
            return Paint(shell: dark ? rgb(0.21, 0.23, 0.46, 1) : rgb(0.80, 0.82, 1.0, 1), shellMetal: dark ? 0.45 : 0.05, shellRough: 0.2,
                         bezel: rgb(0.10, 0.10, 0.25, 1), button: rgb(1.0, 0.36, 0.66, 1), buttonGlow: 0.35,
                         knob: rgb(0.76, 0.76, 0.98, 1), light: rgb(0.20, 0.92, 0.72, 1))
        case .titanium:
            return Paint(shell: rgb(0.50, 0.54, 0.59, 1), shellMetal: 1, shellRough: 0.34,
                         bezel: rgb(0.12, 0.14, 0.17, 1), button: rgb(0.34, 0.62, 0.78, 1), buttonGlow: 0.25,
                         knob: rgb(0.70, 0.74, 0.78, 1), light: rgb(0.35, 0.92, 0.70, 1))
        case .neon, .prism:
            return Paint(shell: rgb(0.08, 0.05, 0.16, 1), shellMetal: 0.65, shellRough: 0.24,
                         bezel: rgb(0.0, 0.62, 0.72, 1), button: rgb(1.0, 0.12, 0.74, 1), buttonGlow: 0.95,
                         knob: rgb(0.20, 0.16, 0.34, 1), light: rgb(0.34, 1.0, 0.26, 1))
        }
    }

    static func image(size: CGSize, theme: PanelTheme, dark: Bool, pressed: Bool) -> NSImage? {
        guard size.width > 80, size.height > 60 else { return nil }
        let key = "\(theme.rawValue)-\(dark)-\(pressed)-\(Int(size.width))x\(Int(size.height))"
        if let hit = cache[key] { return hit }
        let (scene, camera) = makeScene(size: size, look: theme.look3D(dark: dark), paint: paint(theme, dark: dark), pressed: pressed)
        guard let image = Snapshot3D.image(scene: scene, camera: camera, size: size, scale: 3) else { return nil }
        if cache.count > 40 { cache.removeAll() }
        cache[key] = image
        return image
    }

    private static func makeScene(size: CGSize, look: Look3D, paint p: Paint, pressed: Bool) -> (SCNScene, SCNNode) {
        let scene = SCNScene()
        Rig3D.install(in: scene, look: look)
        scene.rootNode.childNode(withName: "key", recursively: false)?.light?.castsShadow = false
        let camera = Rig3D.orthographicCamera(halfHeight: size.height / 2, distance: 120)
        camera.camera?.zFar = 300
        scene.rootNode.addChildNode(camera)

        let W = size.width, H = size.height
        let bodyHeight = H - topHeight, bodyY = -H / 2 + bodyHeight / 2
        let root = SCNNode()
        scene.rootNode.addChildNode(root)

        func material(_ c: NSColor, metal: CGFloat = 0.1, rough: CGFloat = 0.3, coat: CGFloat = 0, glow: CGFloat = 0) -> SCNMaterial {
            Material3D.pbr(c, metal: metal, rough: rough, coat: coat, emission: glow > 0 ? c : nil, glow: glow)
        }

        let shell = SCNBox(width: W - 3, height: bodyHeight - 3, length: 24, chamferRadius: 11)
        shell.chamferSegmentCount = 8
        shell.materials = [material(p.shell, metal: p.shellMetal, rough: p.shellRough, coat: 0.8)]
        let shellNode = SCNNode(geometry: shell)
        shellNode.position = SCNVector3(0, bodyY, -12)
        root.addChildNode(shellNode)

        // A raised frame around the LCD; the SwiftUI screen sits exactly inside it.
        let screenWidth = W - 18 - 8 - knobColumn
        // Extruded rather than an SCNBox: a box clamps its corner radius to half its 4 pt depth.
        let bezelWidth = screenWidth + 5, bezelHeight = bodyHeight - 13, corner: CGFloat = p.buttonGlow > 0.8 ? 7 : 12
        let bezelPath = NSBezierPath(roundedRect: NSRect(x: -bezelWidth / 2, y: -bezelHeight / 2, width: bezelWidth, height: bezelHeight),
                                     xRadius: corner, yRadius: corner)
        bezelPath.flatness = 0.1
        let bezel = SCNShape(path: bezelPath, extrusionDepth: 4)
        bezel.chamferMode = .front
        bezel.chamferRadius = 1
        bezel.materials = [material(p.bezel, metal: 0.45, rough: 0.28, coat: 0.6, glow: p.buttonGlow > 0.8 ? 0.55 : 0)]
        let bezelNode = SCNNode(geometry: bezel)
        bezelNode.position = SCNVector3(-W / 2 + 9 + screenWidth / 2, bodyY, 0.5)
        root.addChildNode(bezelNode)

        let knobX = W / 2 - 9 - knobColumn / 2
        for (offset, angle) in [(CGFloat(14), pressed ? -1.05 : 0.7), (CGFloat(-10), -0.26)] {
            let knob = SCNNode(geometry: Mesh3D.puck(radius: 8.5, height: 7, bevel: 2, segments: 40))
            knob.geometry?.materials = [material(p.knob, metal: 0.85, rough: 0.26, coat: 0.5)]
            knob.position = SCNVector3(knobX, bodyY + offset, 3)
            let mark = SCNBox(width: 1.7, height: 6, length: 1, chamferRadius: 0.4)
            mark.materials = [material(p.bezel, metal: 0, rough: 0.5)]
            let markNode = SCNNode(geometry: mark)
            markNode.position = SCNVector3(0, 3.6, 3.8)
            let dial = SCNNode()
            dial.eulerAngles.z = CGFloat(angle)
            dial.addChildNode(markNode)
            knob.addChildNode(dial)
            root.addChildNode(knob)
        }

        for x in [-W / 2 + 7, W / 2 - 7] {
            let rivet = SCNSphere(radius: 1.9)
            rivet.segmentCount = 12
            rivet.materials = [material(p.knob, metal: 1, rough: 0.22)]
            let node = SCNNode(geometry: rivet)
            node.position = SCNVector3(x, bodyY + bodyHeight / 2 - 6, 0.5)
            root.addChildNode(node)
        }

        let deckY = bodyY + bodyHeight / 2
        let collar = SCNNode(geometry: Mesh3D.puck(radius: 30, height: 8, bevel: 2.5, segments: 64))
        collar.geometry?.materials = [material(p.knob, metal: 0.9, rough: 0.28, coat: 0.5)]
        collar.eulerAngles.x = -.pi / 2
        collar.position = SCNVector3(0, deckY + 1.5, -12)
        root.addChildNode(collar)

        let dome = SCNSphere(radius: 21)
        dome.segmentCount = 48
        dome.materials = [material(p.button, metal: 0, rough: 0.14, coat: 1, glow: p.buttonGlow)]
        let domeNode = SCNNode(geometry: dome)
        domeNode.scale = SCNVector3(1, pressed ? 0.42 : 0.78, 1)
        domeNode.position = SCNVector3(0, deckY + 5, -12)
        root.addChildNode(domeNode)

        let antennaX = -W / 2 + 22
        let mast = SCNCylinder(radius: 1.1, height: 19)
        mast.materials = [material(p.knob, metal: 1, rough: 0.25)]
        let mastNode = SCNNode(geometry: mast)
        mastNode.position = SCNVector3(antennaX, deckY + 8, -8)
        root.addChildNode(mastNode)
        let bulb = SCNSphere(radius: 4)
        bulb.segmentCount = 20
        bulb.materials = [material(p.light, metal: 0, rough: 0.16, coat: 1, glow: 0.8)]
        let bulbNode = SCNNode(geometry: bulb)
        bulbNode.position = SCNVector3(antennaX, deckY + 20, -8)
        root.addChildNode(bulbNode)

        // A slight lean shows the top of the case; the front face stays registered with the LCD.
        root.eulerAngles.x = 0.1
        return (scene, camera)
    }
}
