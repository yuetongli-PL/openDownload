import { html, raw, qs, delegate } from "../core/dom.js";
import { post } from "../core/api.js";
import { loadModels, playKey, setUI, state, wipeSideEffects } from "./state.js";
import { applyParsed, isListMode, latestHash, listHashBase, listKeyOf, parseJable, routeKeyOf, tabOf, watchHash } from "./route.js";
import { bootWorksCache, readLocalHome } from "./data.js";
import { rememberWork } from "./cards.js";
import { cancelHoverWarm, openJableList, prefetchCatalogSnapshots, prefetchWorksOnce, scheduleHoverWarm, syncOrdersPoll } from "./fetch.js";
import { gotoListPage } from "./fetch.js";
import { homeSectionHtml, listSectionHtml, paintHome, paintJump, paintList, resetFilterPaint, setListStatus, syncNav, toggleBatch, toggleSelect } from "./list.js";
import { closeFilterMenus, fillCascadeLevel2, loadCatalog, toggleFilterMenu } from "./filters.js";
import { bindInspectLayout, closeJableInspect, inspectPanelHtml, inspectSourceFromCard, openJableInspect, playInspectFull } from "./inspect.js";
import { closeJableWatch, openJableWatch, watchSectionHtml } from "./watch.js";
import { destroyAllPlayers, handoverInspectToWatch } from "./player.js";

let layoutOff = null;
let hoverCard = null;

function shellHtml() {
  return html`<section id="view-jable" class="view view-jable is-wide">
    <header class="jable-heading">
      <div>
        <h1>Jable</h1>
        <p>浏览热门、最新与分类，预览确认后再收入馆藏。</p>
      </div>
      <form id="jb-search" class="jable-search" role="search">
        <label class="sr-only" for="jb-query">站内搜索</label>
        <input id="jb-query" type="search" name="q" spellcheck="false" placeholder="番号、标题或创作者" autocomplete="off">
        <button type="submit" class="btn btn-primary">解析</button>
      </form>
    </header>
    <nav id="jb-av-nav" class="jable-tabs" aria-label="Jable 分区">
      <a href="#/jable" data-jmode="home">精选</a>
      <a href="#/jable/hot" data-jmode="hot">热门</a>
      <a href="#/jable/latest" data-jmode="latest">最新</a>
      <a href="#/jable/type" data-jmode="type">分类浏览</a>
    </nav>
    <div id="jb-stage" class="jb-stage">
      <div id="jb-stage-main">
        ${raw(homeSectionHtml())}
        ${raw(listSectionHtml())}
        ${raw(watchSectionHtml())}
      </div>
      ${raw(inspectPanelHtml())}
    </div>
    <div id="jb-batch-bar" class="jable-batch" hidden></div>
  </section>`;
}

async function saveCode(code, { quiet = false } = {}) {
  const rawCode = playKey(code);
  if (!rawCode || !state.ctx) return false;
  const saveBtn = qs("#jb-inspect-save");
  const watchBtn = qs("#jb-watch-dl");
  if (!quiet) {
    if (saveBtn) saveBtn.disabled = true;
    if (watchBtn) watchBtn.disabled = true;
  }
  try {
    const task = await post("/api/jable/save", { code: rawCode, subs: false });
    state.ctx.tasks.track(task);
    if (!quiet) state.ctx.toast("已加入任务 " + rawCode.toUpperCase(), { type: "ok" });
    return true;
  } catch (err) {
    if (!quiet) state.ctx.toast((err && err.message) || "保存失败", { type: "error" });
    return false;
  } finally {
    if (!quiet) {
      if (saveBtn) saveBtn.disabled = false;
      if (watchBtn) watchBtn.disabled = false;
    }
  }
}

async function saveSelected() {
  const codes = [...state.selected];
  if (!codes.length) return;
  let ok = 0;
  let fail = 0;
  for (const code of codes) {
    if (await saveCode(code, { quiet: true })) ok += 1;
    else fail += 1;
  }
  toggleBatch(false);
  if (!state.ctx) return;
  if (ok) state.ctx.toast(`已加入 ${ok} 个任务`, { type: "ok" });
  if (fail) state.ctx.toast(`${fail} 个失败`, { type: "error" });
}

function openSearch(query) {
  const text = String(query || "").trim();
  if (!text || !state.ctx) return;
  state.ctx.collect.open({ query: text, site: "jable" });
}

async function loadHome(force) {
  state.homeHotPage = 1;
  state.homeLatestPage = 1;
  const local = state.jableHome || readLocalHome();
  if (local) {
    state.jableHome = local;
    ["hot", "latest"].forEach((k) => (((local[k] || {}).items || []).forEach(rememberWork)));
    paintHome();
    prefetchCatalogSnapshots();
  }
  if (state.jableHomeLoading && !force) return;
  state.jableHomeLoading = true;
  state.homeError = "";
  if (!local) paintHome();
  try {
    const data = await state.ctx.api.get("/api/jable/home?pages=2");
    if (!state.alive || state.jmode !== "home") {
      state.jableHomeLoading = false;
      return;
    }
    state.jableHome = data;
    ["hot", "latest"].forEach((k) => (((data[k] || {}).items || []).forEach(rememberWork)));
    try {
      localStorage.setItem("od-jable-home-v1", JSON.stringify(data));
    } catch {
      /* ignore */
    }
    paintHome();
    prefetchCatalogSnapshots();
  } catch (err) {
    state.homeError = local ? "更新未完成，当前显示上次加载的内容。" : (err && err.message) || "加载未完成，请检查网络后重试。";
    paintHome();
  } finally {
    state.jableHomeLoading = false;
  }
}

function rememberWatchFrom() {
  if (state.jmode !== "watch") state.watchFrom = listHashBase() || "#/jable";
}

function applyRoute(ctx, fromUpdate) {
  const parsed = parseJable(ctx);
  const nextKey = routeKeyOf(parsed);
  if (fromUpdate && nextKey === state.lastRouteKey) return;
  const prevList = state.lastListKey;
  const nextList = listKeyOf(parsed);
  const sameList = prevList && prevList === nextList;
  applyParsed(parsed);
  state.ctx = ctx;
  state.lastRouteKey = nextKey;
  document.body.dataset.site = "jable";
  document.body.dataset.jmode = parsed.mode;
  syncNav();

  if (parsed.mode === "watch") {
    if (state.inspectCode) closeJableInspect({ skipHash: true, skipPaint: true });
    handoverInspectToWatch();
    openJableWatch(parsed.video);
    state.lastListKey = nextList;
    state.lastInspect = "";
    state.lastWatch = parsed.video;
    return;
  }

  if (state.jmode === "watch" || state.lastWatch) closeJableWatch();
  state.lastWatch = "";

  if (parsed.mode === "home") {
    if (!sameList) {
      state.lastListKey = nextList;
      loadHome(false);
    } else if (!fromUpdate) {
      paintHome();
    }
  } else if (isListMode(parsed.mode)) {
    if (!sameList) {
      state.lastListKey = nextList;
      state.listPage = 1;
      openJableList();
    } else if (!fromUpdate) {
      paintList();
    }
  }

  if (parsed.inspect) {
    if (playKey(state.inspectCode) !== playKey(parsed.inspect) || !document.body.classList.contains("jb-inspect-open")) {
      openJableInspect(parsed.inspect, { fromHash: true });
    }
  } else if (state.inspectCode || document.body.classList.contains("jb-inspect-open")) {
    closeJableInspect({ fromHash: true });
  }
  state.lastInspect = parsed.inspect || "";
  syncOrdersPoll();
}

function bindEvents(root) {
  const offs = [];
  offs.push(
    delegate(root, "click", ".av-card, [data-go], [data-batch-check], [data-batch-toggle], [data-batch-save], [data-batch-cancel], [data-filter-reset], [data-empty-action], #jb-inspect-close, #jb-inspect-full, #jb-inspect-save, #jb-watch-dl, .av-dd-btn, [data-sort], [data-year], [data-month], [data-cat], [data-group], [data-tag]", (event, node) => {
      if (node.matches(".av-card") && event.target.closest("a, [data-batch-check]")) return;
      if (node.matches("[data-batch-check]")) {
        event.stopPropagation();
        toggleSelect(node.closest(".av-card")?.dataset.code, node.checked);
        return;
      }
      if (node.matches(".av-card")) {
        if (node.closest("#jable-watch")) {
          const code = node.dataset.code;
          if (code && state.ctx) state.ctx.navigate(watchHash(code));
          return;
        }
        if (state.batch) {
          const box = node.querySelector("[data-batch-check]");
          if (box && event.target !== box) {
            box.checked = !box.checked;
            toggleSelect(node.dataset.code, box.checked);
          }
          return;
        }
        const code = node.dataset.code;
        if (!code) return;
        event.preventDefault();
        if (playKey(state.inspectCode) === playKey(code)) {
          closeJableInspect();
          return;
        }
        state.lastCardFocus = code;
        openJableInspect(code, { source: inspectSourceFromCard(node) });
        return;
      }
      if (node.matches("[data-go]")) {
        if (node.disabled) return;
        const go = Number(node.getAttribute("data-go"));
        const host = node.closest("[data-pager]");
        const kind = host && host.getAttribute("data-pager");
        if (kind === "list") gotoListPage(go);
        else if (kind === "hot") {
          state.homeHotPage = go;
          paintHome();
        } else if (kind === "latest") {
          state.homeLatestPage = go;
          paintHome();
        }
        return;
      }
      if (node.matches("[data-batch-toggle]")) toggleBatch();
      if (node.matches("[data-batch-save]")) saveSelected();
      if (node.matches("[data-batch-cancel]")) toggleBatch(false);
      if (node.matches("[data-filter-reset]")) {
        const tab = tabOf(state.jmode);
        if (state.ctx) state.ctx.navigate(tab === "home" ? "#/jable" : `#/jable/${tab}`);
      }
      if (node.dataset.emptyAction === "retry") openJableList();
      if (node.dataset.emptyAction === "retry-home") loadHome(true);
      if (node.id === "jb-inspect-close") closeJableInspect();
      if (node.id === "jb-inspect-full") playInspectFull();
      if (node.id === "jb-inspect-save") saveCode(state.inspectCode);
      if (node.id === "jb-watch-dl") saveCode(state.watchCode || state.inspectCode);
      if (node.matches(".av-dd-btn")) {
        event.stopPropagation();
        toggleFilterMenu(node.closest(".av-dd"));
        return;
      }
      if (node.matches("[data-sort]")) {
        if (state.jmode === "model") {
          const sort = node.dataset.sort || "post_date";
          const base = `#/jable/model/${encodeURIComponent(state.listSlug)}`;
          if (state.ctx) state.ctx.navigate(sort === "video_viewed" ? `${base}/viewed` : base);
          return;
        }
        if (state.ctx) state.ctx.navigate(`#/jable/${node.dataset.sort || "hot"}`);
        return;
      }
      if (node.matches("[data-year]")) {
        if (state.ctx) state.ctx.navigate(latestHash(node.dataset.year || "", state.listMonth));
        return;
      }
      if (node.matches("[data-month]")) {
        if (state.ctx) state.ctx.navigate(latestHash(state.listYear, node.dataset.month || ""));
        return;
      }
      if (node.matches("[data-cat]")) {
        const slug = node.dataset.cat || "";
        state.listGroup = "";
        if (state.ctx) state.ctx.navigate(slug ? `#/jable/cat/${encodeURIComponent(slug)}` : "#/jable/type");
        return;
      }
      if (node.matches("[data-group]")) {
        state.listGroup = node.dataset.group || "";
        event.stopPropagation();
        if (!state.listGroup) {
          if (state.ctx) state.ctx.navigate("#/jable/type");
          return;
        }
        fillCascadeLevel2();
        return;
      }
      if (node.matches("[data-tag]")) {
        const slug = node.dataset.tag || "";
        if (state.ctx) {
          state.ctx.navigate(slug ? `#/jable/tag/${encodeURIComponent(slug)}` : state.listGroup ? `#/jable/type/${encodeURIComponent(state.listGroup)}` : "#/jable/type");
        }
      }
    })
  );

  const onKey = (event) => {
    if (event.key === "Enter" && event.target && event.target.matches("[data-pager-jump]")) {
      const host = event.target.closest("[data-pager]");
      const go = Number(event.target.value);
      const kind = host && host.getAttribute("data-pager");
      if (kind === "list") gotoListPage(go);
      else if (kind === "hot") {
        state.homeHotPage = go;
        paintHome();
      } else if (kind === "latest") {
        state.homeLatestPage = go;
        paintHome();
      }
    }
    if ((event.key === "Enter" || event.key === " ") && event.target && event.target.classList.contains("av-card")) {
      event.preventDefault();
      event.target.click();
    }
  };
  root.addEventListener("keydown", onKey);
  offs.push(() => root.removeEventListener("keydown", onKey));

  const onSearch = (event) => {
    event.preventDefault();
    openSearch(qs("#jb-query", root)?.value);
  };
  const form = qs("#jb-search", root);
  if (form) {
    form.addEventListener("submit", onSearch);
    offs.push(() => form.removeEventListener("submit", onSearch));
  }

  const onOver = (event) => {
    const card = event.target.closest && event.target.closest(".av-card");
    if (!card || !root.contains(card) || card === hoverCard) return;
    hoverCard = card;
    scheduleHoverWarm(card.dataset.code);
  };
  const onOut = (event) => {
    const card = event.target.closest && event.target.closest(".av-card");
    if (!card || (event.relatedTarget && card.contains(event.relatedTarget))) return;
    if (hoverCard === card) hoverCard = null;
    cancelHoverWarm();
  };
  root.addEventListener("pointerover", onOver);
  root.addEventListener("pointerout", onOut);
  offs.push(() => root.removeEventListener("pointerover", onOver));
  offs.push(() => root.removeEventListener("pointerout", onOut));

  const onDocClick = (event) => {
    if (!event.target.closest("#jb-filters .av-dd")) closeFilterMenus();
  };
  document.addEventListener("click", onDocClick);
  offs.push(() => document.removeEventListener("click", onDocClick));

  const onEsc = (event) => {
    if (event.key !== "Escape") return;
    if (qs("#jb-filters .av-dd.open")) {
      closeFilterMenus();
      return;
    }
    if (state.ctx && state.ctx.collect && state.ctx.collect.isOpen()) return;
    if (state.inspectCode || document.body.classList.contains("jb-inspect-open")) {
      event.preventDefault();
      closeJableInspect();
    }
  };
  document.addEventListener("keydown", onEsc);
  offs.push(() => document.removeEventListener("keydown", onEsc));

  state.unbind.push(...offs);
}

function boot() {
  setUI({
    paintList,
    paintJump,
    paintHome,
    setListStatus,
    toast: (...args) => state.ctx && state.ctx.toast(...args),
    live: (...args) => state.ctx && state.ctx.live && state.ctx.live(...args),
  });
  loadModels();
  bootWorksCache();
  prefetchWorksOnce();
}

const view = {
  mount(root, ctx) {
    state.alive = true;
    state.root = root;
    state.ctx = ctx;
    boot();
    // innerHTML: shell is built with html``
    root.innerHTML = shellHtml();
    bindEvents(root);
    layoutOff = bindInspectLayout(qs("#view-jable", root) || root);
    loadCatalog();
    rememberWatchFrom();
    applyRoute(ctx, false);
  },
  update(ctx) {
    if (!state.alive) return;
    state.ctx = ctx;
    const parsed = parseJable(ctx);
    if (routeKeyOf(parsed) === state.lastRouteKey) return;
    rememberWatchFrom();
    applyRoute(ctx, true);
  },
  unmount() {
    state.alive = false;
    if (layoutOff) layoutOff();
    layoutOff = null;
    hoverCard = null;
    destroyAllPlayers();
    document.body.classList.remove("jb-inspect-open", "jb-inspect-from-hot", "jb-inspect-from-latest", "inspect-resizing");
    delete document.body.dataset.listSnap;
    wipeSideEffects();
    resetFilterPaint();
    state.root = null;
    state.ctx = null;
  },
};

export default view;
