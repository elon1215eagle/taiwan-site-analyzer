from __future__ import annotations

import copy
import unittest

from tw_site_analyzer.supabase_workspace import (
    SupabaseRestError,
    SupabaseWorkspaceRepository,
    TABLES,
)
from tw_site_analyzer.workspace import WorkspaceError


class FakeSupabaseClient:
    def __init__(self):
        self.rows = {table: [] for table in TABLES.values()}
        self.uploads = []

    def select(self, table, *, filters=None, columns="*", order=None, limit=None, extra=None):
        rows = [copy.deepcopy(item) for item in self.rows[table]]
        for field, expression in filters or []:
            if expression.startswith("eq."):
                expected = expression[3:]
                rows = [item for item in rows if self._equal(item.get(field), expected)]
            elif expression.startswith("in.("):
                values = set(expression[4:-1].split(","))
                rows = [item for item in rows if str(item.get(field)) in values]
        if order:
            field, direction = order.split(",", 1)[0].split(".", 1)
            rows.sort(key=lambda item: item.get(field) or "", reverse=direction == "desc")
        if limit is not None:
            rows = rows[:limit]
        if columns != "*":
            names = columns.split(",")
            rows = [{name: item.get(name) for name in names} for item in rows]
        return rows

    def insert(self, table, payload):
        if table == TABLES["users"] and any(
            item["email"] == payload["email"] for item in self.rows[table]
        ):
            raise SupabaseRestError(409, {"code": "23505"})
        row = copy.deepcopy(payload)
        row["id"] = len(self.rows[table]) + 1
        self.rows[table].append(row)
        return copy.deepcopy(row)

    def update(self, table, filters, payload):
        matched = []
        for row in self.rows[table]:
            if all(
                expression.startswith("eq.") and self._equal(row.get(field), expression[3:])
                for field, expression in filters
            ):
                row.update(copy.deepcopy(payload))
                matched.append(copy.deepcopy(row))
        return matched

    def upload(self, bucket, path, content_type, payload):
        self.uploads.append((bucket, path, content_type, payload))
        return {"Key": f"{bucket}/{path}"}

    @staticmethod
    def _equal(actual, expected):
        if expected in ("true", "false"):
            return bool(actual) is (expected == "true")
        return str(actual) == expected


class SupabaseWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeSupabaseClient()
        self.repository = SupabaseWorkspaceRepository(
            "https://example.supabase.co", "test-secret", client=self.client
        )
        self.owner = self.repository.create_user(
            "owner@example.com", "加盟主", "franchisee", "strong-pass-001"
        )
        self.other = self.repository.create_user(
            "other@example.com", "其他加盟主", "franchisee", "strong-pass-002"
        )
        self.admin = self.repository.create_user(
            "admin@example.com", "總部", "admin", "strong-pass-003"
        )

    def test_login_and_case_access_are_preserved(self):
        self.assertEqual(
            self.repository.authenticate("owner@example.com", "strong-pass-001").id,
            self.owner.id,
        )
        case = self.repository.create_case(
            self.owner,
            {"title": "高雄候選店", "business_type": "炸雞", "county": "高雄市"},
        )
        with self.assertRaises(WorkspaceError):
            self.repository.get_case(self.other, case["id"])

    def test_candidate_versions_survey_and_notifications_persist(self):
        case = self.repository.create_case(
            self.owner,
            {"title": "高雄候選店", "business_type": "炸雞", "county": "高雄市"},
        )
        candidate = self.repository.add_candidate(
            self.owner,
            {
                "case_id": case["id"],
                "address": "高雄市三民區建工路",
                "report": {"scorecard": {"overall_score": 72}},
            },
        )
        version = self.repository.add_report_version(
            self.owner,
            {
                "candidate_id": candidate["id"],
                "report": {"scorecard": {"overall_score": 78}},
            },
        )
        pixel = "data:image/png;base64,iVBORw0KGgo="
        survey = self.repository.add_survey(
            self.owner,
            {"candidate_id": candidate["id"], "onsite_count": 35, "photos": [pixel]},
        )
        reviewed = self.repository.review_case(
            self.owner,
            {"case_id": case["id"], "action": "submit", "comment": "請協助評估"},
        )

        self.assertEqual(version["version_number"], 2)
        self.assertGreater(survey["id"], 0)
        self.assertEqual(reviewed["status"], "submitted")
        self.assertEqual(reviewed["candidates"][0]["report"]["scorecard"]["overall_score"], 78)
        self.assertEqual(len(self.client.uploads), 1)
        self.assertEqual(self.repository.list_notifications(self.admin)[0]["event_type"], "submit")


if __name__ == "__main__":
    unittest.main()
