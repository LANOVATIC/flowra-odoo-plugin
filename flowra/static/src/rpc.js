/** @odoo-module **/
// Part of Flowra. See LICENSE file for full copyright and licensing details.
// Odoo 17: `jsonrpc` from the rpc service module (18 renamed it `rpc` and moved it).
import { jsonrpc } from "@web/core/network/rpc_service";

export const flowraRpc = jsonrpc;
