import XCTest
@testable import AgentMeterBar

final class DoubaoTests: XCTestCase {
    func testBrandAndNames() {
        XCTAssertEqual(Catalog.brand("doubao").name, "豆包")
        XCTAssertEqual(Catalog.brand("doubao_work").name, "豆包工作")
        XCTAssertEqual(Catalog.shortName("doubao"), "豆包")
        XCTAssertEqual(Catalog.appLabel("doubao"), "豆包")
        XCTAssertEqual(Catalog.appLabel("doubao_work"), "豆包工作")
    }

    func testUnitsAndBuckets() throws {
        XCTAssertEqual(Catalog.unitLabel("doubao_points"), "点")
        let monthly = try JSONDecoder().decode(JSON.self, from: Data(#"{"bucket":"monthly_quota"}"#.utf8))
        let doubao = try JSONDecoder().decode(JSON.self, from: Data(#"{"bucket":"doubao_quota"}"#.utf8))
        XCTAssertEqual(Catalog.bucketLabel(monthly), "月度额度")
        XCTAssertEqual(Catalog.bucketLabel(doubao), "豆包额度")
    }

    func testWebProviderImportsAppCookies() throws {
        let provider = try XCTUnwrap(WebProvider.find("doubao"))
        XCTAssertTrue(provider.appImport)
        XCTAssertEqual(provider.cookieDomain, "doubao.com")
        XCTAssertTrue(Catalog.order.contains("doubao"))
    }

    func testReasonCopy() {
        XCTAssertEqual(Catalog.reason("doubao_credential_not_connected"), "未连接豆包")
        XCTAssertEqual(Catalog.reason("doubao_not_authenticated"), "豆包登录已过期")
        XCTAssertEqual(Catalog.reason("doubao_app_cookies_not_found"), "未找到豆包 App 的登录数据")
        XCTAssertEqual(Catalog.reason("unsupported_doubao_cookie_format"), "豆包登录数据格式暂未支持")
        XCTAssertEqual(Catalog.reason("doubao_work_sessions_not_found"), "未找到豆包工作会话")
    }

    func testActivityRowKeepsToolCallsWithoutTokens() throws {
        let json = try JSONDecoder().decode(JSON.self, from: Data(#"""
        {"app":"doubao_work","session_id":"s1","requests":3,"tool_calls":5,"counts_scope":"session_lifetime","tokens":null,"notes":"activity_only_no_token_ledger"}
        """#.utf8))
        let row = ActivityRow(json)
        XCTAssertEqual(row.app, "doubao_work")
        XCTAssertEqual(row.requests, 3)
        XCTAssertEqual(row.toolCalls, 5)
        XCTAssertEqual(row.countsScope, "session_lifetime")
        XCTAssertNil(row.tokens)
    }
}
