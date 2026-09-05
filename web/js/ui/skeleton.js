import { html } from "../core/dom.js";

export function Skeleton({ kind = "card", count = 6 } = {}) {
  const one =
    kind === "row"
      ? html`<div class="skeleton" style="height:56px"></div>`
      : html`<div class="skeleton" style="aspect-ratio:16/10;border-radius:10px"></div>`;
  return html`<div class="media-grid" aria-busy="true">${Array.from({ length: count }, () => one)}<span class="sr-only">加载中</span></div>`;
}
