import AppKit
import SceneKit
import SwiftUI

/// An earned medal as a real struck coin: scalloped metal body, raised ring, recessed field and an
/// embossed emblem. Poses are rendered once and cached, so a wall of medals costs no GPU at rest,
/// and hovering re-lights the actual geometry instead of sliding a highlight over a picture.
struct Medal3DDisc: View {
    let tier: MedalTier
    let symbol: String
    var ornate = false
    @Environment(\.tilt) private var tilt
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        // Thirteen steps per axis: finer than the eye can follow on a 52 pt coin.
        let qx = Int((tilt.x * 12).rounded()), qy = Int((tilt.y * 12).rounded())
        if let image = Medal3DRenderer.image(tier: tier, symbol: symbol, dark: scheme == .dark,
                                             scale: ornate ? 9 : 3, stepX: qx, stepY: qy) {
            Image(nsImage: image).resizable().interpolation(.high)
                .shadow(color: .black.opacity(scheme == .dark ? 0.45 : 0.24), radius: 3,
                        x: -CGFloat(qx) * 0.2, y: 2.5 - CGFloat(qy) * 0.15)
                .accessibilityHidden(true)
        } else {
            Color.clear
        }
    }
}

@MainActor
enum Medal3DRenderer {
    private struct Stage {
        let scene: SCNScene
        let camera: SCNNode
        let coin: SCNNode
    }

    private static let maxImages = 320
    private static var stages: [String: Stage] = [:]
    private static var images: [String: NSImage] = [:]
    private static var renderer: SCNRenderer?

    static func image(tier: MedalTier, symbol: String, dark: Bool, scale: CGFloat, stepX: Int, stepY: Int) -> NSImage? {
        let stageKey = "\(tier.rawValue)|\(symbol)|\(dark)"
        let key = "\(stageKey)|\(scale)|\(stepX)|\(stepY)"
        if let hit = images[key] { return hit }
        guard let device = Scene3D.device else { return nil }
        let stage = stages[stageKey] ?? makeStage(tier: tier, symbol: symbol, dark: dark)
        stages[stageKey] = stage

        SCNTransaction.begin()
        SCNTransaction.disableActions = true
        stage.coin.eulerAngles = SCNVector3(-0.24 + CGFloat(stepY) / 12 * 0.95, 0.30 + CGFloat(stepX) / 12 * 0.95, 0)
        SCNTransaction.commit()
        SCNTransaction.flush()

        let active = renderer ?? SCNRenderer(device: device, options: nil)
        renderer = active
        active.scene = stage.scene
        active.pointOfView = stage.camera
        let side = 52 * scale
        let image = active.snapshot(atTime: 0, with: CGSize(width: side, height: side), antialiasingMode: .multisampling4X)
        image.size = NSSize(width: 52, height: 52)
        if images.count >= maxImages { images.removeAll(keepingCapacity: true) }
        images[key] = image
        return image
    }

    private static func metal(_ tier: MedalTier) -> (deep: NSColor, bright: NSColor, field: NSColor) {
        let c = tier.colors.map { NSColor($0).usingColorSpace(.sRGB) ?? .gray }
        // The recessed field sits between the mid and bright metal, or it reads as a dark inlay.
        return (c[0], c[1], c[2].blended(withFraction: 0.45, of: c[1]) ?? c[2])
    }

    private static func makeStage(tier: MedalTier, symbol: String, dark: Bool) -> Stage {
        let scene = SCNScene()
        let look = PanelTheme.aurora.look3D(dark: dark)
        Rig3D.install(in: scene, look: look)
        scene.rootNode.childNode(withName: "key", recursively: false)?.light?.castsShadow = false
        scene.lightingEnvironment.intensity = dark ? 1.5 : 1.25
        let camera = Rig3D.orthographicCamera(halfHeight: 1.14)
        scene.rootNode.addChildNode(camera)

        let colors = metal(tier)
        let coin = SCNNode()
        scene.rootNode.addChildNode(coin)

        let outline = NSBezierPath(cgPath: Scallop(points: 24, depth: 0.045)
            .path(in: CGRect(x: -1, y: -1, width: 2, height: 2)).cgPath)
        outline.flatness = 0.003
        let body = SCNShape(path: outline, extrusionDepth: 0.2)
        body.chamferMode = .both
        body.chamferRadius = 0.035
        body.materials = [Material3D.pbr(colors.bright, metal: 1, rough: 0.26, coat: 0.7)]
        coin.addChildNode(SCNNode(geometry: body))

        let field = SCNNode(geometry: Mesh3D.puck(radius: 0.79, height: 0.05, bevel: 0.018, segments: 72))
        field.geometry?.materials = [Material3D.pbr(colors.field, metal: 1, rough: 0.46)]
        field.position.z = 0.095
        coin.addChildNode(field)

        let ring = SCNNode(geometry: Mesh3D.tubeArc(radius: 0.80, tube: 0.045, from: 0, to: 2 * .pi, segments: 96, sides: 12))
        ring.geometry?.materials = [Material3D.pbr(colors.bright, metal: 1, rough: 0.16, coat: 1)]
        ring.position.z = 0.125
        coin.addChildNode(ring)

        let bead = SCNSphere(radius: 0.017)
        bead.segmentCount = 8
        bead.materials = [Material3D.pbr(colors.deep, metal: 1, rough: 0.32)]
        for i in 0..<36 {
            let angle = CGFloat(i) / 36 * 2 * .pi
            let node = SCNNode(geometry: bead)
            node.position = SCNVector3(0.68 * cos(angle), 0.68 * sin(angle), 0.125)
            coin.addChildNode(node)
        }

        addEmblem(symbol, to: coin, top: colors.bright, side: colors.deep)
        return Stage(scene: scene, camera: camera, coin: coin)
    }

    /// Stacks the symbol's silhouette into a solid relief: SF Symbols have no mesh, but under a tilted
    /// camera these close layers read and light as an extruded shape.
    private static func addEmblem(_ symbol: String, to coin: SCNNode, top: NSColor, side: NSColor) {
        guard let sideMask = symbolImage(symbol, color: side), let topMask = symbolImage(symbol, color: top) else { return }
        let plane = SCNPlane(width: 0.96, height: 0.96)
        let layers = 9
        for i in 0..<layers {
            let isTop = i == layers - 1
            let geometry = plane.copy() as? SCNPlane ?? plane
            let material = Material3D.pbr(.white, metal: 1, rough: isTop ? 0.2 : 0.4, coat: isTop ? 1 : 0)
            material.diffuse.contents = isTop ? topMask : sideMask
            material.transparent.contents = isTop ? topMask : sideMask
            material.transparencyMode = .aOne
            material.writesToDepthBuffer = false
            material.isDoubleSided = false
            geometry.materials = [material]
            let node = SCNNode(geometry: geometry)
            node.position.z = 0.13 + CGFloat(i) * 0.011
            node.renderingOrder = 10 + i
            coin.addChildNode(node)
        }
    }

    private static func symbolImage(_ name: String, color: NSColor) -> NSImage? {
        let config = NSImage.SymbolConfiguration(pointSize: 150, weight: .bold)
            .applying(NSImage.SymbolConfiguration(paletteColors: [color]))
        guard let glyph = NSImage(systemSymbolName: name, accessibilityDescription: nil)?.withSymbolConfiguration(config) else { return nil }
        let side: CGFloat = 320
        let canvas = NSImage(size: NSSize(width: side, height: side))
        canvas.lockFocus()
        let fit = min(side * 0.92 / glyph.size.width, side * 0.92 / glyph.size.height)
        let size = NSSize(width: glyph.size.width * fit, height: glyph.size.height * fit)
        glyph.draw(in: NSRect(x: (side - size.width) / 2, y: (side - size.height) / 2, width: size.width, height: size.height))
        canvas.unlockFocus()
        return canvas
    }
}
