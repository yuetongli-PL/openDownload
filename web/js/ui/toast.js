import { html, qs } from "../core/dom.js";

const MAX = 3;
let host = null;
const items = [];

export function initToast(el) {
  host = el;
}

export function toast(message, { type = "info", action = null, ms = 3200 } = {}) {
  if (!host) return;
  const id = "t" + Date.now() + Math.random().toString(16).slice(2, 6);
  items.push({ id, message, type, action });
  while (items.length > MAX) items.shift();
  render();
  setTimeout(() => dismiss(id), ms);
}

function dismiss(id) {
  const i = items.findIndex((it) => it.id === id);
  if (i >= 0) items.splice(i, 1);
  render();
}

function render() {
  if (!host) return;
  host.innerHTML = items
    .map(
      (it) =>
        html`<div class="toast is-${it.type === "error" ? "err" : it.type === "ok" ? "ok" : "info"}" role="status">
          <span>${it.message}</span>
          ${it.action ? html`<button type="button" data-toast="${it.id}">${it.action.label}</button>` : ""}
        </div>`
    )
    .join("");
  host.onclick = (event) => {
    const btn = event.target.closest("[data-toast]");
    if (!btn) return;
    const it = items.find((row) => row.id === btn.dataset.toast);
    if (it && it.action && it.action.onClick) it.action.onClick();
    dismiss(btn.dataset.toast);
  };
}

export function live(text) {
  const el = qs("#live");
  if (el) el.textContent = text || "";
}
