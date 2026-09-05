import { html, qs, qsa } from "../core/dom.js";

/**
 * Dropdown({ label, value, items, onChange })
 * Dropdown({ label, cascade: { left, right, leftValue, rightValue }, onLeft, onRight })
 * items: [{ value, label }]
 * cascade.left / cascade.right: [{ value, label }] — 两列级联，供 WP3 分类/标签复用
 */
export function Dropdown({
  label = "选择",
  value = "",
  items = [],
  cascade = null,
  id = "",
} = {}) {
  const current = items.find((it) => String(it.value) === String(value));
  const text = current ? current.label : label;
  if (cascade) {
    return html`<div class="dropdown" data-dropdown="${id}">
      <button type="button" class="dropdown-btn" aria-expanded="false" aria-haspopup="true">${label}</button>
      <div class="dropdown-menu is-cascade" hidden>
        <div data-col="left">${(cascade.left || []).map((it) => html`<button type="button" class="dropdown-item ${it.value === cascade.leftValue ? "is-on" : ""}" data-col="left" data-value="${it.value}">${it.label}</button>`)}</div>
        <div data-col="right">${(cascade.right || []).map((it) => html`<button type="button" class="dropdown-item ${it.value === cascade.rightValue ? "is-on" : ""}" data-col="right" data-value="${it.value}">${it.label}</button>`)}</div>
      </div>
    </div>`;
  }
  return html`<div class="dropdown" data-dropdown="${id}">
    <button type="button" class="dropdown-btn" aria-expanded="false" aria-haspopup="true">${text}</button>
    <div class="dropdown-menu" hidden>
      ${items.map((it) => html`<button type="button" class="dropdown-item ${String(it.value) === String(value) ? "is-on" : ""}" data-value="${it.value}">${it.label}</button>`)}
    </div>
  </div>`;
}

export function bindDropdown(root, { onChange, onLeft, onRight } = {}) {
  const open = (dd, on) => {
    const btn = qs(".dropdown-btn", dd);
    const menu = qs(".dropdown-menu", dd);
    if (!btn || !menu) return;
    menu.hidden = !on;
    btn.setAttribute("aria-expanded", on ? "true" : "false");
  };

  const closeAll = (except) => {
    qsa(".dropdown", root).forEach((dd) => {
      if (dd !== except) open(dd, false);
    });
  };

  root.addEventListener("click", (event) => {
    const btn = event.target.closest(".dropdown-btn");
    if (btn) {
      const dd = btn.closest(".dropdown");
      const willOpen = qs(".dropdown-menu", dd).hidden;
      closeAll(dd);
      open(dd, willOpen);
      return;
    }
    const item = event.target.closest(".dropdown-item");
    if (!item) return;
    const dd = item.closest(".dropdown");
    const col = item.dataset.col;
    if (col === "left" && onLeft) onLeft(item.dataset.value, dd);
    else if (col === "right" && onRight) onRight(item.dataset.value, dd);
    else if (onChange) onChange(item.dataset.value, dd);
    if (col !== "left") open(dd, false);
  });

  root.addEventListener("keydown", (event) => {
    const dd = event.target.closest(".dropdown");
    if (!dd) return;
    if (event.key === "ArrowDown" && event.target.classList.contains("dropdown-btn")) {
      event.preventDefault();
      open(dd, true);
      qs(".dropdown-item", dd)?.focus();
    }
    if (event.key === "Escape") {
      open(dd, false);
      qs(".dropdown-btn", dd)?.focus();
    }
  });

  const onDoc = (event) => {
    if (!root.contains(event.target)) closeAll();
  };
  document.addEventListener("click", onDoc);
  return () => document.removeEventListener("click", onDoc);
}
