import { html, raw, qs, delegate } from "../core/dom.js";
import { get, post } from "../core/api.js";
import { SITE_LABEL, fmtSize, relTime } from "../core/format.js";
import { getLibraryView, setLibraryView } from "../core/prefs.js";
import { Button } from "../ui/button.js";
import { ChipRow } from "../ui/chip.js";
import { Dropdown, bindDropdown } from "../ui/dropdown.js";
import { EmptyState } from "../ui/empty.js";
import { Skeleton } from "../ui/skeleton.js";
import { Dialog, openDialog } from "../ui/dialog.js";
import { toast } from "../ui/toast.js";
import { icon } from "../ui/icons.js";

const PAGE = 60;
let ctx = null;
let root = null;
let off = null;
let dropOff = null;
let timer = 0;
let dialogHost = null;

const state = {
  site: "",
  q: "",
  sort: "mtime",
  order: "desc",
  view: "grid",
  items: [],
  total: 0,
  offset: 0,
  loading: false,
  path: "",
};

function queryFromRoute(route) {
  return {
    site: route.query.site || "",
    q: route.query.q || "",
    sort: route.query.sort || "mtime",
  };
}

function fileUrl(rel) {
  return "/api/library/file?rel=" + encodeURIComponent(rel);
}

function coverOf(item) {
  if (item.cover) return fileUrl(item.cover);
  return "";
}

function normalizeItems(data, siteFilter) {
  if (Array.isArray(data.items)) return { items: data.items, total: data.total || data.items.length, path: data.path || "" };
  const rows = [];
  (data.sites || []).forEach((s) => {
    if (siteFilter && s.site !== siteFilter) return;
    (s.recent || []).forEach((f) => rows.push({ ...f, site: s.site, cover: f.cover || "", ext: (f.name || "").split(".").pop() }));
  });
  rows.sort((a, b) => {
    if (state.sort === "name") return String(a.name).localeCompare(String(b.name), "zh");
    if (state.sort === "size") return (b.size || 0) - (a.size || 0);
    return (b.mtime || 0) - (a.mtime || 0);
  });
  return { items: rows, total: rows.length, path: data.path || "" };
}

async function fetchPage(reset) {
  if (reset) {
    state.offset = 0;
    state.items = [];
  }
  state.loading = true;
  paint();
  try {
    const params = new URLSearchParams({
      site: state.site,
      q: state.q,
      sort: state.sort,
      order: state.order,
      offset: String(state.offset),
      limit: String(PAGE),
    });
    const data = await get("/api/library?" + params.toString());
    const norm = normalizeItems(data, state.site);
    state.path = norm.path;
    if (data.items) {
      state.total = norm.total;
      state.items = reset ? norm.items : state.items.concat(norm.items);
      state.offset = state.items.length;
    } else {
      const slice = norm.items.slice(state.offset, state.offset + PAGE);
      state.total = norm.total;
      state.items = reset ? slice : state.items.concat(slice);
      state.offset = state.items.length;
    }
  } catch (err) {
    toast(err.message || "无法读取馆藏", { type: "error" });
  } finally {
    state.loading = false;
    paint();
  }
}

function card(item) {
  const cover = coverOf(item);
  const ext = (item.ext || (item.name || "").split(".").pop() || "").toUpperCase();
  const ph = html`<span class="lib-ph is-${item.site || ""}">${ext}</span>`;
  const thumb = cover ? html`<img alt="" src="${cover}" loading="lazy" decoding="async">` : ph;
  const meta = [fmtSize(item.size), relTime(item.mtime)].filter(Boolean).join(" · ");
  if (state.view === "list") {
    return html`<button type="button" class="lib-row" data-rel="${item.rel || ""}" data-name="${item.name || ""}">
      ${thumb}
      <div><h3>${item.name || "未命名"}</h3><p class="lib-meta">${SITE_LABEL[item.site] || item.site || ""} · ${meta}</p></div>
    </button>`;
  }
  return html`<button type="button" class="media-card" data-rel="${item.rel || ""}" data-name="${item.name || ""}">
    <div class="media-card-cover">${cover ? html`<img alt="" src="${cover}" loading="lazy" decoding="async">` : ph}</div>
    <h3 class="media-card-title">${item.name || "未命名"}</h3>
    <p class="media-card-meta">${meta}</p>
  </button>`;
}

function paint() {
  if (!root) return;
  const more = state.items.length < state.total;
  root.innerHTML = html`<section class="view view-library is-wide">
    <h1>馆藏</h1>
    <div class="lib-toolbar">
      ${ChipRow([{ id: "", name: "全部" }, { id: "jable", name: "Jable" }, { id: "youtube", name: "YouTube" }, { id: "douyin", name: "抖音" }], state.site)}
      <input type="search" id="lib-q" placeholder="搜索文件名" value="${state.q}">
      ${Dropdown({
        id: "lib-sort",
        label: state.sort === "name" ? "名称" : state.sort === "size" ? "大小" : "最近",
        value: state.sort,
        items: [
          { value: "mtime", label: "最近" },
          { value: "name", label: "名称" },
          { value: "size", label: "大小" },
        ],
      })}
      <div class="seg-tabs" role="group" aria-label="视图">
        <button type="button" class="seg-tab" data-lib-view="grid" aria-pressed="${state.view === "grid" ? "true" : "false"}" aria-label="网格">${raw(icon("grid"))}</button>
        <button type="button" class="seg-tab" data-lib-view="list" aria-pressed="${state.view === "list" ? "true" : "false"}" aria-label="列表">${raw(icon("list"))}</button>
      </div>
      ${Button({ variant: "secondary", label: "打开目录", attrs: "data-open-lib" })}
    </div>
    ${state.loading && !state.items.length
      ? Skeleton({ kind: state.view === "list" ? "row" : "card", count: 8 })
      : state.items.length
        ? html`<div class="${state.view === "list" ? "lib-list" : "media-grid"}">${state.items.map(card)}</div>`
        : EmptyState({ title: "还没有收入任何成品", text: "解析并确认保存后，文件会按来源放进这个目录。", action: { label: "去首页解析", id: "home" } })}
    ${more ? html`<div class="lib-more">${Button({ variant: "secondary", label: "加载更多", loading: state.loading, attrs: "data-lib-more" })}</div>` : ""}
    <div id="lib-dialog-host"></div>
  </section>`;
  dialogHost = qs("#lib-dialog-host", root);
  if (dropOff) dropOff();
  dropOff = bindDropdown(root, {
    onChange(value) {
      state.sort = value;
      ctx.navigate(`#/library?site=${encodeURIComponent(state.site)}&q=${encodeURIComponent(state.q)}&sort=${state.sort}`);
    },
  });
}

async function reveal(rel) {
  try {
    await post("/api/library/reveal", { rel });
  } catch (err) {
    if (err.status === 404) {
      await post("/api/open-library");
      return;
    }
    toast(err.message || "无法定位文件", { type: "error" });
  }
}

function openFile(rel, name) {
  if (!rel || !dialogHost) return;
  const src = fileUrl(rel);
  openDialog(
    dialogHost,
    Dialog({
      title: name || "播放",
      body: html`<video class="lib-player" controls src="${src}"></video>`,
      foot: html`${Button({ variant: "secondary", label: "在资源管理器中显示", attrs: `data-reveal="${rel}"` })}
        ${Button({ variant: "ghost", label: "复制路径", attrs: `data-copy="${rel}"` })}`,
    })
  );
}

export default {
  mount(el, next) {
    root = el;
    ctx = next;
    const q = queryFromRoute(ctx.route);
    state.site = q.site;
    state.q = q.q;
    state.sort = q.sort;
    state.view = getLibraryView();
    fetchPage(true);
    off = delegate(root, "click", ".chip, [data-lib-view], [data-open-lib], [data-lib-more], [data-rel], [data-reveal], [data-copy], [data-empty-action]", (event, node) => {
      if (node.classList.contains("chip")) {
        state.site = node.dataset.value || "";
        ctx.navigate(`#/library?site=${encodeURIComponent(state.site)}&q=${encodeURIComponent(state.q)}&sort=${state.sort}`);
        return;
      }
      if (node.dataset.libView) {
        state.view = node.dataset.libView;
        setLibraryView(state.view);
        paint();
        return;
      }
      if (node.matches("[data-open-lib]")) post("/api/open-library").catch((err) => toast(err.message, { type: "error" }));
      if (node.matches("[data-lib-more]")) fetchPage(false);
      if (node.hasAttribute("data-rel")) openFile(node.dataset.rel, node.dataset.name);
      if (node.hasAttribute("data-reveal")) reveal(node.dataset.reveal);
      if (node.hasAttribute("data-copy")) {
        navigator.clipboard.writeText(node.dataset.copy || "").then(
          () => toast("已复制路径", { type: "ok" }),
          () => toast("无法复制", { type: "error" })
        );
      }
      if (node.dataset.emptyAction === "home") ctx.navigate("#/");
    });
    root.addEventListener("input", onSearch);
  },
  update(next) {
    ctx = next;
    const q = queryFromRoute(ctx.route);
    if (q.site !== state.site || q.q !== state.q || q.sort !== state.sort) {
      state.site = q.site;
      state.q = q.q;
      state.sort = q.sort;
      fetchPage(true);
    }
  },
  unmount() {
    if (off) off();
    if (dropOff) dropOff();
    if (root) root.removeEventListener("input", onSearch);
    off = dropOff = null;
    root = ctx = null;
    clearTimeout(timer);
  },
};

function onSearch(event) {
  if (event.target.id !== "lib-q") return;
  clearTimeout(timer);
  timer = setTimeout(() => {
    state.q = event.target.value.trim();
    ctx.navigate(`#/library?site=${encodeURIComponent(state.site)}&q=${encodeURIComponent(state.q)}&sort=${state.sort}`);
  }, 280);
}
