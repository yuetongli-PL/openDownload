import { html, raw, qs } from "../core/dom.js";
import { Button } from "../ui/button.js";
import { PAGE_SIZE, PAGER_WINDOW, playKey, state } from "./state.js";
import { itemsForListPage, listPageCount, pageCountOf, pagerRange } from "./data.js";
import { emptyHtml, errorHtml, fillGrid, inspectVisibleItems } from "./cards.js";
import { listKeyOf, listTitle } from "./route.js";
import { renderFilterBar } from "./filters.js";

let lastFilterKey = "";

export function pagerHtml(page, pageCount, { id, kind, disabled } = {}) {
  const total = Math.max(1, Number(pageCount) || 1);
  const cur = Math.min(Math.max(1, Number(page) || 1), total);
  const { start, end } = pagerRange(cur, total, PAGER_WINDOW);
  const atFirst = cur <= 1;
  const atLast = cur >= total;
  const off = disabled ? "disabled" : "";
  const pages = [];
  for (let i = start; i <= end; i += 1) {
    pages.push(
      html`<button type="button" data-go="${i}" class="${i === cur ? "on" : ""}" ${i === cur ? raw('aria-current="page"') : ""} ${off}>${i}</button>`
    );
  }
  return html`<nav id="${id || ""}" class="pager av-pager" data-pager="${kind || ""}" data-pages="${total}" aria-label="作品分页" aria-busy="${disabled ? "true" : "false"}">
    <button type="button" class="av-pager-first" data-edge data-go="1" ${atFirst ? "disabled" : ""} aria-label="第一页">首</button>
    <button type="button" class="av-pager-prev" data-go="${cur - 1}" ${atFirst ? "disabled" : ""} aria-label="上一页">上</button>
    <span class="av-pager-pages">${pages}</span>
    <button type="button" class="av-pager-next" data-go="${cur + 1}" ${atLast ? "disabled" : ""} aria-label="下一页">下</button>
    <button type="button" class="av-pager-last" data-edge data-go="${total}" ${atLast ? "disabled" : ""} aria-label="最后一页">末</button>
    <label class="sr-only" for="${id || "pager"}-jump">跳到页码</label>
    <input id="${id || "pager"}-jump" class="av-pager-input" type="number" min="1" max="${total}" value="${cur}" data-pager-jump ${disabled ? "disabled" : ""}>
  </nav>`;
}

function setText(id, text) {
  const el = qs("#" + id);
  if (el) el.textContent = text || "";
}

export function paintHome() {
  const feed = qs("#jable-feed");
  const list = qs("#jable-list");
  const watch = qs("#jable-watch");
  if (feed) feed.hidden = false;
  if (list) list.hidden = true;
  if (watch) watch.hidden = true;
  const data = state.jableHome;
  const latest = (data && data.latest && data.latest.items) || [];
  const hot = (data && data.hot && data.hot.items) || [];
  const hotPages = pageCountOf(hot.length, false, state.homeHotPage);
  const latestPages = pageCountOf(latest.length, false, state.homeLatestPage);
  state.homeHotPage = Math.min(Math.max(1, state.homeHotPage || 1), hotPages);
  state.homeLatestPage = Math.min(Math.max(1, state.homeLatestPage || 1), latestPages);
  const hs = (state.homeHotPage - 1) * PAGE_SIZE;
  const ls = (state.homeLatestPage - 1) * PAGE_SIZE;
  const loading = !data && state.jableHomeLoading;
  fillGrid(qs("#jb-hot-grid"), inspectVisibleItems(hot.slice(hs, hs + PAGE_SIZE), state.inspectCode), loading && !hot.length);
  fillGrid(qs("#jb-latest"), inspectVisibleItems(latest.slice(ls, ls + PAGE_SIZE), state.inspectCode), loading && !latest.length);
  const hotPager = qs("#jb-pager-hot");
  const latestPager = qs("#jb-pager-latest");
  if (hotPager) hotPager.outerHTML = pagerHtml(state.homeHotPage, hotPages, { id: "jb-pager-hot", kind: "hot" });
  if (latestPager) latestPager.outerHTML = pagerHtml(state.homeLatestPage, latestPages, { id: "jb-pager-latest", kind: "latest" });
  const status = qs("#jb-feed-status");
  const retry = qs("#jb-retry");
  if (status) {
    if (state.homeError && !hot.length && !latest.length) {
      status.hidden = false;
      status.textContent = state.homeError;
    } else {
      status.hidden = true;
      status.textContent = "";
    }
  }
  if (retry) retry.hidden = !state.homeError;
  syncShell("home");
}

export function paintList(title) {
  const feed = qs("#jable-feed");
  const list = qs("#jable-list");
  const watch = qs("#jable-watch");
  if (feed) feed.hidden = true;
  if (list) list.hidden = false;
  if (watch) watch.hidden = true;
  const page = Math.max(1, state.listPage || 1);
  const shown = inspectVisibleItems(itemsForListPage(page), state.inspectCode);
  const grid = qs("#jb-list-grid");
  if (state.listError && !shown.length) {
    if (grid) grid.innerHTML = errorHtml(state.listError);
  } else if (!shown.length && (state.listPageCount > 1 || state.listHasMore || state.pending)) {
    fillGrid(grid, [], true);
  } else {
    fillGrid(grid, shown, false, { batch: state.batch });
  }
  document.body.dataset.listSnap = state.listCodes.length > PAGE_SIZE ? "1" : "0";
  setText("jb-list-title", title || listTitle());
  const total = state.listTotal || 0;
  setText("jb-list-count", total ? `${total.toLocaleString()} 部影片` : "");
  const host = qs("#jb-pager");
  if (host) host.outerHTML = pagerHtml(page, listPageCount(), { id: "jb-pager", kind: "list", disabled: state.pending });
  syncFilters();
  paintBatchBar();
  syncShell(state.jmode);
}

export function paintJump(page, opts) {
  state.listPage = Math.max(1, Number(page) || 1);
  const forceSkel = opts && opts.skeleton;
  const shown = inspectVisibleItems(itemsForListPage(state.listPage), state.inspectCode);
  const grid = qs("#jb-list-grid");
  if (state.listError && !shown.length && !forceSkel) {
    if (grid) grid.innerHTML = errorHtml(state.listError);
  } else if (forceSkel || !shown.length) {
    fillGrid(grid, [], true);
  } else {
    fillGrid(grid, shown, false, { batch: state.batch });
  }
  setText("jb-list-title", listTitle());
  if (state.listTotal) setText("jb-list-count", `${state.listTotal.toLocaleString()} 部影片`);
  const host = qs("#jb-pager");
  if (host) host.outerHTML = pagerHtml(state.listPage, listPageCount(), { id: "jb-pager", kind: "list", disabled: state.pending || (opts && opts.skeleton) });
  paintBatchBar();
}

function syncFilters() {
  const key = listKeyOf(state);
  if (key === lastFilterKey && qs("#jb-filter-left .av-dd")) return;
  lastFilterKey = key;
  renderFilterBar();
}

export function resetFilterPaint() {
  lastFilterKey = "";
}

export function setListStatus(text) {
  setText("jb-list-count", text || "");
}

export function paintBatchBar() {
  const bar = qs("#jb-batch-bar");
  if (!bar) return;
  const on = state.batch && state.jmode !== "home" && state.jmode !== "watch";
  bar.hidden = !on;
  if (!on) return;
  const n = state.selected.size;
  bar.innerHTML = html`<span>已选 ${n}</span>
    ${Button({ variant: "primary", label: "保存所选", attrs: "data-batch-save", disabled: n < 1 })}
    ${Button({ variant: "ghost", label: "取消", attrs: "data-batch-cancel" })}`;
}

export function syncNav() {
  const mode = state.jmode;
  document.querySelectorAll("#jb-av-nav [data-jmode]").forEach((btn) => {
    const tab = btn.dataset.jmode;
    let on = tab === mode;
    if (tab === "hot") on = ["hot", "week", "month", "all"].includes(mode);
    if (tab === "type") on = ["type", "cat", "tag"].includes(mode);
    if (tab === "home") on = mode === "home";
    btn.classList.toggle("is-on", on);
    btn.classList.toggle("active", on);
    if (on) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
}

function syncShell(mode) {
  state.jmode = mode === "home" ? "home" : state.jmode;
  document.body.dataset.jmode = state.jmode;
  document.body.dataset.site = "jable";
  syncNav();
}

export function homeSectionHtml() {
  return html`<div id="jable-feed">
    <p id="jb-feed-status" class="jable-status" hidden></p>
    <button type="button" id="jb-retry" class="btn btn-secondary" data-empty-action="retry-home" hidden>重试</button>
    <section id="jb-sec-hot" class="jable-sec">
      <div class="jable-sec-head av-sec-head">
        <h2>热门精选</h2>
        <a href="#/jable/hot">查看全部</a>
      </div>
      <div id="jb-hot-grid" class="media-grid av-grid"></div>
      <nav id="jb-pager-hot" class="pager av-pager" data-pager="hot"></nav>
    </section>
    <section id="jb-sec-latest" class="jable-sec">
      <div class="jable-sec-head av-sec-head">
        <h2>最新影片</h2>
        <a href="#/jable/latest">查看全部</a>
      </div>
      <div id="jb-latest" class="media-grid av-grid"></div>
      <nav id="jb-pager-latest" class="pager av-pager" data-pager="latest"></nav>
    </section>
  </div>`;
}

export function listSectionHtml() {
  return html`<div id="jable-list" hidden>
    <div class="jable-list-head">
      <div>
        <h2 id="jb-list-title">影片</h2>
        <p id="jb-list-count" class="jable-count"></p>
      </div>
      <div class="jable-list-tools">
        ${Button({ variant: "secondary", label: "批量选择", attrs: "data-batch-toggle id=\"jb-batch-toggle\"" })}
        ${Button({ variant: "ghost", label: "重置筛选", attrs: "data-filter-reset id=\"jb-filter-reset\"" })}
      </div>
    </div>
    <div id="jb-filters" class="jable-filters av-filter-bar">
      <div id="jb-filter-left" class="av-filter-left"></div>
      <div id="jb-filter-right" class="av-filter-right"></div>
    </div>
    <div id="jb-list-grid" class="media-grid av-grid"></div>
    <nav id="jb-pager" class="pager av-pager" data-pager="list" data-pages="1"></nav>
  </div>`;
}

export function toggleBatch(on) {
  state.batch = on !== undefined ? !!on : !state.batch;
  if (!state.batch) state.selected.clear();
  paintList();
}

export function toggleSelect(code, checked) {
  const key = playKey(code);
  if (!key) return;
  if (checked) state.selected.add(key);
  else state.selected.delete(key);
  paintBatchBar();
}

export { emptyHtml, raw };
