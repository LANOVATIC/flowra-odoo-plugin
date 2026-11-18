# Part of Flowra. See LICENSE file for full copyright and licensing details.
"""Narrow write methods for Flowra's own user (ODOO-PLUGIN-e1, owner decision 2026-11-18).

The Flowra user is least-privilege: it reads sales, purchases, stock and invoicing and creates
purchase orders, but it may not edit products or contacts — and Odoo requires edit rights on a
record to put an activity or a note on it. Rather than widen the user, the app exposes exactly two
writes, run with elevated rights inside Odoo and refused to anyone who is not the Flowra user:

* `schedule_activity` — one activity of type "Flowra" on a product, contact or purchase order;
* `post_note` — one internal log note (`mail.mt_note`, which notifies nobody) on the same;
* `ensure_packaging` — the pack a purchase order line is ordered in (ODOO-PLUGIN-j2): a
  `product.packaging` on 17/18, a unit of measure linked to the product on 19. Found by its size,
  created only when the product has no pack of that size.

Nothing else is reachable through it: no other field is written, no other record created, and only
the three models below are accepted. Flowra still decides *whether* to write
(three gates on its side); this only decides *how* the write lands in Odoo.
"""

from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools import float_compare

from .. import compat
from odoo.exceptions import AccessError, UserError
from odoo.tools import html_sanitize

#: The records a Flowra finding is about.
ALLOWED_MODELS = ("product.product", "res.partner", "purchase.order")
BRIDGE_VERSION = 2


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
        return {"version": BRIDGE_VERSION, "actions": ["schedule_activity", "post_note", "ensure_packaging"]}

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

    @api.model
    def ensure_packaging(self, product_id, quantity, name):
        """The id of *product_id*'s pack of *quantity* units, created when it has none.

        Matched on the size, never the name: the quantity is the fact, and a pack renamed by the
        tenant is still the same pack. On 19 the id is a `uom.uom` (put it on the order line's
        `product_uom_id`); before 19 a `product.packaging` (`product_packaging_id`).
        """
        self._check_caller()
        quantity = float(quantity)
        if quantity <= 1:
            raise UserError("A pack holds more than one unit.")
        name = (name or "").strip() or f"Pack ×{quantity:g}"
        product = self._target("product.product", product_id)
        if compat.PACK_IS_UOM:
            return self._pack_uom(product, quantity, name).id
        Packaging = self.env["product.packaging"].sudo()
        for packaging in Packaging.search([("product_id", "=", product.id)]):
            if float_compare(packaging.qty, quantity, precision_digits=6) == 0:
                return packaging.id
        return Packaging.create({"name": name, "product_id": product.id, "qty": quantity, "purchase": True}).id

    @api.model
    def _pack_uom(self, product, quantity, name):
        base = product.uom_id
        for uom in product.uom_ids:
            if uom.relative_uom_id == base and float_compare(uom.relative_factor, quantity, precision_digits=6) == 0:
                return uom
        Uom = self.env["uom.uom"].sudo()
        uom = next(
            (u for u in Uom.search([("relative_uom_id", "=", base.id)])
             if float_compare(u.relative_factor, quantity, precision_digits=6) == 0),
            None,
        ) or Uom.create({"name": name, "relative_uom_id": base.id, "relative_factor": quantity})
        product.product_tmpl_id.sudo().write({"uom_ids": [(4, uom.id)]})
        return uom
