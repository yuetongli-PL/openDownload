import { qs, qsa, delegate } from "./core/dom.js";
import { api } from "./core/api.js";
import { createStore } from "./core/store.js";
import { createRouter, navigate, parseLocation } from "./core/router.js";
import { applyTheme, getThemePref, getSidebarCollapsed, setSidebarCollapsed, watchSystemTheme, resolveTheme } from "./core/prefs.js";
import { initToast, toast, live } from "./ui/toast.js";
import { icon } from "./ui/icons.js";
import { createTasks } from "./features/tasks.js";
function createCollectFacade() {
  let real = null;
  let loading = null;
  function load() {
    if (real) return Promise.resolve(real);
    if (!loading) {
      loading = import("./features/collect.js").then((mod) => {
        real = mod.createCollect({
          tasks,
          navigate,
          getLimit: () => Number(store.get("limit") || 40),
        });
        bag.collect = real;
        return real;
      });
    }
    return loading;
  }
  return {
    open(opts) {
      return load().then((c) => c.open(opts));
    },
    reopen(id) {
      return load().then((c) => c.reopen(id));
    },
    close() {
      if (real) real.close();
    },
    isOpen() {
      return real ? real.isOpen() : false;
    },
  };
}

applyTheme(getThemePref());
watchSystemTheme(() => syncThemeBtn());

const store = createStore({
  health: null,
  settings: { limit: 40, workers: 64, library: "" },
  limit: 40,
  theme: getThemePref(),
});

initToast(qs("#toast-root"));

const bag = { collect: null };
const tasks = createTasks({
  onBadge(n) {
    const badge = qs("#nav-task-badge");
    if (!badge) return;
    badge.hidden = n < 1;
    badge.textContent = String(n);
  },
  onReopen(id) {
    if (bag.collect) bag.collect.reopen(id);
  },
});

const collect = createCollectFacade();
bag.collect = collect;

const app = qs("#app");
const router = createRouter({
  root: app,
  getCtx() {
    return { store, api, tasks, collect, toast, live };
  },
});

function syncShell(route) {
  const head = route.segments[0] || "";
  const labels = {
    home: ["工作台", "首页"],
    jable: ["来源", "Jable"],
    youtube: ["来源", "YouTube"],
    douyin: ["来源", "抖音"],
    library: ["工作台", "馆藏"],
    tasks: ["工作台", "任务"],
    settings: ["工作台", "设置"],
  };
  const pair = labels[head] || labels[homeKey(head)];
  const crumb = pair || labels.home;
  const parent = qs("#crumb-parent");
  const current = qs("#crumb-current");
  if (parent) {
    parent.textContent = crumb[0];
    parent.href = crumb[0] === "来源" ? "#/" : "#/";
  }
  if (current) current.textContent = crumb[1];
  document.title = crumb[1] === "首页" ? "openDownload" : `${crumb[1]} · openDownload`;
  qsa("[data-nav]").forEach((a) => {
    const on = a.dataset.nav === (head || "home") || (a.dataset.nav === "home" && !head);
    a.classList.toggle("is-active", on);
    if (on) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  const global = qs("#global-query");
  if (global && (head === "youtube" || head === "douyin" || head === "jable")) {
    /* keep value */
  }
}

function homeKey(head) {
  return head || "home";
}

function applySidebar() {
  const collapsed = getSidebarCollapsed();
  qs(".app-shell")?.classList.toggle("is-collapsed", collapsed);
  const btn = qs("#btn-collapse");
  if (btn) {
    btn.setAttribute("aria-label", collapsed ? "展开侧栏" : "折叠侧栏");
    btn.innerHTML = icon(collapsed ? "expand" : "collapse") + "<span>折叠</span>";
  }
}

function closeMobileNav() {
  qs("#sidebar")?.classList.remove("is-open");
  const back = qs("#sidebar-backdrop");
  if (back) back.hidden = true;
  qs("#btn-menu")?.setAttribute("aria-expanded", "false");
}

function openMobileNav() {
  qs("#sidebar")?.classList.add("is-open");
  const back = qs("#sidebar-backdrop");
  if (back) back.hidden = false;
  qs("#btn-menu")?.setAttribute("aria-expanded", "true");
}

function focusQuery() {
  const route = parseLocation();
  const home = qs("#home-query");
  const source = qs("#source-query");
  const global = qs("#global-query");
  const el = route.name === "home" && home ? home : source || global;
  if (el) {
    el.focus();
    if (el.select) el.select();
  }
}

function isTyping(el) {
  if (!el) return false;
  const tag = (el.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
}

let gPending = false;
let gTimer = 0;

function onKeydown(event) {
  const meta = event.ctrlKey || event.metaKey;
  if (meta && event.key.toLowerCase() === "k") {
    event.preventDefault();
    focusQuery();
    return;
  }
  if (event.key === "/" && !isTyping(event.target) && !meta) {
    event.preventDefault();
    focusQuery();
    return;
  }
  if (event.key === "Escape") {
    const menu = qs(".dropdown-menu:not([hidden])");
    if (menu) {
      menu.hidden = true;
      return;
    }
    if (qs("#sidebar")?.classList.contains("is-open")) {
      closeMobileNav();
      qs("#btn-menu")?.focus();
      return;
    }
    const dlg = qs("dialog[open]");
    if (dlg) {
      dlg.close();
      return;
    }
    if (collect.isOpen()) {
      collect.close();
      return;
    }
    return;
  }
  if (isTyping(event.target) || meta) return;
  if (event.key === "g") {
    gPending = true;
    clearTimeout(gTimer);
    gTimer = setTimeout(() => {
      gPending = false;
    }, 800);
    return;
  }
  if (!gPending) return;
  const map = { h: "#/", j: "#/jable", y: "#/youtube", d: "#/douyin", l: "#/library", t: "#/tasks", s: "#/settings" };
  const dest = map[event.key.toLowerCase()];
  if (dest) {
    event.preventDefault();
    navigate(dest);
  }
  gPending = false;
}

function healthClass(h) {
  if (!h) return "";
  const ffmpeg = !!h.ffmpeg;
  const yt = !!h.yt_dlp;
  if (!ffmpeg || !yt) return "is-bad";
  if (!h.cookie || !h.playwright) return "is-warn";
  return "is-ok";
}

async function bootHealth() {
  try {
    const h = await api.get("/api/health");
    store.patch({ health: h, settings: h.settings || store.get("settings"), limit: (h.settings && h.settings.limit) || store.get("limit") });
    const dot = qs("#health-dot");
    if (dot) {
      dot.classList.remove("is-ok", "is-warn", "is-bad");
      const cls = healthClass(h);
      if (cls) dot.classList.add(cls);
      dot.title = cls === "is-ok" ? "环境就绪" : cls === "is-warn" ? "核心依赖就绪，抖音登录功能未齐" : "缺少 FFmpeg 或 yt-dlp，下载可能失败";
    }
    if (h.settings) store.patch({ settings: h.settings, limit: h.settings.limit || 40 });
  } catch {
    qs("#health-dot")?.classList.add("is-bad");
  }
  try {
    const s = await api.get("/api/settings");
    store.patch({ settings: s, limit: s.limit || 40 });
  } catch {
    /* keep defaults */
  }
}

function bindShell() {
  applySidebar();
  delegate(document, "click", "#btn-collapse", () => {
    setSidebarCollapsed(!getSidebarCollapsed());
    applySidebar();
  });
  delegate(document, "click", "#btn-menu", () => {
    if (qs("#sidebar")?.classList.contains("is-open")) closeMobileNav();
    else openMobileNav();
  });
  delegate(document, "click", "#sidebar-backdrop", closeMobileNav);
  delegate(document, "click", "#sidebar [data-nav]", closeMobileNav);
  delegate(document, "click", "#health-dot", () => navigate("#/settings"));
  delegate(document, "click", "#btn-theme", () => {
    const cur = resolveTheme(getThemePref());
    applyTheme(cur === "dark" ? "light" : "dark");
    store.patch({ theme: getThemePref() });
  });
  const global = qs("#global-query");
  if (global) {
    global.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        const query = global.value.trim();
        if (query) {
          collect.open({ query, site: "auto" });
          global.value = "";
        }
      }
    });
  }
  document.addEventListener("keydown", onKeydown);
}

function syncThemeBtn() {
  const btn = qs("#btn-theme");
  if (!btn) return;
  const dark = resolveTheme(getThemePref()) === "dark";
  btn.innerHTML = icon(dark ? "sun" : "moon") + "<span>主题</span>";
  btn.setAttribute("aria-label", dark ? "切换浅色" : "切换深色");
}

window.addEventListener("hashchange", () => syncShell(parseLocation()));

bindShell();
syncThemeBtn();
store.subscribe(() => syncThemeBtn());
tasks.mountTray(qs("#tray-root"));
router.start();
syncShell(parseLocation());
tasks.restore();
bootHealth();
