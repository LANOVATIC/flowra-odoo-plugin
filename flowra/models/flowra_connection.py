# Part of Flowra. See LICENSE file for full copyright and licensing details.
"""The connection to Flowra: one binding per database, kept in system parameters.

System parameters (`ir.config_parameter`) are readable by administrators only, which is the
right audience: the binding holds the API key the app minted, the only clear copy that exists
(Odoo stores keys hashed), and the app needs it to sign its status and disconnect calls — the
PrestaShop module keeps its webservice key the same way.
"""

import logging
import threading
import time

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .. import compat, connect_rules

_logger = logging.getLogger(__name__)

PARAM = "flowra.%s"
#: Binding keys, cleared together on disconnect.
BINDING_KEYS = (
    "api_key", "source_id", "tenant_id", "tenant_slug", "workspace_name", "source_name",
    "embed_url", "chat_enabled", "connected_at", "map_warning", "connected_by_uid",
)
#: Groups the service user gets when the module defining them is installed: read what Flowra reads,
#: write the purchase orders, activities and tasks it writes — nothing administrative.
SERVICE_GROUPS = (
    "base.group_user",
    "flowra.group_flowra_service",
    "purchase.group_purchase_user",
    "stock.group_stock_user",
    "sales_team.group_sale_salesman_all_leads",
    "account.group_account_readonly",
    "project.group_project_user",
)


class FlowraConnection(models.TransientModel):
    _name = "flowra.connection"
    _description = "Flowra connection"

    connected = fields.Boolean(compute="_compute_binding")
    workspace_name = fields.Char(compute="_compute_binding")
    source_name = fields.Char(compute="_compute_binding")
    connected_at = fields.Char(compute="_compute_binding")
    chat_enabled = fields.Boolean(compute="_compute_binding")
    last_error = fields.Char(compute="_compute_binding")
    map_warning = fields.Char(compute="_compute_binding")
    app_url = fields.Char(compute="_compute_binding")

    # --- the binding --------------------------------------------------------------------------

    @api.model
    def _param(self, key, default=None):
        return self.env["ir.config_parameter"].sudo().get_param(PARAM % key, default)

    @api.model
    def _set_param(self, key, value):
        self.env["ir.config_parameter"].sudo().set_param(PARAM % key, value or False)

    @api.model
    def _dev_mode(self):
        return self._param("dev_mode") == "1"

    @api.model
    def _app_url(self):
        """Flowra's app origin (its API is served under it). Overridable for development only."""
        return connect_rules.base_url(self._param("app_url") or connect_rules.DEFAULT_APP_URL, self._dev_mode())

    @api.model
    def _api_url(self):
        return connect_rules.base_url(self._param("api_url") or self._app_url(), self._dev_mode())

    @api.model
    def _store_url(self):
        return connect_rules.base_url(self._param_web_base(), self._dev_mode())

    @api.model
    def _param_web_base(self):
        return self.env["ir.config_parameter"].sudo().get_param("web.base.url")

    @api.depends_context("uid")
    def _compute_binding(self):
        for rec in self:
            rec.connected = bool(self._param("source_id"))
            rec.workspace_name = self._param("workspace_name")
            rec.source_name = self._param("source_name")
            rec.connected_at = self._param("connected_at")
            rec.chat_enabled = self._param("chat_enabled") == "1"
            rec.last_error = self._param("last_error")
            rec.map_warning = self._param("map_warning")
            rec.app_url = self._app_url()

    # --- the service user ---------------------------------------------------------------------

    @api.model
    def _service_user(self, create=True):
        Users = self.env["res.users"].sudo().with_context(active_test=False)
        user = Users.search([("login", "=", connect_rules.SERVICE_LOGIN)], limit=1)
        if not user and create:
            user = Users.create({"name": connect_rules.SERVICE_NAME, "login": connect_rules.SERVICE_LOGIN})
        if user and create:
            # Exactly these groups, replaced on every connect: on 17/18 a new user inherits the
            # default user template's groups (product and purchase *manager* on a fresh database),
            # which would quietly undo least privilege (found by test_bridge, ODOO-PLUGIN-e1).
            groups = [self.env.ref(x, raise_if_not_found=False) for x in SERVICE_GROUPS]
            ids = [g.id for g in groups if g]
            user.write({"active": True, compat.USER_GROUPS_FIELD: [(6, 0, ids)]})
        return user

    @api.model
    def _revoke_keys(self, user):
        if user:
            self.env["res.users.apikeys"].sudo().search([("user_id", "=", user.id)]).unlink()

    # --- connect --------------------------------------------------------------------------------

    def action_connect(self):
        """Send the admin to Flowra's approve page through the app's own start route."""
        self.env["ir.config_parameter"].sudo().set_param(PARAM % "last_error", False)
        return {"type": "ir.actions.act_url", "url": "/flowra/connect/start", "target": "self"}

    @api.model
    def _complete(self, code):
        """Mint the key, hand it to Flowra with the code, keep the binding. Raises `UserError`."""
        api_url, store = self._api_url(), self._store_url()
        if not api_url or not store:
            raise UserError(_("Flowra needs this database to be served over https (web.base.url)."))
        user = self._service_user()
        self._revoke_keys(user)  # one key per binding: a reconnect replaces it
        key = compat.generate_api_key(user, "Flowra")
        # Flowra checks the key by logging in over XML-RPC, from its own transaction: the user and
        # the key must be committed before it is asked, or it sees neither and refuses (found by
        # the live e2e, ODOO-PLUGIN-b). Tests run inside one transaction that must not commit.
        self._commit()
        payload = {
            "code": code, "store_url": store, "db": self.env.cr.dbname,
            "login": connect_rules.SERVICE_LOGIN, "api_key": key,
        }
        try:
            r = requests.post(api_url + connect_rules.COMPLETE_PATH, json=payload, timeout=connect_rules.COMPLETE_TIMEOUT)
        except requests.RequestException as exc:
            self._revoke_keys(user)
            raise UserError(_("Could not reach Flowra: %s", exc)) from exc
        if r.status_code != 200:
            self._revoke_keys(user)
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:200]
            raise UserError(_("Flowra refused the connection (%(status)s: %(detail)s).", status=r.status_code, detail=detail))
        body = r.json()
        self._set_param("api_key", key)
        self._set_param("source_id", body["source_id"])
        self._set_param("tenant_id", body["tenant_id"])
        self._set_param("tenant_slug", body["tenant_slug"])
        self._set_param("workspace_name", body["workspace_name"])
        self._set_param("source_name", body["source_name"])
        self._set_param("embed_url", body.get("embed_url"))
        self._set_param("chat_enabled", "1" if body.get("chat_enabled") else False)
        self._set_param("connected_at", fields.Datetime.to_string(fields.Datetime.now()))
        self._set_param("map_warning", body.get("map_warning"))
        # Activities Flowra files without a named assignee go to the admin who connected it.
        self._set_param("connected_by_uid", str(self.env.uid))
        self._status_cache.pop(self.env.cr.dbname, None)
        self._set_param("last_error", False)
        _logger.info("Flowra connected: source %s", body["source_id"])
        return body

    @api.model
    def _commit(self):
        if not getattr(threading.current_thread(), "testing", False):
            self.env.cr.commit()

    # --- signed calls -------------------------------------------------------------------------

    @api.model
    def _signed_call(self, method, path, timeout=connect_rules.CALL_TIMEOUT):
        key, source_id, api_url = self._param("api_key"), self._param("source_id"), self._api_url()
        if not (key and source_id and api_url):
            return None
        headers = connect_rules.signed_headers(key, method, path, source_id, time.time())
        return requests.request(method, api_url + path, headers=headers, timeout=timeout)

    @api.model
    def _status(self):
        r = self._signed_call("GET", connect_rules.STATUS_PATH)
        return r.json() if r is not None and r.status_code == 200 else None

    # --- dashboard ------------------------------------------------------------------------------

    #: Flowra status per database, kept for `STATUS_TTL` seconds: a dashboard open in many tabs must
    #: not become a request per tab per refresh. `(dbname) -> (fetched_at, status | None, error)`.
    _status_cache = {}
    STATUS_TTL = 300

    @api.model
    def _dashboard(self, refresh=False):
        """Everything the Dashboard shows. States and counts only — no business data from Flowra."""
        connected = bool(self._param("source_id"))
        data = {
            "connected": connected,
            "workspace_name": self._param("workspace_name"),
            "source_name": self._param("source_name"),
            "connected_at": self._param("connected_at"),
            "is_admin": self.env.user.has_group("base.group_system"),
            "status": None,
            "error": None,
            "local": self._local_counts(),
        }
        if not connected:
            return data
        key = self.env.cr.dbname
        cached = self._status_cache.get(key)
        if cached and not refresh and time.time() - cached[0] < self.STATUS_TTL:
            data["status"], data["error"] = cached[1], cached[2]
            return data
        status, error = None, None
        try:
            status = self._status()
            if status is None:
                error = "Flowra did not answer for this connection. Reconnect if this persists."
        except requests.RequestException as exc:
            error = f"Could not reach Flowra: {exc}"
        self._status_cache[key] = (time.time(), status, error)
        data["status"], data["error"] = status, error
        return data

    @api.model
    def _local_counts(self):
        """What Flowra left in this database, counted here (Odoo is the record for these)."""
        user = self._service_user(create=False)
        activity_type = self.env.ref("flowra.mail_activity_type_flowra", raise_if_not_found=False)
        draft_pos = 0
        if user:
            draft_pos = self.env["purchase.order"].sudo().search_count(
                [("create_uid", "=", user.id), ("state", "in", ("draft", "sent"))]
            )
        open_signals = 0
        if activity_type:
            open_signals = self.env["mail.activity"].sudo().search_count(
                [("activity_type_id", "=", activity_type.id)]
            )
        return {"draft_pos": draft_pos, "open_signals": open_signals}

    # --- chat -----------------------------------------------------------------------------------

    @api.model
    def _chat_config(self):
        """The iframe for this user, or why there is none. The chat signs each person in with their
        own Flowra account; this app only decides who sees it (group "Flowra: chat")."""
        user = self.env.user
        if not user.has_group("flowra.group_flowra_chat"):
            return {"allowed": False, "reason": "not_in_group"}
        embed, source_id = self._param("embed_url"), self._param("source_id")
        src = connect_rules.chat_src(embed, source_id, self._dev_mode())
        if not src:
            return {"allowed": False, "reason": "not_connected"}
        return {
            "allowed": True,
            "src": src,
            "origin": connect_rules.origin(src),
            "mode": user.flowra_chat_mode or "bubble",
            "host_allowed": self._param("chat_enabled") == "1",
        }

    # --- disconnect -----------------------------------------------------------------------------

    @api.model
    def _disconnect(self):
        """Tell Flowra (best effort), delete the key, archive the service user, forget the binding."""
        try:
            self._signed_call("POST", connect_rules.DISCONNECT_PATH)
        except requests.RequestException as exc:
            _logger.warning("Flowra disconnect call failed, disconnecting locally: %s", exc)
        user = self._service_user(create=False)
        self._revoke_keys(user)
        if user:
            user.write({"active": False})
        for key in BINDING_KEYS:
            self._set_param(key, False)

    def action_disconnect(self):
        self._disconnect()
        return {"type": "ir.actions.client", "tag": "reload"}
