# Part of Flowra. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    #: Each person's own choice, not a database-wide setting (as in the WooCommerce plugin).
    flowra_chat_mode = fields.Selection(
        [("bubble", "Bubble"), ("page", "Full page only")], default="bubble", string="Flowra chat",
    )
