import plistlib
from pathlib import Path

# App identity is separate from the provider's billing identity.
KNOWN = {
    "ChatGPT": "codex", "Codex": "codex", "Claude": "claude",
    "Kimi Code": "kimi", "Kimi": "kimi_chat", "KimiCU": "kimi_cu",
    "MiniMax Code": "minimax_code", "MiniMax Design": "minimax_design",
    "Qoder CN": "qoder", "Qoder CN IDE": "qoder",
    "Trae CN": "trae_cn", "TRAE SOLO CN": "trae_solo_cn", "WorkBuddy": "workbuddy",
    "ZCode": "zcode", "DeepSeek Harness": "deepseek_harness", "Xiaomi MiMo": "mimo",
    "AutoGLM": "autoglm", "妙手": "catpaw", "Doubao": "doubao", "豆包浏览器": "doubao_browser",
    "Cherry Studio": "cherry", "LM Studio": "lmstudio", "CC Switch": "ccswitch",
    "Agent Launcher": "agent_launcher", "Cursor": "cursor", "Windsurf": "windsurf",
    "Gemini": "gemini", "OpenCode": "opencode", "Antigravity": "antigravity",
}


def discover(app_roots):
    result = []
    seen = set()
    for root in app_roots:
        root = Path(root).expanduser()
        # Include apps in vendor subfolders, but do not descend into app bundles.
        paths = list(root.glob("*.app")) + list(root.glob("*/*.app"))
        for path in sorted(paths):
            if path.stem not in KNOWN or str(path.resolve()) in seen:
                continue
            seen.add(str(path.resolve()))
            info = {}
            try:
                info = plistlib.loads((path/"Contents/Info.plist").read_bytes())
            except (OSError, ValueError):
                pass
            provider = "codex" if info.get("CFBundleIdentifier")=="com.openai.codex" else KNOWN[path.stem]
            result.append({"name":path.stem,"path":str(path),"provider":provider,"installed":True,
                "bundle_id":info.get("CFBundleIdentifier"),"version":info.get("CFBundleShortVersionString"),
                "discovery_kind":"known_bundle" if info else "directory_only"})
    return result
