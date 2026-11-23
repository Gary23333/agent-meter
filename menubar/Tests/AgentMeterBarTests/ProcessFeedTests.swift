import XCTest
@testable import AgentMeterBar

final class ProcessFeedTests: XCTestCase {
    private func row(_ pid: Double, kind: String, core: Bool = false) -> JSON {
        .object(["pid": .number(pid), "ppid": .number(1), "depth": .number(1), "name": .string("p"), "command": .string("p"),
                 "kind": .string(kind), "ports": .array([.number(5173)]), "core": .bool(core)])
    }

    func testCoresFoldIntoTheHeaderAndUnknownKindsStayOther() {
        let feed = ProcessFeed(.object([
            "status": .string("available"),
            "harnesses": .array([.object(["app": .string("codex"), "pid": .number(9), "alive": .bool(true),
                                          "processes": .array([row(10, kind: "harness", core: true), row(11, kind: "future")])])]),
            "totals": .object(["harness_count": .number(1), "process_count": .number(1)]),
        ]))
        XCTAssertTrue(feed.isAvailable)
        XCTAssertEqual(feed.groups[0].rows.map(\.pid), [11])
        XCTAssertEqual(feed.groups[0].rows[0].kind, .other)
        XCTAssertEqual(feed.groups[0].rows[0].ports, [5173])
    }

    func testLeftoversOfAnExitedHarnessHaveNoPid() {
        let group = HarnessGroup(.object(["app": .string("claude"), "pid": .null, "alive": .bool(false)]))
        XCTAssertNil(group.pid)
        XCTAssertFalse(group.alive)
    }

    func testFormats() {
        XCTAssertEqual(ProcessFormat.memory(1_572_864), "2 MB")
        XCTAssertEqual(ProcessFormat.cpu(262.4), "262%")
        XCTAssertEqual(ProcessFormat.uptime(3_660), "1 时 1 分")
    }
}
