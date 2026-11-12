import CoreGraphics
import Foundation

/// The wandering walk as pure geometry, so "slow, nearby, never off screen" can be unit tested.
/// The controller owns the pauses (drag, interaction, quiet hours, sleep); this owns the steps.
enum PetRoam {
    /// Points per second: a stroll, not a teleport.
    static let speed: CGFloat = 7
    /// How far one leg may reach horizontally; vertical legs are shorter (the pet lives near the bottom).
    static let reach: CGFloat = 150
    static let pauseRange: ClosedRange<Double> = 4...12
    /// Seconds after a click / drag / menu before walking resumes.
    static let interactionPause: TimeInterval = 20

    /// A random nearby destination; the whole window stays inside the screen's visible frame.
    static func target(from origin: CGPoint, size: CGSize, screen: CGRect, random: () -> CGFloat) -> CGPoint {
        let maxX = max(screen.minX, screen.maxX - size.width)
        let maxY = max(screen.minY, screen.maxY - size.height)
        let x = origin.x + (random() * 2 - 1) * reach
        let y = origin.y + (random() * 2 - 1) * reach * 0.6
        return CGPoint(x: min(max(x, screen.minX), maxX), y: min(max(y, screen.minY), maxY))
    }

    /// One step toward the target; returns the new origin and whether the leg is done.
    static func step(from origin: CGPoint, to target: CGPoint, dt: Double) -> (point: CGPoint, arrived: Bool) {
        let dx = target.x - origin.x, dy = target.y - origin.y
        let distance = hypot(dx, dy)
        let move = speed * CGFloat(max(0, dt))
        if distance <= move || distance < 0.5 { return (target, true) }
        return (CGPoint(x: origin.x + dx / distance * move, y: origin.y + dy / distance * move), false)
    }
}