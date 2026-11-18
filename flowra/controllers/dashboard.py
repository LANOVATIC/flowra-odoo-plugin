# Part of Flowra. See LICENSE file for full copyright and licensing details.
from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request

from .. import compat


def _may_see_dashboard(user):
    return user.has_group("base.group_system") or user.has_group("purchase.group_purchase_manager")


class FlowraDashboard(http.Controller):
    @http.route("/flowra/dashboard/data", type=compat.JSON_ROUTE, auth="user")
    def dashboard_data(self, refresh=False):
        if not _may_see_dashboard(request.env.user):
            raise Forbidden()
        return request.env["flowra.connection"]._dashboard(refresh=bool(refresh))

    @http.route("/flowra/chat/config", type=compat.JSON_ROUTE, auth="user")
    def chat_config(self):
        return request.env["flowra.connection"]._chat_config()

    @http.route("/flowra/chat/mode", type=compat.JSON_ROUTE, auth="user")
    def chat_mode(self, mode):
        """Each person sets their own preference; nobody else's record is touched."""
        if mode not in ("bubble", "page"):
            raise Forbidden()
        request.env.user.sudo().write({"flowra_chat_mode": mode})
        return {"mode": mode}
