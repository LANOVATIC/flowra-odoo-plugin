# Part of Flowra. See LICENSE file for full copyright and licensing details.
"""Pure rules of the one-click connect (ODOO-PLUGIN-b). No Odoo import, so each is unit-tested.

Mirrors the WooCommerce plugin's `Domain\\Connect` and Flowra's `shop_status`: the same approve
URL shape, the same signed string (`flowra-shop/2`), the same loopback-only-in-development rule.
"""

import hashlib
import hmac
import ipaddress
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_APP_URL = "https://dashboard.flowra.lanovatic.com"
APPROVE_PATH = "/connect/odoo"
COMPLETE_PATH = "/api/v1/shop-connect/odoo/complete"
STATUS_PATH = "/api/v1/shop-connect/odoo/status"
DISCONNECT_PATH = "/api/v1/shop-connect/odoo/disconnect"
KEY_CHECK_PATH = "/api/v1/shop-connect/odoo/key-check"
SIGNATURE_SCHEME = "flowra-shop/2"

#: Seconds `complete` may take: Flowra logs in to this database and installs a source map.
COMPLETE_TIMEOUT = 90
#: Seconds for a status read or a disconnect.
CALL_TIMEOUT = 10

#: The dedicated Odoo user the API key belongs to (owner decision: one paid seat, least privilege).
SERVICE_LOGIN = "flowra-connector"
SERVICE_NAME = "Flowra"

_LOOPBACK_NAMES = {"localhost", "host.docker.internal"}


def is_loopback(host):
    host = (host or "").strip("[]").lower()
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def base_url(url, allow_http_loopback=False):
    """`scheme://host[:port][/path]` without a trailing slash, or None when the app must not use it.

    https always; plain http only to a loopback host and only when *allow_http_loopback* (the
    `flowra.dev_mode` system parameter) — the local playground's exception, never a default.
    """
    url = (url or "").strip()
    if not url:
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if not host or parts.username or parts.password or parts.query or parts.fragment:
        return None
    scheme = parts.scheme.lower()
    if scheme != "https" and not (scheme == "http" and allow_http_loopback and is_loopback(host)):
        return None
    netloc = f"{host}:{port}" if port else host
    return f"{scheme}://{netloc}{parts.path.rstrip('/')}"


def approve_url(app, store_url, return_url, state):
    """The page Flowra shows the approving admin. *app* must already be a `base_url()`."""
    return app + APPROVE_PATH + "?" + urlencode({"store": store_url, "return": return_url, "state": state})


def canonical_request(method, path, source_id, timestamp, body=b""):
    """What is signed — must equal Flowra's `shop_status.canonical_request`."""
    return "\n".join(
        (SIGNATURE_SCHEME, method.upper(), path, source_id, timestamp, hashlib.sha256(body).hexdigest())
    )


def signature(secret, method, path, source_id, timestamp, body=b""):
    message = canonical_request(method, path, source_id, timestamp, body)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def signed_headers(secret, method, path, source_id, now, body=b""):
    stamp = str(int(now))
    return {
        "X-Flowra-Source": source_id,
        "X-Flowra-Timestamp": stamp,
        "X-Flowra-Signature": signature(secret, method, path, source_id, stamp, body),
    }


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def chat_src(embed_url, source_id, allow_http_loopback=False):
    """The chat iframe URL: Flowra's embed widget pinned to this database's source, or None.

    Only a URL Flowra itself returned at connect time is used, and only over https (loopback http
    in development), so a tampered parameter cannot frame another site in Odoo's backend.
    """
    try:
        parts = urlsplit((embed_url or "").strip())
    except ValueError:
        return None
    base = base_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), allow_http_loopback)
    if not base:
        return None
    query = dict(parse_qsl(parts.query))
    if source_id and _UUID.match(source_id.lower()):
        query["source_id"] = source_id.lower()
    return base + ("?" + urlencode(query) if query else "")


def origin(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
