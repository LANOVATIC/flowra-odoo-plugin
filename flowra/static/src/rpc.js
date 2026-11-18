/** @odoo-module **/
// Part of Flowra. See LICENSE file for full copyright and licensing details.
// Odoo 18+ exports `rpc`; 17 has `jsonrpc` (series/17.0 overlays this file). The only place the
// app's JavaScript differs per series.
import { rpc } from "@web/core/network/rpc";

export const flowraRpc = rpc;
