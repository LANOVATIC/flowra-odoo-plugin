# Part of Flowra. See LICENSE file for full copyright and licensing details.
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.flowra import compat, connect_rules

_REQUESTS = "odoo.addons.flowra.models.flowra_connection.requests"
STORE = "https://erp.acme.test"


def _response(status, body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = str(body)
    return r


_OK = {
    "tenant_id": "11111111-2222-3333-4444-555555555555", "tenant_slug": "acme", "workspace_name": "Acme",
    "source_id": "66666666-7777-8888-9999-000000000000", "source_name": "Odoo · erp.acme.test",
    "reconnected": False, "embed_url": "https://dashboard.flowra.lanovatic.com/embed/ask?tenant=acme",
    "chat_enabled": True, "chat_detail": None,
}


@tagged("post_install", "-at_install")
class TestConnectRules(TransactionCase):
    def test_base_url(self):
        self.assertEqual(connect_rules.base_url("https://Flowra.Example.com/"), "https://flowra.example.com")
        self.assertIsNone(connect_rules.base_url("http://flowra.example.com"))
        self.assertIsNone(connect_rules.base_url("http://localhost:8000"))
        self.assertEqual(connect_rules.base_url("http://localhost:8000", True), "http://localhost:8000")
        self.assertIsNone(connect_rules.base_url("http://10.0.0.5", True))
        self.assertIsNone(connect_rules.base_url("https://u:p@flowra.example.com"))

    def test_signature_matches_flowra(self):
        # Vector computed with Flowra's own `shop_status.signature` (ODOO-PLUGIN-b).
        self.assertEqual(
            connect_rules.signature(
                "ab" * 20, "POST", connect_rules.DISCONNECT_PATH,
                "11111111-2222-3333-4444-555555555555", "1700000000",
            ),
            "e381301625efe49435244801dcaa83326bbe5996c4d5e6d0f45720a19ee4d3d7",
        )

    def test_approve_url(self):
        url = connect_rules.approve_url("https://app.test", STORE, STORE + "/flowra/connect/return", "st" * 8)
        parts = urlsplit(url)
        self.assertEqual(parts.path, "/connect/odoo")
        q = parse_qs(parts.query)
        self.assertEqual(q["store"], [STORE])
        self.assertEqual(q["return"], [STORE + "/flowra/connect/return"])


@tagged("post_install", "-at_install")
class TestConnection(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("web.base.url", STORE)
        self.Connection = self.env["flowra.connection"]
        # `_complete` commits so Flowra's own transaction can see the key; a test may not commit.
        committer = patch.object(type(self.Connection), "_commit", lambda self: None)
        committer.start()
        self.addCleanup(committer.stop)

    def _param(self, key):
        return self.env["ir.config_parameter"].sudo().get_param("flowra." + key)

    def test_service_user_is_internal_with_least_privilege(self):
        user = self.Connection._service_user()
        self.assertTrue(user.active)
        self.assertFalse(user.share)
        self.assertTrue(user.has_group("base.group_user"))
        self.assertTrue(user.has_group("purchase.group_purchase_user"))
        self.assertTrue(user.has_group("stock.group_stock_user"))
        self.assertFalse(user.has_group("base.group_system"))
        self.assertFalse(user.has_group("base.group_erp_manager"))
        self.assertFalse(user.has_group("purchase.group_purchase_manager"))
        self.assertFalse(user.has_group("stock.group_stock_manager"))
        self.assertTrue(user.has_group("flowra.group_flowra_service"))

    def test_complete_keeps_the_binding_and_a_working_key(self):
        with patch(_REQUESTS) as req:
            req.post.return_value = _response(200, _OK)
            self.Connection._complete("the-code")
        payload = req.post.call_args.kwargs["json"]
        self.assertEqual(req.post.call_args.args[0], connect_rules.DEFAULT_APP_URL + connect_rules.COMPLETE_PATH)
        self.assertEqual(payload["store_url"], STORE)
        self.assertEqual(payload["db"], self.env.cr.dbname)
        self.assertEqual(payload["login"], connect_rules.SERVICE_LOGIN)
        self.assertEqual(payload["code"], "the-code")
        self.assertEqual(self._param("source_id"), _OK["source_id"])
        self.assertEqual(self._param("api_key"), payload["api_key"])
        uid = self.env["res.users.apikeys"]._check_credentials(scope="rpc", key=payload["api_key"])
        self.assertEqual(uid, self.Connection._service_user(create=False).id)
        conn = self.Connection.create({})
        self.assertTrue(conn.connected)
        self.assertEqual(conn.workspace_name, "Acme")

    def test_a_refused_complete_leaves_no_key(self):
        with patch(_REQUESTS) as req:
            req.post.return_value = _response(422, {"detail": "store_check_failed:auth_failed"})
            req.RequestException = Exception
            with self.assertRaises(UserError):
                self.Connection._complete("the-code")
        user = self.Connection._service_user(create=False)
        self.assertFalse(self.env["res.users.apikeys"].sudo().search([("user_id", "=", user.id)]))
        self.assertFalse(self._param("source_id"))

    def test_reconnect_replaces_the_key(self):
        with patch(_REQUESTS) as req:
            req.post.return_value = _response(200, _OK)
            self.Connection._complete("one")
            self.Connection._complete("two")
        user = self.Connection._service_user(create=False)
        self.assertEqual(len(self.env["res.users.apikeys"].sudo().search([("user_id", "=", user.id)])), 1)

    def test_disconnect_signs_and_cleans_up(self):
        with patch(_REQUESTS) as req:
            req.post.return_value = _response(200, _OK)
            self.Connection._complete("the-code")
            key = self._param("api_key")
            req.request.return_value = _response(204, {})
            req.RequestException = Exception
            self.Connection._disconnect()
        method, url = req.request.call_args.args
        headers = req.request.call_args.kwargs["headers"]
        self.assertEqual((method, url), ("POST", connect_rules.DEFAULT_APP_URL + connect_rules.DISCONNECT_PATH))
        self.assertEqual(headers["X-Flowra-Source"], _OK["source_id"])
        self.assertEqual(
            headers["X-Flowra-Signature"],
            connect_rules.signature(key, "POST", connect_rules.DISCONNECT_PATH, _OK["source_id"], headers["X-Flowra-Timestamp"]),
        )
        user = self.Connection._service_user(create=False)
        self.assertFalse(user.active)
        self.assertFalse(self.env["res.users.apikeys"].sudo().search([("user_id", "=", user.id)]))
        self.assertFalse(self._param("source_id"))
        self.assertFalse(self._param("api_key"))


@tagged("post_install", "-at_install")
class TestConnectRoutes(HttpCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("web.base.url", STORE)

    def test_start_redirects_to_flowra_with_a_state(self):
        self.authenticate("admin", "admin")
        r = self.url_open("/flowra/connect/start", allow_redirects=False)
        self.assertIn(r.status_code, (302, 303))
        target = urlsplit(r.headers["Location"])
        self.assertEqual(f"{target.scheme}://{target.netloc}{target.path}", connect_rules.DEFAULT_APP_URL + "/connect/odoo")
        q = parse_qs(target.query)
        self.assertEqual(q["store"], [STORE])
        self.assertEqual(q["return"], [STORE + "/flowra/connect/return"])
        self.assertGreaterEqual(len(q["state"][0]), 16)

    def test_return_with_a_foreign_state_completes_nothing(self):
        self.authenticate("admin", "admin")
        with patch(_REQUESTS) as req:
            r = self.url_open("/flowra/connect/return?state=forged-state-1234&flowra_code=c", allow_redirects=False)
            req.post.assert_not_called()
        self.assertIn(r.status_code, (302, 303))
        self.assertIn("flowra.action_flowra_connection", r.headers["Location"])
        self.assertTrue(self.env["ir.config_parameter"].sudo().get_param("flowra.last_error"))

    def test_start_then_return_completes(self):
        self.authenticate("admin", "admin")
        r = self.url_open("/flowra/connect/start", allow_redirects=False)
        state = parse_qs(urlsplit(r.headers["Location"]).query)["state"][0]
        with patch(_REQUESTS) as req:
            req.post.return_value = _response(200, _OK)
            r = self.url_open(f"/flowra/connect/return?state={state}&flowra_code=the-code", allow_redirects=False)
            req.post.assert_called_once()
        self.assertEqual(self.env["ir.config_parameter"].sudo().get_param("flowra.source_id"), _OK["source_id"])
        # The state is single-use.
        with patch(_REQUESTS) as req:
            self.url_open(f"/flowra/connect/return?state={state}&flowra_code=again", allow_redirects=False)
            req.post.assert_not_called()

    def test_non_admin_cannot_start(self):
        user = self.env["res.users"].create({"name": "Clerk", "login": "clerk", "password": "clerk-pass-12345"})
        self.assertFalse(user.has_group("base.group_system"))
        self.authenticate("clerk", "clerk-pass-12345")
        r = self.url_open("/flowra/connect/start", allow_redirects=False)
        self.assertEqual(r.status_code, 403)
