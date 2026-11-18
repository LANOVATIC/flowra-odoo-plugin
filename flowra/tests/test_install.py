# Part of Flowra. See LICENSE file for full copyright and licensing details.
from odoo import release
from odoo.tests import TransactionCase, tagged

from odoo.addons.flowra import compat


@tagged("post_install", "-at_install")
class TestInstall(TransactionCase):
    def test_data_is_installed(self):
        self.assertTrue(self.env.ref("flowra.group_flowra_chat"))
        self.assertEqual(self.env.ref("flowra.mail_activity_type_flowra").name, "Flowra")
        action = self.env.ref("flowra.action_flowra_signals")
        self.assertEqual(action.res_model, "mail.activity")

    def test_signals_view_mode_matches_the_series(self):
        first = self.env.ref("flowra.action_flowra_signals").view_mode.split(",")[0]
        self.assertEqual(first, "list" if release.version_info[0] >= 18 else "tree")

    def test_compat_constants(self):
        major = release.version_info[0]
        self.assertEqual(compat.MAJOR, major)
        self.assertEqual(compat.BACKEND_PATH, "/odoo" if major >= 18 else "/web")
        self.assertEqual(compat.JSON_ROUTE, "jsonrpc" if major >= 19 else "json")

    def test_generate_api_key_authenticates(self):
        user = self.env["res.users"].create({"name": "Flowra test", "login": "flowra-test-key"})
        key = compat.generate_api_key(user, "flowra-test")
        self.assertTrue(key)
        row = self.env["res.users.apikeys"].sudo().search([("user_id", "=", user.id)])
        self.assertEqual(len(row), 1)
        self.assertEqual(row.scope, "rpc")
        uid = self.env["res.users.apikeys"]._check_credentials(scope="rpc", key=key)
        self.assertEqual(uid, user.id)
