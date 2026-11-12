import AppKit
import XCTest
@testable import AgentMeterBar

/// The experience pack: roaming geometry, drag-to-install plumbing, the pet photo in the share card and
/// opening the app behind a session. All pure logic — no window, no backend, no real installation.
final class PetRoamTests: XCTestCase {
    private let screen = CGRect(x: 0, y: 0, width: 1440, height: 900)
    private let size = CGSize(width: 320, height: 400)

    func testTargetsStayFullyInsideTheScreen() {
        var rng = SystemRandomNumberGenerator()
        let origins = [CGPoint(x: 0, y: 0), CGPoint(x: 1400, y: 880), CGPoint(x: 700, y: 400), CGPoint(x: -40, y: 1200)]
        for origin in origins {
            for _ in 0..<200 {
                let t = PetRoam.target(from: origin, size: size, screen: screen) { CGFloat.random(in: 0...1, using: &rng) }
                XCTAssertGreaterThanOrEqual(t.x, screen.minX)
                XCTAssertGreaterThanOrEqual(t.y, screen.minY)
                XCTAssertLessThanOrEqual(t.x + size.width, screen.maxX)
                XCTAssertLessThanOrEqual(t.y + size.height, screen.maxY)
            }
        }
    }

    func testTargetsStayNearbyAndLegsAreSlow() {
        let origin = CGPoint(x: 600, y: 300)
        var rng = SystemRandomNumberGenerator()
        for _ in 0..<200 {
            let t = PetRoam.target(from: origin, size: size, screen: screen) { CGFloat.random(in: 0...1, using: &rng) }
            XCTAssertLessThanOrEqual(abs(t.x - origin.x), PetRoam.reach + 0.001)
            XCTAssertLessThanOrEqual(abs(t.y - origin.y), PetRoam.reach * 0.6 + 0.001)
        }
        XCTAssertLessThanOrEqual(PetRoam.speed, 12, "a stroll, not a teleport")
        XCTAssertGreaterThanOrEqual(PetRoam.pauseRange.lowerBound, 3)
    }

    func testStepsAdvanceWithoutOvershootAndArrive() {
        let from = CGPoint(x: 100, y: 100), to = CGPoint(x: 103, y: 104)   // 5 points away
        let (mid, arrived) = PetRoam.step(from: from, to: to, dt: 0.1)
        XCTAssertFalse(arrived)
        XCTAssertEqual(hypot(mid.x - from.x, mid.y - from.y), PetRoam.speed * 0.1, accuracy: 0.001)
        let (end, done) = PetRoam.step(from: mid, to: to, dt: 10)
        XCTAssertTrue(done)
        XCTAssertEqual(end, to)
        let (same, still) = PetRoam.step(from: to, to: to, dt: 0.1)
        XCTAssertTrue(still)
        XCTAssertEqual(same, to)
        let (back, _) = PetRoam.step(from: from, to: to, dt: -1)
        XCTAssertEqual(back, from, "a negative clock never moves the pet backwards")
    }

    func testTinyScreensClampInsteadOfInverting() {
        let small = CGRect(x: 0, y: 0, width: 200, height: 300)
        let t = PetRoam.target(from: CGPoint(x: 50, y: 50), size: size, screen: small) { 0.5 }
        XCTAssertEqual(t.x, small.minX)
        XCTAssertEqual(t.y, small.minY)
    }
}

@MainActor
final class PetInstallerTests: XCTestCase {
    private var tmp: URL!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory.appendingPathComponent("pet-install-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: tmp) }

    func testOnlyAgentpetFilesAreAccepted() {
        let pet = URL(fileURLWithPath: "/tmp/my-pet.agentpet")
        XCTAssertTrue(PetInstaller.accepts([pet]))
        XCTAssertTrue(PetInstaller.accepts([pet, URL(fileURLWithPath: "/tmp/OTHER.AGENTPET")]))
        XCTAssertFalse(PetInstaller.accepts([]))
        XCTAssertFalse(PetInstaller.accepts([URL(fileURLWithPath: "/tmp/pet.zip")]))
        XCTAssertFalse(PetInstaller.accepts([pet, URL(fileURLWithPath: "/tmp/pet.zip")]))
    }

    func testTheToolIsFoundInResourcesFirstThenTheSourceCheckout() throws {
        let root = tmp.appendingPathComponent("Pet")
        let project = tmp.appendingPathComponent("project")
        try FileManager.default.createDirectory(at: root.appendingPathComponent("tools"), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: project.appendingPathComponent("pets/tools"), withIntermediateDirectories: true)
        let bundled = root.appendingPathComponent("tools/petpack.py")
        let checkout = project.appendingPathComponent("pets/tools/petpack.py")
        XCTAssertNil(PetInstaller.toolURL(root: root, project: project))
        try "# bundled".write(to: bundled, atomically: true, encoding: .utf8)
        XCTAssertEqual(PetInstaller.toolURL(root: root, project: project), bundled)
        try "# checkout".write(to: checkout, atomically: true, encoding: .utf8)
        XCTAssertEqual(PetInstaller.toolURL(root: root, project: project), bundled, "the bundled tool wins")
        XCTAssertEqual(PetInstaller.toolURL(root: nil, project: project), checkout)
    }

    func testPythonIsFoundOnThePathBeforeTheUsualPlaces() throws {
        let bin = tmp.appendingPathComponent("bin")
        try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true)
        let python = bin.appendingPathComponent("python3")
        try "#!/bin/sh\n".write(to: python, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: python.path)
        XCTAssertEqual(PetInstaller.pythonURL(environment: ["PATH": bin.path]), python)
        XCTAssertNotNil(PetInstaller.pythonURL(environment: [:]), "the usual install places are searched too")
    }

    func testInstalledNameComesFromTheToolsOwnAnswer() {
        XCTAssertEqual(PetInstaller.installedName("installed -> /Users/me/Library/Application Support/AgentMeter/pets/my-pet\n", fallback: "file"), "my-pet")
        XCTAssertEqual(PetInstaller.installedName("validated ok\ninstalled -> /pets/猫\n", fallback: "file"), "猫")
        XCTAssertEqual(PetInstaller.installedName("nothing useful", fallback: "file"), "file")
        XCTAssertEqual(PetInstaller.installedName("installed -> \n", fallback: "file"), "file")
    }

    func testFailuresKeepTheValidatorsWordsAndStayBounded() {
        XCTAssertEqual(PetInstaller.readableFailure("包里有符号链接：evil\n", stdout: ""), "包里有符号链接：evil")
        XCTAssertEqual(PetInstaller.readableFailure("", stdout: "fallback reason"), "fallback reason")
        XCTAssertEqual(PetInstaller.readableFailure("  \n", stdout: ""), "安装失败（校验器没有给出原因）。")
        XCTAssertEqual(PetInstaller.readableFailure(String(repeating: "x", count: 900), stdout: "").count, 400)
        let traceback = "Traceback (most recent call last):\n  File \"petpack.py\", line 1, in <module>\nzipfile.BadZipFile: File is not a zip file"
        XCTAssertEqual(PetInstaller.readableFailure(traceback, stdout: ""), "zipfile.BadZipFile: File is not a zip file")
    }
}

final class SharePetOptionTests: XCTestCase {
    func testThePetIsOffByDefaultAndSurvivesOldSavedOptions() throws {
        XCTAssertFalse(ShareOptions.compact.pet)
        XCTAssertFalse(ShareOptions.review.pet)
        let old = Data(#"{"mode":"review","costs":false,"peak":true}"#.utf8)
        let decoded = try JSONDecoder().decode(ShareOptions.self, from: old)
        XCTAssertFalse(decoded.pet)
        XCTAssertEqual(decoded.mode, .review)
        XCTAssertFalse(decoded.costs)
        XCTAssertTrue(decoded.qrCode)
    }

    func testTheChoiceRoundTrips() throws {
        var options = ShareOptions.compact
        options.pet = true
        let data = try JSONEncoder().encode(options)
        let back = try JSONDecoder().decode(ShareOptions.self, from: data)
        XCTAssertEqual(back, options)
        XCTAssertTrue(back.pet)
    }
}

@MainActor
final class AppLauncherSessionTests: XCTestCase {
    func testSessionAppsMapToTheirSources() {
        XCTAssertEqual(Catalog.applicationID("codex_images"), "codex")
        XCTAssertEqual(Catalog.applicationID("mcode"), "minimax_code")
        XCTAssertEqual(Catalog.applicationID("dsh"), "deepseek_harness")
        XCTAssertEqual(Catalog.applicationID("agy"), "antigravity")
        XCTAssertEqual(Catalog.applicationID("kimi_chat"), "kimi_desktop")
        XCTAssertEqual(Catalog.applicationID("claude"), "claude")
    }

    func testAnUninstalledAppGivesWordsNotACrash() {
        let message = AppLauncher.openApp(forApp: "codex", in: nil)
        XCTAssertNotNil(message)
        XCTAssertTrue(message?.contains("Codex") == true)
        XCTAssertNotNil(AppLauncher.openApp(forApp: "totally-unknown", in: nil))
    }

    func testAWebOnlySourceStillHasATarget() {
        let targets = AppLauncher.targets(for: "dreamina", in: nil)
        XCTAssertEqual(targets.count, 1)
        XCTAssertNil(targets[0].path)
        XCTAssertNotNil(targets[0].url)
    }
}

@MainActor
final class PetPhotoTests: XCTestCase {
    /// A 4x4 PNG with one opaque red pixel at (1, 2); everything else transparent.
    private func spottedImage() throws -> NSImage {
        let rep = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 4, pixelsHigh: 4, bitsPerSample: 8,
                                                 samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                                 colorSpaceName: .deviceRGB, bytesPerRow: 16, bitsPerPixel: 32))
        // setColor is a silent no-op on a premultiplied rep; write the pixel itself.
        let bytes = try XCTUnwrap(rep.bitmapData)
        bytes[2 * 16 + 1 * 4] = 255
        bytes[2 * 16 + 1 * 4 + 3] = 255
        let image = NSImage(size: NSSize(width: 4, height: 4))
        image.addRepresentation(rep)
        return image
    }

    func testTrimmingCutsToTheOpaqueBoundingBox() throws {
        let trimmed = try XCTUnwrap(PetThumbnails.trimmed(try spottedImage()))
        XCTAssertEqual(trimmed.size, NSSize(width: 1, height: 1))
        let rep = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(trimmed.tiffRepresentation)))
        XCTAssertEqual(rep.pixelsWide, 1)
        XCTAssertEqual(rep.pixelsHigh, 1)
    }

    func testAFullyTransparentPictureHasNothingToTrim() throws {
        let rep = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 2, pixelsHigh: 2, bitsPerSample: 8,
                                                 samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                                 colorSpaceName: .deviceRGB, bytesPerRow: 8, bitsPerPixel: 32))
        let image = NSImage(size: NSSize(width: 2, height: 2))
        image.addRepresentation(rep)
        XCTAssertNil(PetThumbnails.trimmed(image))
    }
}