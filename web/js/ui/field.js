import { html, raw } from "../core/dom.js";

export function Field({
  label = "",
  id,
  type = "text",
  value = "",
  help = "",
  error = "",
  min,
  max,
  rows,
  placeholder = "",
  attrs = "",
} = {}) {
  const invalid = Boolean(error);
  const extra = raw(
    [
      attrs || "",
      min != null ? `min="${min}"` : "",
      max != null ? `max="${max}"` : "",
    ]
      .filter(Boolean)
      .join(" ")
  );
  const control =
    type === "textarea"
      ? html`<textarea id="${id}" name="${id}" rows="${rows || 4}" placeholder="${placeholder}" ${extra}>${value}</textarea>`
      : html`<input id="${id}" name="${id}" type="${type}" value="${value}" placeholder="${placeholder}" ${extra}>`;
  return html`<div class="field ${invalid ? "is-invalid" : ""}">
    ${label ? html`<label for="${id}">${label}</label>` : ""}
    ${control}
    ${error ? html`<p class="error">${error}</p>` : help ? html`<p class="help">${help}</p>` : ""}
  </div>`;
}
