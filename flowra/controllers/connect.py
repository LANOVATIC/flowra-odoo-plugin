# Part of Flowra. See LICENSE file for full copyright and licensing details.
import hmac
import logging
import secrets

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from .. import compat, connect_rules

_logger = logging.getLogger(__name__)

_SESSION_STATE = "flowra_connect_state"
_ACTION = "flowra.action_flowra_connection"


def _require_admin():
    if not request.env.user.has_group("base.group_system"):
        raise Forbidden()


class FlowraConnect(http.Controller):
    @http.route("/flowra/connect/start", type="http", auth="user", methods=["GET"])
    def start(self, **kw):
        """Step 1: send the admin to Flowra's approve page with a single-use state."""
        _require_admin()
        Connection = request.env["flowra.connection"]
        app, store = Connection._app_url(), Connection._store_url()
        if not app or not store:
            Connection._set_param("last_error", "Flowra needs this database to be served over https (web.base.url).")
            return request.redirect(compat.action_url(_ACTION), local=True)
        state = secrets.token_urlsafe(24)
        request.session[_SESSION_STATE] = state
        target = connect_rules.approve_url(app, store, store + "/flowra/connect/return", state)
        return request.redirect(target, local=False)

    @http.route("/flowra/connect/return", type="http", auth="user", methods=["GET"])
    def connect_return(self, state="", flowra_code="", flowra_error="", **kw):
        """Step 3: Flowra sent the admin back with a one-time code; mint the key and complete."""
        _require_admin()
        expected = request.session.pop(_SESSION_STATE, None)
        Connection = request.env["flowra.connection"]
        if not expected or not state or not hmac.compare_digest(expected, state):
            Connection._set_param("last_error", "The connection link expired or was not started here. Try again.")
        elif flowra_error:
            Connection._set_param("last_error", "Connection cancelled in Flowra.")
        elif not flowra_code:
            Connection._set_param("last_error", "Flowra sent no connection code. Try again.")
        else:
            try:
                Connection._complete(flowra_code)
            except UserError as exc:
                _logger.warning("Flowra connect failed: %s", exc)
                Connection._set_param("last_error", str(exc.args[0] if exc.args else exc))
        return request.redirect(compat.action_url(_ACTION), local=True)
