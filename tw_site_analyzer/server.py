from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .analysis import SiteSelectionAnalyzer, public_json
from .report import build_chinese_report

WEB_ROOT = Path(__file__).resolve().parent.parent / "web_mobile"


class SiteAnalyzerHandler(BaseHTTPRequestHandler):
    analyzer = SiteSelectionAnalyzer()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._send_json({"ok": True, "service": "taiwan-site-selection-analyzer"})
            return
        requested = self.path.split("?", 1)[0]
        if requested in ("", "/"):
            file_path = WEB_ROOT / "index.html"
        else:
            file_path = (WEB_ROOT / unquote(requested.lstrip("/"))).resolve()
            if WEB_ROOT.resolve() not in file_path.parents and file_path != WEB_ROOT.resolve():
                self.send_error(403)
                return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        payload = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        if file_path.name == "sw.js":
            self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if self.path != "/api/analyze":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "INVALID_JSON", "message": "Request body must be JSON."}, 400)
            return
        location = str(body.get("location", "")).strip()
        if not location:
            self._send_json({"error": "LOCATION_REQUIRED", "message": "請輸入縣市、行政區、路段或地標。"}, 400)
            return
        result = public_json(self.analyzer.analyze(location))
        self._send_json({"report": build_chinese_report(result), "json": result})

    def log_message(self, format: str, *args) -> None:
        print(f"[site-analyzer] {self.address_string()} - {format % args}")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mobile web server for Taiwan site analyzer")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", default=int(os.getenv("PORT", "8787")), type=int)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), SiteAnalyzerHandler)
    print(f"Mobile analyzer running at http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
