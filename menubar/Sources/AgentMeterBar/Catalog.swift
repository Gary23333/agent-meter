import SwiftUI

/// Display names, colours and Chinese copy for backend identifiers.
enum Catalog {
    struct Brand {
        let name: String
        let symbol: String
        let tint: Color
    }

    static let order = ["codex", "claude", "kimi", "qoder", "workbuddy", "trae_cn", "minimax_code", "minimax_design", "dreamina", "deepseek_api"]
    static let metricOrder = ["quota", "reset_time", "reset_cards", "credits", "tokens", "cost",
                              "renewal_time", "renewal_countdown", "renewal_amount",
                              "credit_refresh_time", "credit_refresh_countdown"]

    /// User order first (set in 调整顺序), then the built-in order.
    static func rank(_ id: String) -> Int {
        if let custom = UserDefaults.standard.stringArray(forKey: "sourceOrder"), let i = custom.firstIndex(of: id) {
            return i
        }
        let base = ConnectionManager.provider(ofSlot: id)
        return 10_000 + (order.firstIndex(of: base) ?? order.count) * 10 + ConnectionManager.order(ofSlot: id)
    }

    static func brand(_ id: String) -> Brand {
        if id.contains("#") { return brand(ConnectionManager.provider(ofSlot: id)) }
        switch id {
        case "codex": return Brand(name: "Codex", symbol: "chevron.left.forwardslash.chevron.right", tint: Color(red: 0.10, green: 0.66, blue: 0.52))
        case "claude": return Brand(name: "Claude Code", symbol: "staroflife.fill", tint: Color(red: 0.85, green: 0.47, blue: 0.34))
        case "kimi": return Brand(name: "Kimi Code", symbol: "moon.stars.fill", tint: Color(red: 0.24, green: 0.47, blue: 0.96))
        case "qoder": return Brand(name: "Qoder CN", symbol: "cube.fill", tint: .indigo)
        case "workbuddy": return Brand(name: "WorkBuddy", symbol: "person.2.fill", tint: Color(red: 0.13, green: 0.55, blue: 0.95))
        case "trae_cn": return Brand(name: "TRAE CN", symbol: "triangle.fill", tint: Color(red: 0.20, green: 0.80, blue: 0.55))
        case "minimax_code": return Brand(name: "MiniMax Code", symbol: "waveform", tint: Color(red: 0.95, green: 0.42, blue: 0.24))
        case "minimax_design": return Brand(name: "MiniMax Design", symbol: "paintpalette.fill", tint: Color(red: 0.93, green: 0.30, blue: 0.55))
        case "dreamina": return Brand(name: "即梦", symbol: "sparkles", tint: Color(red: 0.55, green: 0.36, blue: 0.96))
        case "deepseek_api": return Brand(name: "DeepSeek API", symbol: "fish.fill", tint: Color(red: 0.25, green: 0.42, blue: 0.95))
        case "ccswitch": return Brand(name: "CC Switch", symbol: "arrow.triangle.swap", tint: .orange)
        default:
            if id.hasPrefix("codexbar:") {
                let inner = brand(String(id.dropFirst("codexbar:".count)))
                return Brand(name: inner.name + " · CodexBar", symbol: inner.symbol, tint: inner.tint)
            }
            return Brand(name: id, symbol: "circle.grid.2x2.fill", tint: .gray)
        }
    }

    static func shortName(_ id: String) -> String {
        let id = ConnectionManager.provider(ofSlot: id)
        return ["codex": "Codex", "claude": "Claude", "kimi": "Kimi", "qoder": "Qoder", "workbuddy": "WorkBuddy", "trae_cn": "TRAE", "minimax_code": "MiniMax",
         "minimax_design": "Design", "dreamina": "即梦", "deepseek_api": "DeepSeek"][id]
            ?? brand(id).name
    }

    static func scopeLabel(_ scope: String) -> String {
        switch scope {
        case "account": return "订阅账户"
        case "api_account": return "API 账户"
        case "creative_account": return "创作账户"
        case "creative_personal_account": return "个人创作账户"
        case "local_imported_history": return "本机历史"
        default: return scope
        }
    }

    static func statusLabel(_ status: String) -> String {
        switch status {
        case "available": return "正常"
        case "partial": return "部分"
        case "not_provided": return "未提供"
        case "not_connected": return "未连接"
        case "not_supported": return "暂不支持"
        case "error": return "读取失败"
        case "stale": return "数据过期"
        default: return status
        }
    }

    static func statusColor(_ status: String) -> Color {
        switch status {
        case "available": return .green
        case "partial": return .teal
        case "stale": return .orange
        case "error": return .red
        case "not_connected": return Color.gray.opacity(0.75)
        default: return Color.secondary.opacity(0.4)
        }
    }

    static func reason(_ code: String?) -> String {
        guard let code else { return "" }
        let map: [String: String] = [
            "source_does_not_return_field": "来源未返回此项",
            "cli_not_available": "未找到命令行工具",
            "database_not_found": "未找到数据库",
            "not_authenticated": "未登录或登录已失效",
            "kimi_server_not_running": "Kimi 服务未运行",
            "kimi_server_token_missing": "Kimi 服务凭据缺失",
            "qoder_sdk_initialization_failed": "Qoder SDK 初始化失败",
            "qoder_sdk_not_installed": "未安装 Qoder SDK",
            "qoder_not_authenticated": "Qoder 未登录",
            "qoder_usage_unavailable": "Qoder 未返回用量",
            "minimax_credential_not_connected": "未填写 API Key，CC Switch 中也没有可用的 MiniMax 供应方",
            "deepseek_credential_not_connected": "未填写 API Key（在「连接网页账户 / API 密钥」里填写）",
            "dreamina_cli_not_available": "未找到即梦 CLI",
            "dreamina_not_authenticated": "即梦未登录",
            "design_gateway_not_ready": "MiniMax Design 未运行",
            "design_billing_scope_unavailable": "Design 计费范围不可用",
            "design_personal_scope_required": "需切换到个人账户",
            "design_account_changed_during_query": "查询中账户发生切换",
            "codexbar_not_installed": "未安装 CodexBar",
            "claude_not_logged_in": "Claude Code 未登录",
            "claude_subscription_login_missing": "未连接 Claude 账户，点「登录」用 claude.ai 账户连接",
            "claude_token_expired": "登录凭据已过期，使用一次 Claude Code 后自动恢复",
            "claude_keychain_denied": "钥匙串访问被拒绝",
            "claude_keychain_timeout": "等待钥匙串授权超时",
            "claude_keychain_unavailable": "无法访问钥匙串",
            "claude_usage_windows_missing": "未返回额度窗口",
            "connection_failed": "网络连接失败",
            "web_session_missing": "未登录网页账户",
            "disabled_by_user": "已在设置中关闭",
            "dreamina_subscription_cancelled": "已取消自动续费",
            "dreamina_no_scheduled_renewal": "没有已安排的续费",
            "claude_web_no_organization": "该账户没有可用的 Claude 组织",
            "workbuddy_api_error": "WorkBuddy 返回错误",
            "workbuddy_no_credit_packages": "没有积分包",
            "trae_no_credit_packs": "没有积分包",
            "unsupported_trae_contract": "TRAE 返回格式不支持",
            "unsupported_qoder_web_contract": "Qoder 返回格式不支持",
            "http_429": "请求过于频繁，稍后再试",
            "disabled_in_config": "已在配置中禁用",
            "adapter_not_implemented": "尚无适配器",
            "unexpected_source_error": "未知错误",
        ]
        return map[code] ?? code
    }

    static func bucketLabel(_ q: JSON) -> String {
        // Named windows that share a length (Claude's weekly model windows).
        let named = ["seven_day_opus": "7 天 Opus", "seven_day_sonnet": "7 天 Sonnet",
                     "seven_day_oauth_apps": "7 天 OAuth 应用"]
        if let b = q["bucket"].string, let n = named[b] { return n }
        if let minutes = q["window_minutes"].double { return Fmt.window(minutes: minutes) }
        if let d = q["window"]["duration"].double, let u = q["window"]["unit"].string {
            let unit = ["second": "秒", "minute": "分钟", "hour": "小时", "day": "天", "week": "周", "month": "个月"][u] ?? u
            return "\(Fmt.trim(d)) \(unit)"
        }
        let names = ["limit5h": "5 小时", "limit7d": "7 天", "monthTotal": "本月总量", "monthCode": "本月编程",
                     "5h": "5 小时", "week": "每周", "userQuota": "套餐额度", "addOnQuota": "加购额度",
                     "orgResourcePackage": "组织资源包", "totalQuota": "总额度", "sharedQuota": "共享额度", "credits": "积分", "primary": "主窗口", "secondary": "次窗口",
                     "tertiary": "第三窗口", "summary": "汇总"]
        let b = q["bucket"].string ?? ""
        return names[b] ?? (b.isEmpty ? "额度" : b)
    }

    static func unitLabel(_ unit: String?) -> String {
        switch unit {
        case "provider_credits", "dreamina_credits": return "积分"
        case "minimax_design_media_credits": return "媒体积分"
        case "workbuddy_credits", "trae_credits", "qoder_credits": return "积分"
        case "CNY": return "元"
        case "USD": return "美元"
        case nil: return ""
        default: return unit!
        }
    }

    static func appLabel(_ app: String) -> String {
        ["claude": "Claude", "codex": "Codex", "kimi": "Kimi Code", "gemini": "Gemini", "opencode": "OpenCode",
         "mcode": "MiniMax Code", "grokbuild": "Grok Build", "pi": "Pi"][app] ?? app
    }

    static func appTint(_ app: String) -> Color {
        switch app {
        case "claude": return Color(red: 0.85, green: 0.47, blue: 0.34)
        case "codex": return brand("codex").tint
        case "gemini": return .blue
        case "opencode": return .gray
        case "mcode": return brand("minimax_code").tint
        case "kimi": return brand("kimi").tint
        default: return .purple
        }
    }
}
