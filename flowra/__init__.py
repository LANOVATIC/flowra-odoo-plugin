# Part of Flowra. See LICENSE file for full copyright and licensing details.
from . import compat, connect_rules, controllers, models


def uninstall_hook(env):
    """Uninstalling disconnects: Flowra pauses the source, the key is deleted, the user archived."""
    env["flowra.connection"]._disconnect()
