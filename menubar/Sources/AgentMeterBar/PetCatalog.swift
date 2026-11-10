import Foundation

/// How a state looks in the panel: the colour family of its dot and chip.
enum PetStateTone: Equatable {
    case calm, active, warn, danger, quiet
}

/// One thing the pet can show, in words: what to call it and what makes it happen for real.
struct PetStateInfo: Identifiable, Equatable {
    let id: String
    let label: String
    let symbol: String
    let tone: PetStateTone
    let trigger: String
}

/// What the 桌宠 tab lets the user try. The ids are the animation names of the pet runtime
/// (`pets/runtime/js/constants.js`) and the states of the backend brain (`agent_meter/pet.py`); a Python test
/// keeps the three lists identical, so a state added in one place cannot silently be missing here.
enum PetCatalog {
    static let states: [PetStateInfo] = [
        .init(id: "idle", label: "待机", symbol: "face.smiling", tone: .calm,
              trigger: "没有任务在跑、额度也充足时的日常模样；闲久了会挠挠头、打个哈欠。"),
        .init(id: "working", label: "干活中", symbol: "keyboard", tone: .active,
              trigger: "有 1～2 个 Agent 会话正在运行（本机会话记录，或 hooks 报来的）。"),
        .init(id: "busy", label: "忙翻了", symbol: "bolt.fill", tone: .active,
              trigger: "同时有 3 个以上会话在运行。"),
        .init(id: "waiting", label: "等你确认", symbol: "hand.raised.fill", tone: .warn,
              trigger: "Agent 停下来等你回复或授权。需要接入 hooks 才能知道。"),
        .init(id: "painting", label: "创作中", symbol: "paintbrush.fill", tone: .active,
              trigger: "Codex 正在生成图片。"),
        .init(id: "focus", label: "专注", symbol: "timer", tone: .active,
              trigger: "你开始了专注计时；结束时它会撒花。"),
        .init(id: "alert", label: "有提醒", symbol: "bell.fill", tone: .warn,
              trigger: "24 小时内有重置卡、积分或会员到期。"),
        .init(id: "excited", label: "期待", symbol: "sparkles", tone: .calm,
              trigger: "重置预测认为额度快要重置了。"),
        .init(id: "tired", label: "没力气", symbol: "battery.25", tone: .warn,
              trigger: "你正在用的那个来源，额度低于提醒阈值。"),
        .init(id: "alarm", label: "告急", symbol: "exclamationmark.triangle.fill", tone: .danger,
              trigger: "你正在用的那个来源，额度只剩不到 5%。"),
        .init(id: "exhausted", label: "耗尽", symbol: "battery.0", tone: .danger,
              trigger: "你正在用的那个来源，额度已经用完。"),
        .init(id: "confused", label: "拿不准", symbol: "questionmark.circle", tone: .quiet,
              trigger: "额度数据超过 20 分钟没更新。不知道就说不知道，不会当成 0%。"),
        .init(id: "offline", label: "失联", symbol: "wifi.slash", tone: .quiet,
              trigger: "连不上本机后端。"),
        .init(id: "sleeping", label: "睡觉", symbol: "moon.zzz.fill", tone: .quiet,
              trigger: "免打扰时段，或者很久没有任何活动。"),
    ]

    /// Short reactions that play on top of whatever the pet is doing.
    static let reactions: [PetStateInfo] = [
        .init(id: "celebrate", label: "庆祝", symbol: "party.popper.fill", tone: .calm,
              trigger: "Agent 完成任务、额度刷新、重置如期到账、专注计时结束时撒花。"),
        .init(id: "eating", label: "吃 Token", symbol: "fork.knife", tone: .calm,
              trigger: "短时间里烧掉大量 Token 时，大口大口地吃。"),
        .init(id: "startle", label: "受惊", symbol: "exclamationmark.bubble.fill", tone: .danger,
              trigger: "Agent 会话出错或失败时吓一跳。"),
        .init(id: "wave", label: "挥手", symbol: "hand.wave.fill", tone: .calm,
              trigger: "刚启动、或模型价格表更新时打招呼。"),
        .init(id: "painting", label: "花积分", symbol: "paintpalette.fill", tone: .active,
              trigger: "创作积分被花掉时，画上一笔。"),
    ]

    static func info(_ id: String) -> PetStateInfo? {
        states.first { $0.id == id } ?? reactions.first { $0.id == id }
    }

    static func label(_ id: String) -> String { info(id)?.label ?? id }
}
