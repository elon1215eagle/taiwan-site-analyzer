from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from contextlib import contextmanager

ROLES = ("franchisee", "developer", "admin")
CASE_STATUSES = ("draft", "submitted", "needs_info", "evaluating", "closed")


@dataclass(frozen=True)
class WorkspaceUser:
    id: int
    email: str
    name: str
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "email": self.email, "name": self.name, "role": self.role}


class WorkspaceError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class TokenService:
    def __init__(self, secret: str, lifetime_hours: int = 12):
        if len(secret) < 24:
            raise ValueError("GDO_AUTH_SECRET must contain at least 24 characters")
        self.secret = secret.encode("utf-8")
        self.lifetime_hours = lifetime_hours

    def issue(self, user: WorkspaceUser) -> str:
        expires = datetime.now(timezone.utc) + timedelta(hours=self.lifetime_hours)
        payload = json.dumps(
            {"sub": user.id, "role": user.role, "exp": int(expires.timestamp())},
            separators=(",", ":"),
        ).encode("utf-8")
        encoded = urlsafe_encode(payload)
        signature = urlsafe_encode(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def verify(self, token: str) -> int:
        try:
            encoded, signature = token.split(".", 1)
            expected = urlsafe_encode(
                hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(urlsafe_decode(encoded))
            if int(payload["exp"]) < int(datetime.now(timezone.utc).timestamp()):
                raise ValueError
            return int(payload["sub"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise WorkspaceError("INVALID_SESSION", "登入狀態已失效，請重新登入。", 401) from error


class WorkspaceRepository:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id INTEGER NOT NULL REFERENCES users(id),
                    developer_user_id INTEGER REFERENCES users(id),
                    title TEXT NOT NULL,
                    business_type TEXT NOT NULL,
                    county TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    address TEXT NOT NULL,
                    monthly_rent INTEGER,
                    area_ping REAL,
                    report_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS report_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                    version_number INTEGER NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(candidate_id, version_number)
                );
                CREATE TABLE IF NOT EXISTS surveys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    onsite_count INTEGER,
                    notes TEXT NOT NULL DEFAULT '',
                    photo_data TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS case_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    read_at TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_user(self, email: str, name: str, role: str, password: str) -> WorkspaceUser:
        if role not in ROLES:
            raise WorkspaceError("INVALID_ROLE", "帳號角色不正確。")
        now = utc_now()
        password_hash = hash_password(password)
        try:
            with self.connection() as db:
                cursor = db.execute(
                    "INSERT INTO users(email,name,role,password_hash,created_at) VALUES(?,?,?,?,?)",
                    (email.strip().lower(), name.strip(), role, password_hash, now),
                )
                user_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as error:
            raise WorkspaceError("EMAIL_EXISTS", "此 Email 已建立帳號。") from error
        return WorkspaceUser(user_id, email.strip().lower(), name.strip(), role)

    def authenticate(self, email: str, password: str) -> WorkspaceUser:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM users WHERE email=? AND active=1",
                (email.strip().lower(),),
            ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            raise WorkspaceError("LOGIN_FAILED", "Email 或密碼不正確。", 401)
        return row_to_user(row)

    def user_by_id(self, user_id: int) -> WorkspaceUser:
        with self.connection() as db:
            row = db.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if row is None:
            raise WorkspaceError("USER_NOT_FOUND", "帳號不存在或已停權。", 401)
        return row_to_user(row)

    def list_cases(self, user: WorkspaceUser) -> list[dict]:
        where, params = case_scope(user)
        with self.connection() as db:
            rows = db.execute(
                f"""
                SELECT c.*, u.name AS owner_name, d.name AS developer_name,
                       (SELECT COUNT(*) FROM candidates x WHERE x.case_id=c.id) AS candidate_count
                FROM cases c
                JOIN users u ON u.id=c.owner_user_id
                LEFT JOIN users d ON d.id=c.developer_user_id
                WHERE {where}
                ORDER BY c.updated_at DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_users(self, user: WorkspaceUser) -> list[dict]:
        if user.role != "admin":
            raise WorkspaceError("ACTION_FORBIDDEN", "只有總部管理員可管理帳號。", 403)
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,email,name,role,active,created_at FROM users ORDER BY role,name"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_managed_user(self, user: WorkspaceUser, payload: dict) -> dict:
        if user.role != "admin":
            raise WorkspaceError("ACTION_FORBIDDEN", "只有總部管理員可建立帳號。", 403)
        created = self.create_user(
            required(payload, "email"),
            required(payload, "name"),
            required(payload, "role"),
            required(payload, "password"),
        )
        return created.to_dict()

    def create_case(self, user: WorkspaceUser, payload: dict) -> dict:
        business_type = required(payload, "business_type")
        title = required(payload, "title")
        county = str(payload.get("county") or "").strip()
        now = utc_now()
        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO cases(owner_user_id,title,business_type,county,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                """,
                (user.id, title, business_type, county, now, now),
            )
            case_id = int(cursor.lastrowid)
        return self.get_case(user, case_id)

    def get_case(self, user: WorkspaceUser, case_id: int) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                raise WorkspaceError("CASE_NOT_FOUND", "找不到案件。", 404)
            ensure_case_access(user, row)
            candidates = db.execute(
                "SELECT * FROM candidates WHERE case_id=? ORDER BY created_at",
                (case_id,),
            ).fetchall()
            candidate_ids = [int(item["id"]) for item in candidates]
            versions_by_candidate: dict[int, list[dict]] = defaultdict(list)
            surveys_by_candidate: dict[int, list[dict]] = defaultdict(list)
            if candidate_ids:
                placeholders = ",".join("?" for _ in candidate_ids)
                version_rows = db.execute(
                    f"""
                    SELECT id,candidate_id,version_number,created_at
                    FROM report_versions
                    WHERE candidate_id IN ({placeholders})
                    ORDER BY candidate_id,version_number DESC
                    """,
                    candidate_ids,
                ).fetchall()
                for item in version_rows:
                    versions_by_candidate[int(item["candidate_id"])].append(dict(item))
                survey_rows = db.execute(
                    f"""
                    SELECT s.id,s.candidate_id,s.onsite_count,s.notes,s.photo_data,s.created_at,u.name AS author_name
                    FROM surveys s JOIN users u ON u.id=s.user_id
                    WHERE s.candidate_id IN ({placeholders})
                    ORDER BY s.created_at DESC
                    """,
                    candidate_ids,
                ).fetchall()
                for item in survey_rows:
                    survey = dict(item)
                    survey["photos"] = json.loads(survey.pop("photo_data"))
                    surveys_by_candidate[int(item["candidate_id"])].append(survey)
            comments = db.execute(
                """
                SELECT m.*, u.name AS author_name, u.role AS author_role
                FROM case_comments m JOIN users u ON u.id=m.user_id
                WHERE m.case_id=? ORDER BY m.created_at
                """,
                (case_id,),
            ).fetchall()
        result = dict(row)
        result["candidates"] = []
        for item in candidates:
            candidate = candidate_to_dict(item)
            candidate["report_versions"] = versions_by_candidate[int(item["id"])]
            candidate["surveys"] = surveys_by_candidate[int(item["id"])]
            result["candidates"].append(candidate)
        result["comments"] = [dict(item) for item in comments]
        return result

    def add_candidate(self, user: WorkspaceUser, payload: dict) -> dict:
        case_id = int(payload.get("case_id") or 0)
        self.get_case(user, case_id)
        address = required(payload, "address")
        now = utc_now()
        report_json = payload.get("report")
        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO candidates(case_id,address,monthly_rent,area_ping,report_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    case_id,
                    address,
                    optional_int(payload.get("monthly_rent")),
                    optional_float(payload.get("area_ping")),
                    json.dumps(report_json, ensure_ascii=False) if report_json else None,
                    now,
                    now,
                ),
            )
            candidate_id = int(cursor.lastrowid)
            row = db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
            if report_json:
                db.execute(
                    """
                    INSERT INTO report_versions(candidate_id,version_number,report_json,created_at)
                    VALUES(?,?,?,?)
                    """,
                    (candidate_id, 1, json.dumps(report_json, ensure_ascii=False), now),
                )
        return candidate_to_dict(row)

    def add_report_version(self, user: WorkspaceUser, payload: dict) -> dict:
        candidate_id = int(payload.get("candidate_id") or 0)
        report = payload.get("report")
        if not isinstance(report, dict):
            raise WorkspaceError("REPORT_REQUIRED", "缺少重新分析報告。")
        now = utc_now()
        with self.connection() as db:
            candidate = db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
            if candidate is None:
                raise WorkspaceError("CANDIDATE_NOT_FOUND", "找不到候選店面。", 404)
            case = db.execute("SELECT * FROM cases WHERE id=?", (candidate["case_id"],)).fetchone()
            ensure_case_access(user, case)
            version = int(
                db.execute(
                    "SELECT COALESCE(MAX(version_number),0)+1 FROM report_versions WHERE candidate_id=?",
                    (candidate_id,),
                ).fetchone()[0]
            )
            encoded = json.dumps(report, ensure_ascii=False)
            db.execute(
                """
                INSERT INTO report_versions(candidate_id,version_number,report_json,created_at)
                VALUES(?,?,?,?)
                """,
                (candidate_id, version, encoded, now),
            )
            db.execute(
                "UPDATE candidates SET report_json=?,updated_at=? WHERE id=?",
                (encoded, now, candidate_id),
            )
        return {"candidate_id": candidate_id, "version_number": version, "created_at": now}

    def assign_case(self, user: WorkspaceUser, payload: dict) -> dict:
        if user.role != "admin":
            raise WorkspaceError("ACTION_FORBIDDEN", "只有總部管理員可指派案件。", 403)
        case_id = int(payload.get("case_id") or 0)
        developer_user_id = int(payload.get("developer_user_id") or 0)
        with self.connection() as db:
            case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                raise WorkspaceError("CASE_NOT_FOUND", "找不到案件。", 404)
            developer = db.execute(
                "SELECT * FROM users WHERE id=? AND role='developer' AND active=1",
                (developer_user_id,),
            ).fetchone()
            if developer is None:
                raise WorkspaceError("DEVELOPER_NOT_FOUND", "找不到可指派的區域開發人員。")
            now = utc_now()
            db.execute(
                "UPDATE cases SET developer_user_id=?,updated_at=? WHERE id=?",
                (developer_user_id, now, case_id),
            )
            db.execute(
                """
                INSERT INTO notifications(user_id,case_id,event_type,message,created_at)
                VALUES(?,?,?,?,?)
                """,
                (developer_user_id, case_id, "assigned", f"你已被指派案件「{case['title']}」。", now),
            )
        return self.get_case(user, case_id)

    def add_survey(self, user: WorkspaceUser, payload: dict) -> dict:
        candidate_id = int(payload.get("candidate_id") or 0)
        with self.connection() as db:
            candidate = db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
            if candidate is None:
                raise WorkspaceError("CANDIDATE_NOT_FOUND", "找不到候選店面。", 404)
            case = db.execute("SELECT * FROM cases WHERE id=?", (candidate["case_id"],)).fetchone()
            ensure_case_access(user, case)
            photos = payload.get("photos") or []
            if not isinstance(photos, list) or len(json.dumps(photos)) > 2_000_000:
                raise WorkspaceError("PHOTO_LIMIT", "現勘照片資料超過限制。")
            cursor = db.execute(
                """
                INSERT INTO surveys(candidate_id,user_id,onsite_count,notes,photo_data,created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    candidate_id,
                    user.id,
                    optional_int(payload.get("onsite_count")),
                    str(payload.get("notes") or "").strip(),
                    json.dumps(photos, ensure_ascii=False),
                    utc_now(),
                ),
            )
            survey_id = int(cursor.lastrowid)
        return {"id": survey_id, "candidate_id": candidate_id}

    def review_case(self, user: WorkspaceUser, payload: dict) -> dict:
        case_id = int(payload.get("case_id") or 0)
        action = str(payload.get("action") or "").strip()
        comment = str(payload.get("comment") or "").strip()
        allowed = {
            "submit": ("submitted", ("franchisee", "developer", "admin")),
            "evaluate": ("evaluating", ("developer", "admin")),
            "needs_info": ("needs_info", ("developer", "admin")),
            "close": ("closed", ("admin",)),
        }
        if action not in allowed or user.role not in allowed[action][1]:
            raise WorkspaceError("ACTION_FORBIDDEN", "你沒有執行此案件動作的權限。", 403)
        case = self.get_case(user, case_id)
        new_status = allowed[action][0]
        now = utc_now()
        with self.connection() as db:
            db.execute("UPDATE cases SET status=?,updated_at=? WHERE id=?", (new_status, now, case_id))
            if comment:
                db.execute(
                    "INSERT INTO case_comments(case_id,user_id,body,created_at) VALUES(?,?,?,?)",
                    (case_id, user.id, comment, now),
                )
            recipients = {int(case["owner_user_id"])}
            if case.get("developer_user_id"):
                recipients.add(int(case["developer_user_id"]))
            if user.id in recipients:
                recipients.remove(user.id)
            if action == "submit":
                admin_rows = db.execute(
                    "SELECT id FROM users WHERE role='admin' AND active=1"
                ).fetchall()
                recipients.update(int(item["id"]) for item in admin_rows if int(item["id"]) != user.id)
            for recipient in recipients:
                db.execute(
                    """
                    INSERT INTO notifications(user_id,case_id,event_type,message,created_at)
                    VALUES(?,?,?,?,?)
                    """,
                    (recipient, case_id, action, status_message(new_status, case["title"]), now),
                )
        return self.get_case(user, case_id)

    def list_notifications(self, user: WorkspaceUser) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
                (user.id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def read_notification(self, user: WorkspaceUser, notification_id: int) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE notifications SET read_at=? WHERE id=? AND user_id=?",
                (utc_now(), notification_id, user.id),
            )


def bootstrap_admin(repository: WorkspaceRepository) -> None:
    email = os.getenv("GDO_ADMIN_EMAIL", "").strip()
    password = os.getenv("GDO_ADMIN_PASSWORD", "")
    if not email or not password:
        return
    try:
        repository.create_user(email, os.getenv("GDO_ADMIN_NAME", "GDO 總部管理員"), "admin", password)
    except WorkspaceError as error:
        if error.code != "EMAIL_EXISTS":
            raise


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise WorkspaceError("WEAK_PASSWORD", "密碼至少需要 10 個字元。")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"pbkdf2_sha256$240000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def case_scope(user: WorkspaceUser) -> tuple[str, tuple]:
    if user.role == "admin":
        return "1=1", ()
    if user.role == "developer":
        return "(c.developer_user_id=? OR c.owner_user_id=?)", (user.id, user.id)
    return "c.owner_user_id=?", (user.id,)


def ensure_case_access(user: WorkspaceUser, case: sqlite3.Row | dict) -> None:
    if user.role == "admin":
        return
    if int(case["owner_user_id"]) == user.id:
        return
    if user.role == "developer" and case["developer_user_id"] == user.id:
        return
    raise WorkspaceError("CASE_FORBIDDEN", "你沒有查看此案件的權限。", 403)


def candidate_to_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["report"] = json.loads(result.pop("report_json")) if result.get("report_json") else None
    return result


def row_to_user(row: sqlite3.Row) -> WorkspaceUser:
    return WorkspaceUser(int(row["id"]), row["email"], row["name"], row["role"])


def required(payload: dict, field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise WorkspaceError("FIELD_REQUIRED", f"{field} 為必填欄位。")
    return value


def optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def status_message(status: str, title: str) -> str:
    labels = {
        "submitted": "已送交評估",
        "evaluating": "已進入評估",
        "needs_info": "需要補件",
        "closed": "已結案",
    }
    return f"案件「{title}」{labels.get(status, '狀態已更新')}。"


def urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def urlsafe_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
