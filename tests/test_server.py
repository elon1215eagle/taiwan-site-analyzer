import os
import unittest
from unittest.mock import patch

from tw_site_analyzer.server import bootstrap_workspace_admin


class FailingRepository:
    def create_user(self, *_args, **_kwargs):
        raise RuntimeError("database offline")


class ExistingAdminRepository:
    def create_user(self, *_args, **_kwargs):
        from tw_site_analyzer.workspace import WorkspaceError

        raise WorkspaceError("EMAIL_EXISTS", "already exists")


class ServerStartupTest(unittest.TestCase):
    def test_admin_bootstrap_degrades_without_crashing_when_database_is_offline(self):
        with patch.dict(
            os.environ,
            {"GDO_ADMIN_EMAIL": "admin@example.com", "GDO_ADMIN_PASSWORD": "password-123"},
            clear=False,
        ):
            self.assertEqual("degraded", bootstrap_workspace_admin(FailingRepository()))

    def test_existing_admin_is_ready(self):
        with patch.dict(
            os.environ,
            {"GDO_ADMIN_EMAIL": "admin@example.com", "GDO_ADMIN_PASSWORD": "password-123"},
            clear=False,
        ):
            self.assertEqual("ready", bootstrap_workspace_admin(ExistingAdminRepository()))


if __name__ == "__main__":
    unittest.main()
