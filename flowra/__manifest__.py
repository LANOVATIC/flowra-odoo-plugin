# Part of Flowra. See LICENSE file for full copyright and licensing details.
{
    "name": "Flowra",
    "summary": "Demand forecasts, stock-risk signals and purchase orders you approve, inside Odoo",
    "description": """
Connects this Odoo database to Flowra (https://flowra.lanovatic.com).
Flowra reads your sales, purchases, products and stock through Odoo's external API and writes
back only to Odoo's own objects: draft purchase orders, chatter notes and activities.
This app adds the connection, a dashboard, the Flowra chat and a Flowra activity type.
""",
    # Stamped per Odoo series by dev/build.sh (17.0.x.y.z / 18.0.x.y.z / 19.0.x.y.z).
    "version": "19.0.1.0.0",
    "category": "Inventory/Purchase",
    "author": "Lanovatic",
    "website": "https://flowra.lanovatic.com/p/odoo.html",
    "support": "contact@lanovatic.com",
    "license": "LGPL-3",
    "depends": ["mail", "purchase", "stock"],
    "data": [
        "security/flowra_security.xml",
        "security/ir.model.access.csv",
        "data/mail_activity_type.xml",
        "views/flowra_connection_views.xml",
        "views/flowra_actions.xml",
        "views/flowra_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "flowra/static/src/rpc.js",
            "flowra/static/src/dashboard.js",
            "flowra/static/src/dashboard.xml",
            "flowra/static/src/chat.js",
            "flowra/static/src/chat.xml",
            "flowra/static/src/flowra.css",
        ],
    },
    "images": ["static/description/icon.png"],
    "application": True,
    "uninstall_hook": "uninstall_hook",
    "external_dependencies": {"python": ["requests"]},
    "installable": True,
    "price": 0.0,
    "currency": "EUR",
}
