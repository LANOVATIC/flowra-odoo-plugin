# Part of Flowra. See LICENSE file for full copyright and licensing details.
"""The three places Odoo 17, 18 and 19 differ for this app (ODOO-PLUGIN-a, measured 2026-11-18).

Kept in one module so a fourth difference has an obvious home, and so nothing else in the app
reads `odoo.release`:

* `res.users.apikeys._generate` is `(scope, name)` on 17 and `(scope, name, expiration_date)`
  on 18 and 19.
* `@route(type='json')` is current on 17/18 and a deprecated alias of `'jsonrpc'` on 19.
* The backend lives at `/web` on 17 and `/odoo` from 18.
* `res.users.groups_id` is `group_ids` on 19 (ODOO-PLUGIN-b, measured on fresh images).
* `product.packaging` is gone on 19: a pack is a unit of measure (`uom.uom`, `relative_factor`
  over the product's unit) listed in the product's `uom_ids` (ODOO-PLUGIN-j2).
"""

from odoo import release

MAJOR = release.version_info[0]

#: The JSON route type this series expects.
JSON_ROUTE = "jsonrpc" if MAJOR >= 19 else "json"

#: Path of the backend client on this series.
BACKEND_PATH = "/odoo" if MAJOR >= 18 else "/web"

#: Odoo 19 models a pack as a unit of measure, not as a `product.packaging` row.
PACK_IS_UOM = MAJOR >= 19

#: The many2many from a user to their groups.
USER_GROUPS_FIELD = "group_ids" if MAJOR >= 19 else "groups_id"


def action_url(xmlid):
    """Backend URL that opens the window action *xmlid*."""
    if MAJOR >= 18:
        return f"/odoo/action-{xmlid}"
    return f"/web#action={xmlid}"


def generate_api_key(user, name, scope="rpc"):
    """Mint an API key for *user* and return it in clear — the only moment it exists in clear.

    Odoo stores the key hashed. No expiration: the key lives exactly as long as the connection,
    and disconnecting or uninstalling the app deletes it. From 18 a key without an expiration date
    may only be created in a superuser environment (`_check_expiration_date`), hence `sudo()`;
    `with_user` first, so the key still belongs to *user*.
    """
    keys = user.env["res.users.apikeys"].with_user(user).sudo()
    if MAJOR >= 18:
        return keys._generate(scope, name, False)
    return keys._generate(scope, name)
