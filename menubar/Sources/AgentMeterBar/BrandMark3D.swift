import AppKit
import SceneKit
import SwiftUI

/// The AgentMeter mark as a real 3D object: a bevelled tile, two gauge tubes and an extruded sparkle.
/// It never moves, so it is rendered once per theme and appearance and shown as an image (no live GPU view).
struct BrandMark3D: View {
    var size: CGFloat = 34
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme

    @MainActor private static var cache: [String: NSImage] = [:]

    var body: some View {
        if let image = render() {
            Image(nsImage: image).resizable().interpolation(.high).frame(width: size, height: size)
        } else {
            Color.clear.frame(width: size, height: size)
        }
    }

    private func render() -> NSImage? {
        let key = "\(theme.rawValue)-\(scheme == .dark)-\(size)"
        if let hit = Self.cache[key] { return hit }
        let (scene, camera) = Self.scene(theme: theme, look: theme.look3D(dark: scheme == .dark))
        let image = Snapshot3D.image(scene: scene, camera: camera, size: CGSize(width: size, height: size), scale: 3)
        Self.cache[key] = image
        return image
    }

    private static func palette(_ theme: PanelTheme) -> (plate: [NSColor], outer: NSColor, inner: NSColor, spark: NSColor) {
        let white = NSColor.white
        let mint = Look3D.rgb(0.37, 0.95, 0.84)
        switch theme {
        case .minimal:
            return ([Look3D.rgb(0.16, 0.16, 0.17), Look3D.rgb(0.07, 0.07, 0.08)], white, Look3D.rgb(0.72, 0.72, 0.74), white)
        case .native:
            return ([Look3D.rgb(0.20, 0.56, 1.0), Look3D.rgb(0.04, 0.40, 0.92)], white, white, white)
        case .titanium:
            return ([Look3D.rgb(0.62, 0.67, 0.72), Look3D.rgb(0.27, 0.31, 0.36)], white, Look3D.rgb(0.55, 0.86, 1.0), white)
        case .neon, .prism:
            return ([Look3D.rgb(0.10, 0.06, 0.20), Look3D.rgb(0.03, 0.02, 0.08)], Look3D.rgb(1.0, 0.16, 0.82), Look3D.rgb(0.0, 0.94, 1.0), Look3D.rgb(0.0, 0.94, 1.0))
        case .porcelain, .aurora:
            return ([Look3D.rgb(0.36, 0.45, 1.0), Look3D.rgb(0.71, 0.36, 0.98)], white, mint, white)
        }
    }

    private static func gradient(_ colors: [NSColor]) -> NSImage {
        let image = NSImage(size: NSSize(width: 128, height: 128))
        image.lockFocus()
        NSGradient(colors: colors)?.draw(in: NSRect(x: 0, y: 0, width: 128, height: 128), angle: -45)
        image.unlockFocus()
        return image
    }

    private static func scene(theme: PanelTheme, look: Look3D) -> (SCNScene, SCNNode) {
        let scene = SCNScene()
        Rig3D.install(in: scene, look: look)
        scene.rootNode.childNode(withName: "key", recursively: false)?.light?.castsShadow = false
        let camera = Rig3D.orthographicCamera(halfHeight: 1.2)
        scene.rootNode.addChildNode(camera)
        let colors = palette(theme)

        let mark = SCNNode()
        mark.eulerAngles = SCNVector3(-0.24, 0.3, 0)
        scene.rootNode.addChildNode(mark)

        let tile = SCNBox(width: 1.9, height: 1.9, length: 0.34, chamferRadius: 0.17)
        tile.chamferSegmentCount = 8
        let face = Material3D.pbr(.white, metal: theme == .titanium ? 0.9 : 0.05, rough: theme == .titanium ? 0.34 : 0.24, coat: 1)
        face.diffuse.contents = gradient(colors.plate)
        tile.materials = [face]
        let tileNode = SCNNode(geometry: tile)
        tileNode.position.z = -0.17
        mark.addChildNode(tileNode)

        let start = CGFloat.pi * 1.25, sweep = CGFloat.pi * 1.5
        for (radius, tube, progress, color) in [(CGFloat(0.66), CGFloat(0.075), CGFloat(0.72), colors.outer),
                                                (CGFloat(0.42), CGFloat(0.062), CGFloat(0.46), colors.inner)] {
            let track = SCNNode(geometry: Mesh3D.tubeArc(radius: radius, tube: tube * 0.8, from: start - sweep, to: start, segments: 72, sides: 14))
            track.geometry?.materials = [Material3D.pbr(color.withAlphaComponent(0.28), metal: 0, rough: 0.4)]
            track.position.z = tube * 0.6
            mark.addChildNode(track)
            let end = start - sweep * progress
            let fill = SCNNode(geometry: Mesh3D.tubeArc(radius: radius, tube: tube, from: end, to: start, segments: 64, sides: 16))
            let lit = Material3D.pbr(color, metal: 0, rough: 0.2, coat: 1, emission: color, glow: 0.3)
            fill.geometry?.materials = [lit]
            fill.position.z = tube * 0.6
            mark.addChildNode(fill)
            for angle in [start, end] {
                let cap = SCNSphere(radius: tube)
                cap.segmentCount = 16
                cap.materials = [lit]
                let node = SCNNode(geometry: cap)
                node.position = SCNVector3(radius * cos(angle), radius * sin(angle), tube * 0.6)
                mark.addChildNode(node)
            }
        }

        let outline = Sparkle().path(in: CGRect(x: -0.24, y: -0.24, width: 0.48, height: 0.48)).cgPath
        let path = NSBezierPath(cgPath: outline)
        path.flatness = 0.004
        let spark = SCNShape(path: path, extrusionDepth: 0.1)
        spark.materials = [Material3D.pbr(colors.spark, metal: 0, rough: 0.18, coat: 1, emission: colors.spark, glow: 0.35)]
        let sparkNode = SCNNode(geometry: spark)
        sparkNode.position.z = 0.06
        mark.addChildNode(sparkNode)
        return (scene, camera)
    }
}
