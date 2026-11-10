#!/usr/bin/env python3
"""Static server for developing and previewing pet packs (stdlib only, loopback only, never cached).

    python3 pets/tools/serve.py            # serves pets/ at http://127.0.0.1:8765
    python3 pets/tools/serve.py --root ~/Library/Application\\ Support/AgentMeter/pets --port 8766

Open /runtime/sheet.html?pack=<id> for the contact sheet or /runtime/dev.html for the interactive harness.
The browser must not cache modules while you iterate, hence the no-store header.
"""
import argparse
import functools
import json
import mimetypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/webp", ".webp")


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/presets/index.json":
            return self.send_index()
        return super().do_GET()

    def send_index(self):
        """Lists the packs found under presets/ so the harness can offer them."""
        root = Path(self.directory) / "presets"
        packs = []
        for manifest in sorted(root.glob("*/pet.json")):
            try:
                data = json.loads(manifest.read_text())
                packs.append({"id": data["id"], "name": data.get("name"), "renderer": data.get("renderer")})
            except (OSError, ValueError, KeyError):
                continue
        body = json.dumps(packs, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="directory to serve (default: pets/)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    handler = functools.partial(Handler, directory=str(args.root))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print("serving %s at http://127.0.0.1:%d/" % (args.root, server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
