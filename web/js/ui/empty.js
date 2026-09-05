import { html, raw } from "../core/dom.js";
import { Button } from "./button.js";
import { icon } from "./icons.js";

export function EmptyState({ iconName = "inbox", title = "", text = "", action = null, secondary = null } = {}) {
  return html`<div class="empty">
    <span aria-hidden="true">${raw(icon(iconName))}</span>
    <h3>${title}</h3>
    <p>${text}</p>
    <div class="task-actions">
      ${action ? Button({ variant: "primary", label: action.label, attrs: `data-empty-action="${action.id || "go"}"` }) : ""}
      ${secondary ? Button({ variant: "ghost", label: secondary.label, attrs: `data-empty-action="${secondary.id || "alt"}"` }) : ""}
    </div>
  </div>`;
}
