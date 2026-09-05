import { html, raw, qs, focusTrap } from "../core/dom.js";
import { icon } from "./icons.js";

let lastFocus = null;
let releaseTrap = null;

export function Dialog({ title = "", body = "", foot = "", id = "od-dialog" } = {}) {
  return html`<dialog class="od-dialog" id="${id}" aria-labelledby="${id}-title">
    <div class="od-dialog-head">
      <h2 id="${id}-title">${title}</h2>
      <button type="button" class="icon-btn" data-dialog-close aria-label="关闭">${raw(icon("close"))}</button>
    </div>
    <div class="od-dialog-body">${raw(body)}</div>
    ${foot ? html`<div class="od-dialog-foot">${raw(foot)}</div>` : ""}
  </dialog>`;
}

export function openDialog(host, markup) {
  lastFocus = document.activeElement;
  host.innerHTML = markup;
  const dlg = qs("dialog", host);
  if (!dlg) return null;
  if (!dlg.open) dlg.showModal();
  releaseTrap = focusTrap(dlg);
  const onClose = () => {
    if (releaseTrap) releaseTrap();
    releaseTrap = null;
    host.innerHTML = "";
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  };
  dlg.addEventListener("close", onClose, { once: true });
  dlg.addEventListener("click", (event) => {
    if (event.target.closest("[data-dialog-close]") || event.target === dlg) dlg.close();
  });
  dlg.addEventListener("cancel", (event) => {
    event.preventDefault();
    dlg.close();
  });
  return dlg;
}

export function closeDialog(host) {
  const dlg = host && qs("dialog", host);
  if (dlg && dlg.open) dlg.close();
}
