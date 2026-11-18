/** @odoo-module **/
// Part of Flowra. See LICENSE file for full copyright and licensing details.
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { flowraRpc } from "./rpc";

/** What each skill key is called on the dashboard. Keys come from Flowra's `ShopStatus.skills`. */
const SKILL_LABELS = {
    chat: "Chat",
    purchase_orders: "Purchase orders",
    notes: "Notes and activities",
    insights: "Insights",
    automations: "Automations",
    telegram: "Telegram",
    email: "Email",
    slack: "Slack",
    teams: "Microsoft Teams",
    simulator: "Simulator",
};
const STATE_LABELS = { on: "On", off: "Not set up", available: "Available" };
// Same words as the PrestaShop and WooCommerce dashboards (ML health states, `MLHealthState`).
const ML_LABELS = {
    healthy: "Up to date", training: "Running now", stale: "Out of date",
    degraded: "Partly up to date", failed: "Last run failed", no_data: "Waiting for data",
};
const SYNC_LABELS = { never: "Never", queued: "Queued", running: "Running", success: "Succeeded", failed: "Failed" };

/**
 * Flowra → Dashboard (ODOO-PLUGIN-d): the connection, the last sync, forecasts, purchase orders and
 * skills, as Flowra reports them for this database, plus what Flowra left here. Read-only; every
 * number comes from the server — the component formats, it does not compute.
 */
export class FlowraDashboard extends Component {
    static template = "flowra.Dashboard";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.state = useState({ loading: true, data: null, failed: null });
        onWillStart(() => this.load(false));
    }

    async load(refresh) {
        this.state.loading = true;
        try {
            this.state.data = await flowraRpc("/flowra/dashboard/data", { refresh });
            this.state.failed = null;
        } catch (e) {
            this.state.failed = (e && e.message) || "Could not load the Flowra dashboard.";
        }
        this.state.loading = false;
    }

    open(xmlid) {
        this.action.doAction(xmlid);
    }

    when(value) {
        return value ? String(value).replace("T", " ").slice(0, 16) + " UTC" : "—";
    }

    skillLabel(key) {
        return SKILL_LABELS[key] || key;
    }

    stateLabel(state) {
        return STATE_LABELS[state] || state;
    }

    mlLabel(state) {
        return ML_LABELS[state] || ML_LABELS.no_data;
    }

    syncLabel(state) {
        return SYNC_LABELS[state] || state;
    }
}

registry.category("actions").add("flowra.dashboard", FlowraDashboard);
