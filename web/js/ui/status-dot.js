import { html } from "../core/dom.js";

export function StatusDot({ status = "ok", label = "" } = {}) {
  const cls = status === "ok" ? "is-ok" : status === "warn" ? "is-warn" : "is-bad";
  return html`<span class="status-dot ${cls}"><i></i>${label}</span>`;
}
