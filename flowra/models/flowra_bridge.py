# Part of Flowra. See LICENSE file for full copyright and licensing details.
"""Narrow write methods for Flowra's own user (ODOO-PLUGIN-e1, owner decision 2026-11-18).

The Flowra user is least-privilege: it reads sales, purchases, stock and invoicing and creates
purchase orders, but it may not edit products or contacts — and Odoo requires edit rights on a
record to put an activity or a note on it. Rather than widen the user, the app exposes exactly two
writes, run with elevated rights inside Odoo and refused to anyone who is not the Flowra user:

* `schedule_activity` — one activity of type "Flowra" on a product, contact or purchase order;
* `post_note` — one internal log note (`mail.mt_note`, which notifies nobody) on the same.

Nothing else is reachable through it: no field is written, no record created besides the activity
or note, and only the three models below are accepted. Flowra still decides *whether* to write
(three gates on its side); this only decides *how* the write lands in Odoo.
"""

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html_sanitize

#: The records a Flowra finding is about.
ALLOWED_MODELS = ("product.product", "res.partner", "purchase.order")
BRIDGE_VERSION = 1


class FlowraBridge(models.AbstractModel):
    _name = "flowra.bridge"
    _description = "Flowra write bridge"

    @api.model
    def _check_caller(self):
        if not self.env.user.has_group("flowra.group_flowra_service"):
            raise AccessError("Only the Flowra user may call the Flowra bridge.")

    @api.model
    def _target(self, model, res_id):
        if model not in ALLOWED_MODELS:
            raise AccessError(f"The Flowra bridge does not write on {model}.")
        record = self.env[model].sudo().browse(int(res_id)).exists()
        if not record:
            raise UserError(f"{model} {res_id} does not exist.")
        return record

    @api.model
    def _assignee(self, user_id):
        """The person who gets the activity: the one Flowra named, else the admin who connected
        Flowra — never the Flowra user, whose list nobody reads."""
        Users = self.env["res.users"].sudo()
        if user_id:
            user = Users.browse(int(user_id)).exists()
            if not user or not user.active or user.share:
                raise UserError(f"User {user_id} is not an active internal user.")
            return user
        connected_by = self.env["ir.config_parameter"].sudo().get_param("flowra.connected_by_uid")
        user = Users.browse(int(connected_by)).exists() if connected_by else Users.browse()
        return user if user and user.active else self.env.ref("base.user_admin")

    @api.model
    def capabilities(self):
        """What this bridge can do. Flowra asks once per client to decide which path to take."""
        self._check_caller()
        return {"version": BRIDGE_VERSION, "actions": ["schedule_activity", "post_note"]}

    @api.model
    def schedule_activity(self, model, res_id, summary, date_deadline, note=False, user_id=False):
        self._check_caller()
        summary = (summary or "").strip()
        if not summary:
            raise UserError("An activity needs a summary.")
        record = self._target(model, res_id)
        # No assignment email: it would come "from" the Flowra user, which has no mailbox, and a
        # finding belongs in the assignee's activity list, not their inbox (the WooCommerce plugin
        # does not email either). `mail_activity_quick_update` is Odoo's own switch for that.
        activity = record.with_context(mail_activity_quick_update=True).activity_schedule(
            "flowra.mail_activity_type_flowra",
            date_deadline=fields.Date.to_date(date_deadline),
            summary=summary,
            note=Markup(html_sanitize(note)) if note else "",
            user_id=self._assignee(user_id).id,
        )
        return activity.id

    @api.model
    def post_note(self, model, res_id, body, subject=False):
        self._check_caller()
        if not (body or "").strip():
            raise UserError("A note needs a body.")
        record = self._target(model, res_id)
        message = record.message_post(
            body=body, subject=subject or None, message_type="comment", subtype_xmlid="mail.mt_note",
        )
        return message.id
