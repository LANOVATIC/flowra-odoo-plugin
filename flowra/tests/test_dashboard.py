# Part of Flowra. See LICENSE file for full copyright and licensing details.
import json
from unittest.mock import MagicMock, patch

from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.flowra import compat, connect_rules  # noqa: F401 — compat used in tests below

_REQUESTS = "odoo.addons.flowra.models.flowra_connection.requests"
SOURCE = "66666666-7777-8888-9999-000000000000"
EMBED = "https://dashboard.flowra.lanovatic.com/embed/ask?tenant=acme"
STATUS = {
    "workspace_name": "Acme", "tenant_slug": "acme", "source_id": SOURCE, "source_name": "Odoo",
    "source_active": True, "flowra_url": "https://dashboard.flowra.lanovatic.com",
    "source_url": "https://dashboard.flowra.lanovatic.com/data/x/overview",
    "sync": {"state": "success", "at": "2026-11-18T10:00:00Z", "rows_loaded": 12},
    "ml": {"state": "healthy", "last_trained_at": None}, "last_po_pushed_at": None, "pos_pushed": 3,
    "skills": [{"key": "chat", "state": "on", "setup_url": "https://x/chat"}], "map_warning": None,
}


def _bind(env, embed=EMBED):
    P = env["ir.config_parameter"].sudo()
    for k, v in {"source_id": SOURCE, "api_key": "ab" * 20, "workspace_name": "Acme",
                 "source_name": "Odoo", "embed_url": embed, "chat_enabled": "1"}.items():
        P.set_param("flowra." + k, v)


def _ok(body):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = body
    return r


@tagged("post_install", "-at_install")
class TestDashboard(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Connection = self.env["flowra.connection"]
        type(self.Connection)._status_cache.clear()

    def test_not_connected(self):
        data = self.Connection._dashboard()
        self.assertFalse(data["connected"])
        self.assertIsNone(data["status"])
        self.assertEqual(data["local"], {"draft_pos": 0, "open_signals": 0})

    def test_status_is_cached_and_refresh_bypasses_it(self):
        _bind(self.env)
        with patch(_REQUESTS) as req:
            req.request.return_value = _ok(STATUS)
            req.RequestException = Exception
            first = self.Connection._dashboard()
            self.Connection._dashboard()
            self.assertEqual(req.request.call_count, 1)
            self.Connection._dashboard(refresh=True)
            self.assertEqual(req.request.call_count, 2)
        self.assertEqual(first["status"]["sync"]["state"], "success")
        method, url = req.request.call_args.args
        self.assertEqual((method, url), ("GET", connect_rules.DEFAULT_APP_URL + connect_rules.STATUS_PATH))

    def test_an_unreachable_flowra_is_an_error_not_a_crash(self):
        _bind(self.env)
        with patch(_REQUESTS) as req:
            req.RequestException = OSError
            req.request.side_effect = OSError("down")
            data = self.Connection._dashboard()
        self.assertIsNone(data["status"])
        self.assertIn("Could not reach Flowra", data["error"])

    def test_local_counts_are_what_flowra_left_here(self):
        user = self.Connection._service_user()
        partner = self.env["res.partner"].create({"name": "Supplier"})
        self.env["purchase.order"].with_user(user).create({"partner_id": partner.id})
        self.env["purchase.order"].create({"partner_id": partner.id})  # not Flowra's
        kind = self.env.ref("flowra.mail_activity_type_flowra")
        self.env["mail.activity"].create({
            "activity_type_id": kind.id, "res_id": partner.id, "summary": "Reorder",
            "res_model_id": self.env["ir.model"]._get_id("res.partner"),
        })
        self.assertEqual(self.Connection._local_counts(), {"draft_pos": 1, "open_signals": 1})


@tagged("post_install", "-at_install")
class TestChatConfig(TransactionCase):
    def setUp(self):
        super().setUp()
        self.user = self.env["res.users"].create({"name": "Buyer", "login": "buyer-chat"})
        self.Connection = self.env["flowra.connection"].with_user(self.user)

    def _grant(self):
        self.user.write({compat.USER_GROUPS_FIELD: [(4, self.env.ref("flowra.group_flowra_chat").id)]})

    def test_outside_the_group_there_is_no_chat(self):
        _bind(self.env)
        self.assertEqual(self.Connection._chat_config(), {"allowed": False, "reason": "not_in_group"})

    def test_not_connected(self):
        self._grant()
        self.assertEqual(self.Connection._chat_config()["reason"], "not_connected")

    def test_the_frame_is_pinned_to_this_source(self):
        self._grant()
        _bind(self.env)
        config = self.Connection._chat_config()
        self.assertTrue(config["allowed"])
        self.assertIn("tenant=acme", config["src"])
        self.assertIn("source_id=" + SOURCE, config["src"])
        self.assertEqual(config["origin"], "https://dashboard.flowra.lanovatic.com")
        self.assertEqual(config["mode"], "bubble")

    def test_a_non_https_embed_url_is_never_framed(self):
        self._grant()
        _bind(self.env, embed="http://evil.example/embed/ask")
        self.assertEqual(self.Connection._chat_config()["reason"], "not_connected")

    def test_chat_src_rules(self):
        self.assertIsNone(connect_rules.chat_src("javascript:alert(1)", SOURCE))
        self.assertIsNone(connect_rules.chat_src("http://localhost:5173/embed/ask", SOURCE))
        self.assertEqual(
            connect_rules.chat_src("http://localhost:5173/embed/ask?tenant=a", "not-a-uuid", True),
            "http://localhost:5173/embed/ask?tenant=a",
        )


@tagged("post_install", "-at_install")
class TestDashboardRoutes(HttpCase):
    def _json(self, url, params=None):
        r = self.url_open(url, data=json.dumps({"jsonrpc": "2.0", "params": params or {}}),
                          headers={"Content-Type": "application/json"})
        return r.json()

    def test_admin_reads_the_dashboard(self):
        self.authenticate("admin", "admin")
        body = self._json("/flowra/dashboard/data")
        self.assertIn("result", body, body)
        self.assertFalse(body["result"]["connected"])

    def test_a_plain_user_cannot(self):
        # Only "Internal user": on 17/18 a new user inherits the default template's groups, which
        # include purchase manager on a fresh database.
        self.env["res.users"].create({
            "name": "Clerk", "login": "clerk2", "password": "clerk-pass-12345",
            compat.USER_GROUPS_FIELD: [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.authenticate("clerk2", "clerk-pass-12345")
        body = self._json("/flowra/dashboard/data")
        self.assertIn("error", body)

    def test_each_user_sets_their_own_chat_mode(self):
        user = self.env["res.users"].create({"name": "Clerk", "login": "clerk3", "password": "clerk-pass-12345"})
        self.authenticate("clerk3", "clerk-pass-12345")
        self.assertEqual(self._json("/flowra/chat/mode", {"mode": "page"})["result"], {"mode": "page"})
        self.assertEqual(user.flowra_chat_mode, "page")
        self.assertIn("error", self._json("/flowra/chat/mode", {"mode": "everyone"}))
