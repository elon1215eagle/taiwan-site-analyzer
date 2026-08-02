from __future__ import annotations

import base64
import json
import re
from collections import Counter, defaultdict
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from .workspace import (
    ROLES,
    WorkspaceError,
    WorkspaceUser,
    ensure_case_access,
    hash_password,
    optional_float,
    optional_int,
    required,
    status_message,
    utc_now,
    verify_password,
)


TABLES = {
    "users": "gdo_users",
    "cases": "gdo_cases",
    "candidates": "gdo_candidates",
    "versions": "gdo_report_versions",
    "surveys": "gdo_surveys",
    "comments": "gdo_case_comments",
    "notifications": "gdo_notifications",
}


class SupabaseRestError(RuntimeError):
    def __init__(self, status: int, payload: object):
        super().__init__(f"Supabase request failed with HTTP {status}")
        self.status = status
        self.payload = payload


class SupabaseRestClient:
    def __init__(self, url: str, secret_key: str, timeout_seconds: float = 20):
        if not url.startswith("https://"):
            raise ValueError("SUPABASE_URL must use HTTPS")
        if not secret_key:
            raise ValueError("SUPABASE_SECRET_KEY is required")
        self.url = url.rstrip("/")
        self.secret_key = secret_key
        self.timeout_seconds = timeout_seconds

    def select(
        self,
        table: str,
        *,
        filters: list[tuple[str, str]] | None = None,
        columns: str = "*",
        order: str | None = None,
        limit: int | None = None,
        extra: list[tuple[str, str]] | None = None,
    ) -> list[dict]:
        query = [("select", columns), *(filters or []), *(extra or [])]
        if order:
            query.append(("order", order))
        if limit is not None:
            query.append(("limit", str(limit)))
        result = self._request("GET", f"/rest/v1/{table}", query=query)
        return result if isinstance(result, list) else []

    def insert(self, table: str, payload: dict) -> dict:
        rows = self._request(
            "POST",
            f"/rest/v1/{table}",
            payload=payload,
            prefer="return=representation",
        )
        if not isinstance(rows, list) or not rows:
            raise SupabaseRestError(502, {"message": "Supabase insert returned no row"})
        return rows[0]

    def update(self, table: str, filters: list[tuple[str, str]], payload: dict) -> list[dict]:
        rows = self._request(
            "PATCH",
            f"/rest/v1/{table}",
            query=filters,
            payload=payload,
            prefer="return=representation",
        )
        return rows if isinstance(rows, list) else []

    def upload(self, bucket: str, path: str, content_type: str, payload: bytes) -> dict:
        return self._request(
            "POST",
            f"/storage/v1/object/{quote(bucket, safe='')}/{quote(path, safe='/')}",
            raw_payload=payload,
            content_type=content_type,
            extra_headers={"x-upsert": "false"},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, str]] | None = None,
        payload: dict | None = None,
        raw_payload: bytes | None = None,
        content_type: str = "application/json",
        prefer: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> object:
        target = f"{self.url}{path}"
        if query:
            target += "?" + urlencode(query, doseq=True, safe="(),.*")
        data = raw_payload
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
            "Accept": "application/json",
            "Content-Type": content_type,
        }
        if prefer:
            headers["Prefer"] = prefer
        if extra_headers:
            headers.update(extra_headers)
        request = Request(target, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except HTTPError as error:
            body = error.read()
            try:
                details = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                details = {"message": body.decode("utf-8", errors="replace")}
            raise SupabaseRestError(error.code, details) from error
        except URLError as error:
            raise SupabaseRestError(503, {"message": str(error.reason)}) from error
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SupabaseRestError(502, {"message": "Invalid Supabase response"}) from error


class SupabaseWorkspaceRepository:
    def __init__(self, url: str, secret_key: str, client: SupabaseRestClient | None = None):
        self.client = client or SupabaseRestClient(url, secret_key)

    def health(self) -> bool:
        self.client.select(TABLES["users"], columns="id", limit=1)
        return True

    def create_user(self, email: str, name: str, role: str, password: str) -> WorkspaceUser:
        if role not in ROLES:
            raise WorkspaceError("INVALID_ROLE", "帳號角色不正確。")
        try:
            row = self.client.insert(
                TABLES["users"],
                {
                    "email": email.strip().lower(),
                    "name": name.strip(),
                    "role": role,
                    "password_hash": hash_password(password),
                    "active": True,
                    "created_at": utc_now(),
                },
            )
        except SupabaseRestError as error:
            if error.status == 409 or "23505" in json.dumps(error.payload):
                raise WorkspaceError("EMAIL_EXISTS", "此 Email 已建立帳號。") from error
            raise
        return self._row_to_user(row)

    def authenticate(self, email: str, password: str) -> WorkspaceUser:
        rows = self.client.select(
            TABLES["users"],
            filters=[("email", f"eq.{email.strip().lower()}"), ("active", "eq.true")],
            limit=1,
        )
        if not rows or not verify_password(password, rows[0]["password_hash"]):
            raise WorkspaceError("LOGIN_FAILED", "Email 或密碼不正確。", 401)
        return self._row_to_user(rows[0])

    def user_by_id(self, user_id: int) -> WorkspaceUser:
        rows = self.client.select(
            TABLES["users"],
            filters=[("id", f"eq.{user_id}"), ("active", "eq.true")],
            limit=1,
        )
        if not rows:
            raise WorkspaceError("USER_NOT_FOUND", "帳號不存在或已停權。", 401)
        return self._row_to_user(rows[0])

    def list_cases(self, user: WorkspaceUser) -> list[dict]:
        cases = self.client.select(TABLES["cases"], order="updated_at.desc")
        if user.role == "developer":
            cases = [
                item
                for item in cases
                if item.get("developer_user_id") == user.id or item["owner_user_id"] == user.id
            ]
        elif user.role != "admin":
            cases = [item for item in cases if item["owner_user_id"] == user.id]
        users = self._users_by_id()
        case_ids = {int(item["id"]) for item in cases}
        counts = Counter(
            int(item["case_id"])
            for item in self.client.select(TABLES["candidates"], columns="case_id")
            if int(item["case_id"]) in case_ids
        )
        for item in cases:
            owner = users.get(int(item["owner_user_id"]), {})
            developer = users.get(int(item["developer_user_id"])) if item.get("developer_user_id") else None
            item["owner_name"] = owner.get("name", "")
            item["developer_name"] = developer.get("name", "") if developer else None
            item["candidate_count"] = counts[int(item["id"])]
        return cases

    def list_users(self, user: WorkspaceUser) -> list[dict]:
        if user.role != "admin":
            raise WorkspaceError("ACTION_FORBIDDEN", "只有總部管理員可管理帳號。", 403)
        return self.client.select(
            TABLES["users"],
            columns="id,email,name,role,active,created_at",
            order="role.asc,name.asc",
        )

    def create_managed_user(self, user: WorkspaceUser, payload: dict) -> dict:
        if user.role != "admin":
            raise WorkspaceError("ACTION_FORBIDDEN", "只有總部管理員可建立帳號。", 403)
        return self.create_user(
            required(payload, "email"),
            required(payload, "name"),
            required(payload, "role"),
            required(payload, "password"),
        ).to_dict()

    def create_case(self, user: WorkspaceUser, payload: dict) -> dict:
        now = utc_now()
        row = self.client.insert(
            TABLES["cases"],
            {
                "owner_user_id": user.id,
                "title": required(payload, "title"),
                "business_type": required(payload, "business_type"),
                "county": str(payload.get("county") or "").strip(),
                "status": "draft",
                "created_at": now,
                "updated_at": now,
            },
        )
        return self.get_case(user, int(row["id"]))

    def get_case(self, user: WorkspaceUser, case_id: int) -> dict:
        rows = self.client.select(TABLES["cases"], filters=[("id", f"eq.{case_id}")], limit=1)
        if not rows:
            raise WorkspaceError("CASE_NOT_FOUND", "找不到案件。", 404)
        result = rows[0]
        ensure_case_access(user, result)
        candidates = self.client.select(
            TABLES["candidates"],
            filters=[("case_id", f"eq.{case_id}")],
            order="created_at.asc",
        )
        candidate_ids = [int(item["id"]) for item in candidates]
        versions_by_candidate: dict[int, list[dict]] = defaultdict(list)
        surveys_by_candidate: dict[int, list[dict]] = defaultdict(list)
        if candidate_ids:
            filter_value = self._in_filter(candidate_ids)
            versions = self.client.select(
                TABLES["versions"],
                filters=[("candidate_id", filter_value)],
                columns="id,candidate_id,version_number,created_at",
                order="candidate_id.asc,version_number.desc",
            )
            for item in versions:
                versions_by_candidate[int(item["candidate_id"])].append(item)
            users = self._users_by_id()
            surveys = self.client.select(
                TABLES["surveys"],
                filters=[("candidate_id", filter_value)],
                order="created_at.desc",
            )
            for item in surveys:
                survey = dict(item)
                survey["author_name"] = users.get(int(item["user_id"]), {}).get("name", "")
                survey["photos"] = survey.pop("photo_data", []) or []
                surveys_by_candidate[int(item["candidate_id"])].append(survey)
        users = self._users_by_id()
        comments = self.client.select(
            TABLES["comments"],
            filters=[("case_id", f"eq.{case_id}")],
            order="created_at.asc",
        )
        for item in comments:
            author = users.get(int(item["user_id"]), {})
            item["author_name"] = author.get("name", "")
            item["author_role"] = author.get("role", "")
        result["candidates"] = []
        for item in candidates:
            candidate = self._candidate_to_dict(item)
            candidate["report_versions"] = versions_by_candidate[int(item["id"])]
            candidate["surveys"] = surveys_by_candidate[int(item["id"])]
            result["candidates"].append(candidate)
        result["comments"] = comments
        return result

    def add_candidate(self, user: WorkspaceUser, payload: dict) -> dict:
        case_id = int(payload.get("case_id") or 0)
        self.get_case(user, case_id)
        now = utc_now()
        report = payload.get("report")
        row = self.client.insert(
            TABLES["candidates"],
            {
                "case_id": case_id,
                "address": required(payload, "address"),
                "monthly_rent": optional_int(payload.get("monthly_rent")),
                "area_ping": optional_float(payload.get("area_ping")),
                "report_json": report,
                "created_at": now,
                "updated_at": now,
            },
        )
        if report:
            self.client.insert(
                TABLES["versions"],
                {
                    "candidate_id": int(row["id"]),
                    "version_number": 1,
                    "report_json": report,
                    "created_at": now,
                },
            )
        return self._candidate_to_dict(row)

    def add_report_version(self, user: WorkspaceUser, payload: dict) -> dict:
        candidate_id = int(payload.get("candidate_id") or 0)
        report = payload.get("report")
        if not isinstance(report, dict):
            raise WorkspaceError("REPORT_REQUIRED", "缺少重新分析報告。")
        candidate = self._one(TABLES["candidates"], "id", candidate_id, "CANDIDATE_NOT_FOUND", "找不到候選店面。")
        case = self._one(TABLES["cases"], "id", int(candidate["case_id"]), "CASE_NOT_FOUND", "找不到案件。")
        ensure_case_access(user, case)
        versions = self.client.select(
            TABLES["versions"],
            filters=[("candidate_id", f"eq.{candidate_id}")],
            columns="version_number",
            order="version_number.desc",
            limit=1,
        )
        version = int(versions[0]["version_number"]) + 1 if versions else 1
        now = utc_now()
        self.client.insert(
            TABLES["versions"],
            {
                "candidate_id": candidate_id,
                "version_number": version,
                "report_json": report,
                "created_at": now,
            },
        )
        self.client.update(
            TABLES["candidates"],
            [("id", f"eq.{candidate_id}")],
            {"report_json": report, "updated_at": now},
        )
        return {"candidate_id": candidate_id, "version_number": version, "created_at": now}

    def assign_case(self, user: WorkspaceUser, payload: dict) -> dict:
        if user.role != "admin":
            raise WorkspaceError("ACTION_FORBIDDEN", "只有總部管理員可指派案件。", 403)
        case_id = int(payload.get("case_id") or 0)
        developer_user_id = int(payload.get("developer_user_id") or 0)
        case = self._one(TABLES["cases"], "id", case_id, "CASE_NOT_FOUND", "找不到案件。")
        developers = self.client.select(
            TABLES["users"],
            filters=[
                ("id", f"eq.{developer_user_id}"),
                ("role", "eq.developer"),
                ("active", "eq.true"),
            ],
            limit=1,
        )
        if not developers:
            raise WorkspaceError("DEVELOPER_NOT_FOUND", "找不到可指派的區域開發人員。")
        now = utc_now()
        self.client.update(
            TABLES["cases"],
            [("id", f"eq.{case_id}")],
            {"developer_user_id": developer_user_id, "updated_at": now},
        )
        self.client.insert(
            TABLES["notifications"],
            {
                "user_id": developer_user_id,
                "case_id": case_id,
                "event_type": "assigned",
                "message": f"你已被指派案件「{case['title']}」。",
                "created_at": now,
            },
        )
        return self.get_case(user, case_id)

    def add_survey(self, user: WorkspaceUser, payload: dict) -> dict:
        candidate_id = int(payload.get("candidate_id") or 0)
        candidate = self._one(TABLES["candidates"], "id", candidate_id, "CANDIDATE_NOT_FOUND", "找不到候選店面。")
        case = self._one(TABLES["cases"], "id", int(candidate["case_id"]), "CASE_NOT_FOUND", "找不到案件。")
        ensure_case_access(user, case)
        photos = payload.get("photos") or []
        if not isinstance(photos, list) or len(photos) > 3:
            raise WorkspaceError("PHOTO_LIMIT", "現勘照片最多 3 張。")
        stored_photos = [self._store_photo(candidate_id, item) for item in photos]
        row = self.client.insert(
            TABLES["surveys"],
            {
                "candidate_id": candidate_id,
                "user_id": user.id,
                "onsite_count": optional_int(payload.get("onsite_count")),
                "notes": str(payload.get("notes") or "").strip(),
                "photo_data": stored_photos,
                "created_at": utc_now(),
            },
        )
        return {"id": int(row["id"]), "candidate_id": candidate_id}

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
        self.client.update(
            TABLES["cases"],
            [("id", f"eq.{case_id}")],
            {"status": new_status, "updated_at": now},
        )
        if comment:
            self.client.insert(
                TABLES["comments"],
                {"case_id": case_id, "user_id": user.id, "body": comment, "created_at": now},
            )
        recipients = {int(case["owner_user_id"])}
        if case.get("developer_user_id"):
            recipients.add(int(case["developer_user_id"]))
        recipients.discard(user.id)
        if action == "submit":
            admins = self.client.select(
                TABLES["users"],
                filters=[("role", "eq.admin"), ("active", "eq.true")],
                columns="id",
            )
            recipients.update(int(item["id"]) for item in admins if int(item["id"]) != user.id)
        for recipient in recipients:
            self.client.insert(
                TABLES["notifications"],
                {
                    "user_id": recipient,
                    "case_id": case_id,
                    "event_type": action,
                    "message": status_message(new_status, case["title"]),
                    "created_at": now,
                },
            )
        return self.get_case(user, case_id)

    def list_notifications(self, user: WorkspaceUser) -> list[dict]:
        return self.client.select(
            TABLES["notifications"],
            filters=[("user_id", f"eq.{user.id}")],
            order="created_at.desc",
            limit=50,
        )

    def read_notification(self, user: WorkspaceUser, notification_id: int) -> None:
        self.client.update(
            TABLES["notifications"],
            [("id", f"eq.{notification_id}"), ("user_id", f"eq.{user.id}")],
            {"read_at": utc_now()},
        )

    def _one(self, table: str, field: str, value: int, code: str, message: str) -> dict:
        rows = self.client.select(table, filters=[(field, f"eq.{value}")], limit=1)
        if not rows:
            raise WorkspaceError(code, message, 404)
        return rows[0]

    def _users_by_id(self) -> dict[int, dict]:
        return {
            int(item["id"]): item
            for item in self.client.select(
                TABLES["users"], columns="id,name,role,email,active,created_at"
            )
        }

    def _store_photo(self, candidate_id: int, data_url: object) -> dict:
        if not isinstance(data_url, str):
            raise WorkspaceError("INVALID_PHOTO", "現勘照片格式不正確。")
        match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,(.+)", data_url, re.DOTALL)
        if not match:
            raise WorkspaceError("INVALID_PHOTO", "現勘照片僅支援 JPEG、PNG 或 WebP。")
        try:
            payload = base64.b64decode(match.group(2), validate=True)
        except ValueError as error:
            raise WorkspaceError("INVALID_PHOTO", "現勘照片內容無法讀取。") from error
        if len(payload) > 10 * 1024 * 1024:
            raise WorkspaceError("PHOTO_LIMIT", "單張現勘照片不可超過 10 MB。")
        content_type = match.group(1)
        extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[content_type]
        path = f"candidate-{candidate_id}/{uuid4().hex}.{extension}"
        self.client.upload("gdo-surveys", path, content_type, payload)
        return {"bucket": "gdo-surveys", "path": path, "content_type": content_type}

    @staticmethod
    def _row_to_user(row: dict) -> WorkspaceUser:
        return WorkspaceUser(int(row["id"]), row["email"], row["name"], row["role"])

    @staticmethod
    def _candidate_to_dict(row: dict) -> dict:
        result = dict(row)
        result["report"] = result.pop("report_json", None)
        return result

    @staticmethod
    def _in_filter(values: list[int]) -> str:
        return f"in.({','.join(str(int(value)) for value in values)})"
