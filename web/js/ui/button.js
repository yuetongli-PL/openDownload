import { html, raw } from "../core/dom.js";

export function Button({
  variant = "secondary",
  label = "",
  type = "button",
  loading = false,
  disabled = false,
  attrs = "",
  icon = "",
} = {}) {
  const cls = ["btn", `btn-${variant}`, loading ? "is-loading" : ""].filter(Boolean).join(" ");
  return html`<button
    type="${type}"
    class="${cls}"
    ${disabled || loading ? "disabled" : ""}
    aria-busy="${loading ? "true" : "false"}"
    ${raw(attrs)}
  >${icon ? raw(icon) : ""}${label}</button>`;
}
