from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .application import SiteAnalyzerApplication
from .workspace import (
    TokenService,
    WorkspaceError,
    WorkspaceRepository,
    WorkspaceUser,
    bootstrap_admin,
)

WEB_ROOT = Path(__file__).resolve().parent.parent / "web_mobile"


def build_workspace_repository():
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_secret_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if supabase_url and supabase_secret_key:
        from .supabase_workspace import SupabaseWorkspaceRepository

        return SupabaseWorkspaceRepository(supabase_url, supabase_secret_key)
    return WorkspaceRepository(os.getenv("GDO_DB_PATH", ".data/gdo.sqlite3"))


class SiteAnalyzerHandler(BaseHTTPRequestHandler):
    application = SiteAnalyzerApplication()
    repository = build_workspace_repository()
    token_service = TokenService(
        os.getenv("GDO_AUTH_SECRET", "gdo-local-development-secret-change-me")
    )
    bootstrap_admin(repository)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/health":
            health = self.application.health()
            using_supabase = bool(
                os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SECRET_KEY")
            )
            database_ready = False
            if using_supabase:
                try:
                    database_ready = bool(self.repository.health())
                except Exception:
                    database_ready = False
            else:
                database_path = os.getenv("GDO_DB_PATH", ".data/gdo.sqlite3")
                database_ready = database_path.startswith("/var/data") or bool(
                    os.getenv("GDO_DATABASE_PERSISTENT")
                )
            health["workspace"] = {
                "authentication": "ready" if os.getenv("GDO_AUTH_SECRET") else "degraded",
                "admin_bootstrap": (
                    "ready"
                    if os.getenv("GDO_ADMIN_EMAIL") and os.getenv("GDO_ADMIN_PASSWORD")
                    else "degraded"
                ),
                "database": "ready" if database_ready else "degraded",
                "database_provider": "supabase" if using_supabase else "sqlite",
                "photo_storage": "ready" if using_supabase and database_ready else "degraded",
            }
            health["ok"] = health["ok"] and all(
                status in ("ready", "supabase") for status in health["workspace"].values()
            )
            if not health["ok"]:
                health["status"] = "degraded"
            self._send_json(health)
            return
        if self.path == "/api/auth/me":
            user = self._require_user()
            if user:
                self._send_json({"user": user.to_dict()})
            return
        if self.path == "/api/workspace/cases":
            user = self._require_user()
            if user:
                self._send_json({"cases": self.repository.list_cases(user)})
            return
        if self.path.startswith("/api/workspace/cases/"):
            user = self._require_user()
            if not user:
                return
            try:
                case_id = int(self.path.rsplit("/", 1)[-1])
                self._send_json({"case": self.repository.get_case(user, case_id)})
            except (ValueError, WorkspaceError) as error:
                self._send_workspace_error(error)
            return
        if self.path == "/api/workspace/notifications":
            user = self._require_user()
            if user:
                self._send_json({"notifications": self.repository.list_notifications(user)})
            return
        if self.path == "/api/workspace/users":
            user = self._require_user()
            if user:
                self._workspace_action(lambda: {"users": self.repository.list_users(user)})
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
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "INVALID_JSON", "message": "Request body must be JSON."}, 400)
            return
        if not isinstance(body, dict):
            self._send_json({"error": "INVALID_JSON_OBJECT", "message": "Request body must be a JSON object."}, 400)
            return
        if self.path == "/api/auth/login":
            try:
                user = self.repository.authenticate(
                    str(body.get("email") or ""),
                    str(body.get("password") or ""),
                )
                self._send_json({"token": self.token_service.issue(user), "user": user.to_dict()})
            except WorkspaceError as error:
                self._send_workspace_error(error)
            return
        user = self._require_user()
        if not user:
            return
        if self.path == "/api/workspace/cases":
            self._workspace_action(lambda: {"case": self.repository.create_case(user, body)})
            return
        if self.path == "/api/workspace/candidates":
            self._workspace_action(lambda: {"candidate": self.repository.add_candidate(user, body)})
            return
        if self.path == "/api/workspace/candidates/report":
            self._workspace_action(lambda: {"version": self.repository.add_report_version(user, body)})
            return
        if self.path == "/api/workspace/surveys":
            self._workspace_action(lambda: {"survey": self.repository.add_survey(user, body)})
            return
        if self.path == "/api/workspace/review":
            self._workspace_action(lambda: {"case": self.repository.review_case(user, body)})
            return
        if self.path == "/api/workspace/assign":
            self._workspace_action(lambda: {"case": self.repository.assign_case(user, body)})
            return
        if self.path == "/api/workspace/users":
            self._workspace_action(lambda: {"user": self.repository.create_managed_user(user, body)})
            return
        if self.path == "/api/workspace/notifications/read":
            def read_notification():
                self.repository.read_notification(user, int(body.get("notification_id") or 0))
                return {"ok": True}
            self._workspace_action(read_notification)
            return
        response = self.application.execute(self.path, body)
        self._send_json(response.payload, response.status_code)

    def log_message(self, format: str, *args) -> None:
        print(f"[site-analyzer] {format % args}")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _require_user(self) -> WorkspaceUser | None:
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            self._send_json(
                {"error": "AUTH_REQUIRED", "message": "請先登入 GDO 選址系統。"},
                401,
            )
            return None
        try:
            user_id = self.token_service.verify(authorization[7:].strip())
            return self.repository.user_by_id(user_id)
        except WorkspaceError as error:
            self._send_workspace_error(error)
            return None

    def _workspace_action(self, operation) -> None:
        try:
            self._send_json(operation())
        except WorkspaceError as error:
            self._send_workspace_error(error)
        except (TypeError, ValueError):
            self._send_json(
                {"error": "INVALID_INPUT", "message": "輸入資料格式不正確。"},
                400,
            )

    def _send_workspace_error(self, error) -> None:
        if isinstance(error, WorkspaceError):
            self._send_json({"error": error.code, "message": error.message}, error.status)
            return
        self._send_json({"error": "INVALID_INPUT", "message": "輸入資料格式不正確。"}, 400)


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
