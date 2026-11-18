/** @odoo-module **/
// Part of Flowra. See LICENSE file for full copyright and licensing details.
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { flowraRpc } from "./rpc";

/** The widget and its host agree on this message: expand / collapse (same as the WooCommerce plugin). */
const RESIZE = "flowra:embed:resize";

async function loadConfig() {
    try {
        return await flowraRpc("/flowra/chat/config", {});
    } catch {
        return { allowed: false, reason: "error" };
    }
}

/** Listen to resize requests from *our* iframe only. */
function useResizeMessages(frameRef, getOrigin, onResize) {
    const handler = (event) => {
        const frame = frameRef.el;
        if (!frame || event.source !== frame.contentWindow || event.origin !== getOrigin()) {
            return;
        }
        if (event.data && event.data.type === RESIZE) {
            onResize(Boolean(event.data.expanded));
        }
    };
    onMounted(() => window.addEventListener("message", handler));
    onWillUnmount(() => window.removeEventListener("message", handler));
}

/**
 * Flowra → Chat: the chat as a full page (ODOO-PLUGIN-d). Each person signs in with their own Flowra
 * account inside the frame; this app only decides who sees it (group "Flowra: chat").
 */
export class FlowraChatPage extends Component {
    static template = "flowra.ChatPage";
    static props = ["*"];

    setup() {
        this.frame = useRef("frame");
        this.state = useState({ config: null });
        onWillStart(async () => {
            this.state.config = await loadConfig();
        });
        useResizeMessages(this.frame, () => this.state.config && this.state.config.origin, () => {});
    }

    onFrameLoad() {
        const frame = this.frame.el;
        if (frame && frame.contentWindow && this.state.config.origin) {
            frame.contentWindow.postMessage({ type: RESIZE, expanded: true }, this.state.config.origin);
        }
    }

    async setMode(mode) {
        await flowraRpc("/flowra/chat/mode", { mode });
        this.state.config.mode = mode;
    }
}

/**
 * The bubble, on every backend page for the people who chose it (ODOO-PLUGIN-d). The iframe is
 * created the first time it opens, so a closed bubble costs Flowra nothing.
 */
export class FlowraChatBubble extends Component {
    static template = "flowra.ChatBubble";
    static props = ["*"];

    setup() {
        this.frame = useRef("frame");
        this.state = useState({ config: null, open: false, opened: false, expanded: false });
        onWillStart(async () => {
            this.state.config = await loadConfig();
        });
        useResizeMessages(this.frame, () => this.state.config && this.state.config.origin, (expanded) => {
            this.state.expanded = expanded;
        });
    }

    get visible() {
        const config = this.state.config;
        return Boolean(config && config.allowed && config.mode === "bubble");
    }

    toggle() {
        this.state.open = !this.state.open;
        this.state.opened = this.state.opened || this.state.open;
    }
}

registry.category("actions").add("flowra.chat", FlowraChatPage);
registry.category("main_components").add("flowra.ChatBubble", { Component: FlowraChatBubble });
