import tempfile
import unittest
from pathlib import Path

from tw_site_analyzer.workspace import TokenService, WorkspaceError, WorkspaceRepository


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repository = WorkspaceRepository(Path(self.temp.name) / "gdo.sqlite3")
        self.franchisee = self.repository.create_user(
            "owner@example.com", "加盟主", "franchisee", "strong-pass-001"
        )
        self.other = self.repository.create_user(
            "other@example.com", "其他加盟主", "franchisee", "strong-pass-002"
        )
        self.developer = self.repository.create_user(
            "dev@example.com", "開發人員", "developer", "strong-pass-003"
        )
        self.admin = self.repository.create_user(
            "admin@example.com", "總部", "admin", "strong-pass-004"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_login_and_signed_token(self):
        user = self.repository.authenticate("owner@example.com", "strong-pass-001")
        token_service = TokenService("a-secure-test-secret-with-32-bytes")
        token = token_service.issue(user)
        self.assertEqual(token_service.verify(token), user.id)
        with self.assertRaises(WorkspaceError):
            self.repository.authenticate("owner@example.com", "wrong-password")

    def test_franchisee_cannot_read_another_case(self):
        case = self.repository.create_case(
            self.franchisee,
            {"title": "高雄候選店", "business_type": "炸雞", "county": "高雄市"},
        )
        with self.assertRaises(WorkspaceError) as raised:
            self.repository.get_case(self.other, case["id"])
        self.assertEqual(raised.exception.status, 403)

    def test_candidate_survey_and_submission_are_saved(self):
        case = self.repository.create_case(
            self.franchisee,
            {"title": "高雄候選店", "business_type": "炸雞", "county": "高雄市"},
        )
        candidate = self.repository.add_candidate(
            self.franchisee,
            {
                "case_id": case["id"],
                "address": "高雄市三民區建工路",
                "monthly_rent": 60000,
                "area_ping": 30,
                "report": {"scorecard": {"overall_score": 72}},
            },
        )
        survey = self.repository.add_survey(
            self.franchisee,
            {"candidate_id": candidate["id"], "onsite_count": 35, "notes": "晚餐時段"},
        )
        reviewed = self.repository.review_case(
            self.franchisee,
            {"case_id": case["id"], "action": "submit", "comment": "請協助評估"},
        )
        self.assertGreater(survey["id"], 0)
        self.assertEqual(reviewed["status"], "submitted")
        self.assertEqual(reviewed["candidates"][0]["report"]["scorecard"]["overall_score"], 72)
        self.assertEqual(reviewed["candidates"][0]["report_versions"][0]["version_number"], 1)
        self.assertEqual(self.repository.list_notifications(self.admin)[0]["event_type"], "submit")

        version = self.repository.add_report_version(
            self.franchisee,
            {
                "candidate_id": candidate["id"],
                "report": {"scorecard": {"overall_score": 78}},
            },
        )
        self.assertEqual(version["version_number"], 2)
        refreshed = self.repository.get_case(self.franchisee, case["id"])
        self.assertEqual(refreshed["candidates"][0]["report"]["scorecard"]["overall_score"], 78)

    def test_only_admin_can_close_case(self):
        case = self.repository.create_case(
            self.franchisee,
            {"title": "台南候選店", "business_type": "便當", "county": "台南市"},
        )
        with self.assertRaises(WorkspaceError):
            self.repository.review_case(
                self.franchisee, {"case_id": case["id"], "action": "close"}
            )
        closed = self.repository.review_case(
            self.admin, {"case_id": case["id"], "action": "close"}
        )
        self.assertEqual(closed["status"], "closed")

    def test_admin_can_create_user_and_assign_developer(self):
        created = self.repository.create_managed_user(
            self.admin,
            {
                "email": "new@example.com",
                "name": "新加盟主",
                "role": "franchisee",
                "password": "strong-pass-005",
            },
        )
        self.assertEqual(created["role"], "franchisee")
        case = self.repository.create_case(
            self.franchisee,
            {"title": "指派測試", "business_type": "火鍋", "county": "台北市"},
        )
        assigned = self.repository.assign_case(
            self.admin,
            {"case_id": case["id"], "developer_user_id": self.developer.id},
        )
        self.assertEqual(assigned["developer_user_id"], self.developer.id)
        developer_cases = self.repository.list_cases(self.developer)
        self.assertEqual(developer_cases[0]["id"], case["id"])


if __name__ == "__main__":
    unittest.main()
