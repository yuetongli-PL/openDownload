import { html } from "../core/dom.js";

export function Chip({ label, value, pressed = false, attrs = "" } = {}) {
  return html`<button type="button" class="chip ${pressed ? "is-on" : ""}" data-value="${value ?? label}" aria-pressed="${pressed ? "true" : "false"}" ${attrs}>${label}</button>`;
}

export function ChipRow(items, current) {
  return html`<div class="chip-row" role="group">${items.map((it) => {
    const value = typeof it === "string" ? it : it.id ?? it.value;
    const label = typeof it === "string" ? it : it.name ?? it.label;
    return Chip({ label, value, pressed: String(value) === String(current) });
  })}</div>`;
}

export function SegmentedTabs({ items, value, name = "tabs" } = {}) {
  return html`<div class="seg-tabs" role="tablist" data-seg="${name}">${items.map((it) => {
    const id = it.id ?? it.value;
    const on = String(id) === String(value);
    return html`<button type="button" class="seg-tab" role="tab" id="tab-${name}-${id}" data-value="${id}" aria-selected="${on ? "true" : "false"}" tabindex="${on ? "0" : "-1"}">${it.name ?? it.label}</button>`;
  })}</div>`;
}

export function bindSegmented(root, onChange) {
  root.addEventListener("keydown", (event) => {
    const tab = event.target.closest('[role="tab"]');
    const list = event.target.closest('[role="tablist"]');
    if (!tab || !list) return;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    const i = tabs.indexOf(tab);
    const next = tabs[(i + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
    next.focus();
    next.click();
  });
  if (onChange) {
    root.addEventListener("click", (event) => {
      const tab = event.target.closest('[role="tab"]');
      if (tab) onChange(tab.dataset.value, tab);
    });
  }
}
