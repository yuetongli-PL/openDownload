import { html, raw } from "../core/dom.js";

/**
 * Pager({ page, pageCount, onGo })
 * 首/上/页码窗口(5)/下/末 + 跳页输入 Enter
 */
export function Pager({ page = 1, pageCount = 1 } = {}) {
  const cur = Math.max(1, Number(page) || 1);
  const total = Math.max(1, Number(pageCount) || 1);
  const start = Math.max(1, Math.min(cur - 2, total - 4));
  const end = Math.min(total, start + 4);
  const pages = [];
  for (let i = start; i <= end; i += 1) pages.push(i);
  return html`<nav class="pager" aria-label="分页">
    <button type="button" data-edge data-go="1" ${cur <= 1 ? "disabled" : ""} aria-label="第一页">首</button>
    <button type="button" data-go="${cur - 1}" ${cur <= 1 ? "disabled" : ""} aria-label="上一页">上</button>
    ${pages.map((n) => html`<button type="button" data-go="${n}" ${n === cur ? raw('aria-current="page"') : ""}>${n}</button>`)}
    <button type="button" data-go="${cur + 1}" ${cur >= total ? "disabled" : ""} aria-label="下一页">下</button>
    <button type="button" data-edge data-go="${total}" ${cur >= total ? "disabled" : ""} aria-label="最后一页">末</button>
    <label class="sr-only" for="pager-jump">跳到页码</label>
    <input id="pager-jump" type="number" min="1" max="${total}" value="${cur}" data-pager-jump>
  </nav>`;
}

export function bindPager(root, onGo) {
  root.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-go]");
    if (!btn || btn.disabled) return;
    const page = Number(btn.dataset.go);
    if (page >= 1 && onGo) onGo(page);
  });
  root.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const input = event.target.closest("[data-pager-jump]");
    if (!input) return;
    const page = Number(input.value);
    if (page >= 1 && onGo) onGo(page);
  });
}
