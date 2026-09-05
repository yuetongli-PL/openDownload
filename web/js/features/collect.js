import { html, raw, qs, qsa, delegate, focusTrap } from "../core/dom.js";
import { get, post, sse } from "../core/api.js";
import { SITE_LABEL, kindLabel } from "../core/format.js";
import { DrawerChrome, openPanel, closePanel } from "../ui/drawer.js";
import { toast, live } from "../ui/toast.js";
import { bodyHtml, buildParseBody, footHtml, stepMarkup, visibleIds as idsOf } from "./collect-view.js";

export { buildParseBody };

const MAX_LOG = 400;

export function createCollect({ tasks, navigate, getLimit }) {
  const host = qs("#collect-root");
  const state = {
    phase: "idle",
    query: "",
    site: "auto",
    tab: "",
    jable: null,
    dmode: "",
    detect: null,
    parseId: "",
    downloadId: "",
    preview: null,
    selected: new Set(),
    filter: "",
    view: "grid",
    quality: "1080p",
    subs: false,
    logs: [],
    logOpen: false,
    progress: null,
    error: "",
    needSite: false,
    maximized: false,
    open: false,
  };
  let stopParse = null;
  let stopDown = null;
  let unbind = null;
  let trap = null;
  let session = null;
  let lastOpts = null;
  let triggerEl = null;
  let pendingChromeFocus = false;

  function limit() {
    return getLimit ? getLimit() : 40;
  }

  function setPhase(phase, extra = {}) {
    Object.assign(state, extra, { phase });
    render();
    live(phase === "error" ? state.error : phase === "preview" ? "预览已就绪" : phase === "done" ? "已收入馆藏" : "");
  }

  function appendLog(line) {
    state.logs.push(line);
    if (state.logs.length > MAX_LOG) state.logs.splice(0, state.logs.length - MAX_LOG);
    const pre = qs("#collect-log");
    if (pre) {
      pre.textContent = state.logs.join("\n");
      pre.scrollTop = pre.scrollHeight;
    }
  }

  function visibleIds() {
    return idsOf(state);
  }

  function previewMeta() {
    const items = (state.preview && state.preview.items) || [];
    const blocked = Boolean(state.preview && state.preview.downloadable === false);
    return { items, blocked };
  }

  function findItem(id) {
    return qsa(".collect-item", host).find((el) => el.dataset.id === id) || null;
  }

  function patchPreviewChrome() {
    const { items, blocked } = previewMeta();
    const vis = visibleIds();
    const count = qs("[data-sel-count]", host);
    if (count) count.textContent = `已选 ${state.selected.size} / ${items.length}`;
    const all = qs("[data-sel-all]", host);
    if (all) all.checked = vis.length > 0 && vis.every((id) => state.selected.has(id));
    const saveBtn = qs("[data-collect-save]", host);
    if (saveBtn) {
      saveBtn.textContent = `确认保存 (${state.selected.size})`;
      saveBtn.disabled = !state.selected.size || blocked;
    }
  }

  function patchItem(id) {
    const el = findItem(id);
    if (!el) return;
    const on = state.selected.has(id);
    el.classList.toggle("is-off", !on);
    const cb = qs("input[type=checkbox]", el);
    if (cb) cb.checked = on;
  }

  function patchAllItems() {
    qsa(".collect-item", host).forEach((el) => {
      const on = state.selected.has(el.dataset.id);
      el.classList.toggle("is-off", !on);
      const cb = qs("input[type=checkbox]", el);
      if (cb) cb.checked = on;
    });
    patchPreviewChrome();
  }

  function applyFilter() {
    const q = state.filter.trim().toLowerCase();
    qsa(".collect-item", host).forEach((el) => {
      const title = (el.dataset.title || "").toLowerCase();
      el.hidden = Boolean(q && !title.includes(q));
    });
    patchPreviewChrome();
  }

  function rebindTrap() {
    const drawer = qs("#collect-drawer", host);
    if (!drawer || !state.open) return;
    if (trap) trap();
    trap = focusTrap(drawer, { autoFocus: false });
    if (session) {
      session.release = () => {
        if (trap) trap();
        trap = null;
      };
    }
  }

  function focusDrawerChrome() {
    const closeBtn = qs("[data-drawer-close]", host);
    const heading = qs(".drawer-head h2", host);
    if (closeBtn) closeBtn.focus();
    else if (heading) {
      heading.setAttribute("tabindex", "-1");
      heading.focus();
    }
  }

  function render() {
    if (!host) return;
    const prevInside = host.contains(document.activeElement);
    const bodyEl = qs(".drawer-body", host);
    const scrollTop = bodyEl ? bodyEl.scrollTop : 0;
    const filterEl = qs("[data-card-filter]", host);
    const keepFilter = filterEl
      ? {
          start: filterEl.selectionStart,
          end: filterEl.selectionEnd,
          focused: document.activeElement === filterEl,
        }
      : null;
    const drawerWasOpen = Boolean(qs("#collect-drawer.is-open", host));
    const site = (state.detect && state.detect.site) || state.site || "auto";
    const title =
      state.phase === "preview" || state.phase === "downloading" || state.phase === "done"
        ? (state.preview && state.preview.title) || "收藏单"
        : kindLabel(state.detect) || "收藏单";
    const openCls = state.open && drawerWasOpen ? "is-open" : "";
    host.innerHTML = html`<div class="sheet-backdrop" data-collect-backdrop ${state.open ? "" : "hidden"}></div>
      <aside id="collect-drawer" class="drawer ${state.maximized ? "is-max" : ""} ${openCls}" role="dialog" aria-modal="false" aria-label="收藏单" ${state.open ? "" : "hidden"}>
        ${DrawerChrome({
          title,
          kicker: SITE_LABEL[site] || "来源",
          steps: stepMarkup(state.phase),
          maximized: state.maximized,
        })}
        <div class="drawer-body">${raw(bodyHtml(state))}</div>
        <footer class="drawer-foot">${raw(footHtml(state))}</footer>
      </aside>`;
    const pre = qs("#collect-log", host);
    if (pre) pre.scrollTop = pre.scrollHeight;
    const body2 = qs(".drawer-body", host);
    if (body2) body2.scrollTop = scrollTop;
    if (keepFilter) {
      const input = qs("[data-card-filter]", host);
      if (input && keepFilter.focused) {
        input.focus();
        try {
          input.setSelectionRange(keepFilter.start, keepFilter.end);
        } catch {
          /* ignore */
        }
      }
    }
    bind();
    if (keepFilter && keepFilter.focused) pendingChromeFocus = false;
    else if (state.open && (pendingChromeFocus || prevInside) && !host.contains(document.activeElement)) {
      focusDrawerChrome();
    }
    if (pendingChromeFocus && qs("#collect-drawer.is-open", host)) pendingChromeFocus = false;
  }

  function bind() {
    if (unbind) unbind();
    const drawer = qs("#collect-drawer", host);
    const offs = [];
    if (!drawer) return;
    offs.push(
      delegate(host, "click", "[data-drawer-close], [data-collect-backdrop]", () => close())
    );
    offs.push(
      delegate(host, "click", "[data-drawer-max]", () => {
        state.maximized = !state.maximized;
        const drawer = qs("#collect-drawer", host);
        if (drawer) drawer.classList.toggle("is-max", state.maximized);
        const btn = qs("[data-drawer-max]", host);
        if (btn) btn.setAttribute("aria-label", state.maximized ? "还原宽度" : "最大化");
      })
    );
    offs.push(delegate(host, "click", "[data-toggle-log]", () => {
      state.logOpen = !state.logOpen;
      const pre = qs("#collect-log", host);
      const btn = qs("[data-toggle-log]", host);
      if (pre) pre.hidden = !state.logOpen;
      if (btn) btn.setAttribute("aria-expanded", state.logOpen ? "true" : "false");
    }));
    offs.push(delegate(host, "click", "[data-collect-retry]", () => retry()));
    offs.push(delegate(host, "click", "[data-pick-site]", (e, node) => {
      state.site = node.dataset.pickSite;
      state.needSite = false;
      startParse();
    }));
    offs.push(delegate(host, "click", "[data-collect-save]", () => confirmSave()));
    offs.push(delegate(host, "click", "[data-collect-cancel]", () => cancelDownload()));
    offs.push(delegate(host, "click", "[data-collect-folder]", () => post("/api/open-library").catch(() => {})));
    offs.push(delegate(host, "click", "[data-collect-library]", () => {
      close();
      navigate("#/library");
    }));
    offs.push(delegate(host, "click", "[data-collect-new]", () => {
      reset();
      close();
    }));
    offs.push(delegate(host, "change", "[data-sel-all]", (e, node) => {
      const on = node.checked;
      visibleIds().forEach((id) => (on ? state.selected.add(id) : state.selected.delete(id)));
      patchAllItems();
    }));
    offs.push(delegate(host, "change", "[data-subs]", (e, node) => {
      state.subs = node.checked;
    }));
    offs.push(delegate(host, "change", 'input[name="quality"]', (e, node) => {
      state.quality = node.value;
    }));
    offs.push(delegate(host, "click", "[data-view]", (e, node) => {
      state.view = node.dataset.view;
      const cards = qs(".collect-cards", host);
      if (cards) cards.classList.toggle("is-list", state.view === "list");
      qsa("[data-view]", host).forEach((btn) => {
        btn.setAttribute("aria-pressed", btn.dataset.view === state.view ? "true" : "false");
      });
    }));
    offs.push(delegate(host, "input", "[data-card-filter]", (e, node) => {
      const start = node.selectionStart;
      const end = node.selectionEnd;
      state.filter = node.value || "";
      applyFilter();
      node.focus();
      try {
        node.setSelectionRange(start, end);
      } catch {
        /* ignore */
      }
    }));
    offs.push(delegate(host, "change", ".collect-item input[type=checkbox]", (e, node) => {
      const id = node.closest("[data-id]")?.dataset.id;
      if (!id) return;
      if (node.checked) state.selected.add(id);
      else state.selected.delete(id);
      patchItem(id);
      patchPreviewChrome();
    }));
    if (state.open) rebindTrap();
    unbind = () => offs.forEach((fn) => fn());
  }

  function reset() {
    if (stopParse) stopParse();
    if (stopDown) stopDown();
    stopParse = stopDown = null;
    state.phase = "idle";
    state.detect = null;
    state.parseId = "";
    state.downloadId = "";
    state.preview = null;
    state.selected = new Set();
    state.filter = "";
    state.logs = [];
    state.logOpen = false;
    state.progress = null;
    state.error = "";
    state.needSite = false;
  }

  function show() {
    if (!host) return;
    const first = !state.open;
    if (first) {
      triggerEl = document.activeElement;
      pendingChromeFocus = true;
    }
    state.open = true;
    render();
    const drawer = qs("#collect-drawer", host);
    if (!drawer) return;
    if (first) {
      session = openPanel(drawer, { returnFocus: triggerEl, autoFocus: false, installTrap: false });
      rebindTrap();
      focusDrawerChrome();
      pendingChromeFocus = false;
    }
  }

  function close() {
    state.open = false;
    const drawer = qs("#collect-drawer", host);
    const back = qs("[data-collect-backdrop]", host);
    if (back) back.hidden = true;
    const pack = session || {
      trigger: triggerEl,
      release() {
        if (trap) trap();
        trap = null;
      },
    };
    session = null;
    if (drawer) closePanel(drawer, pack);
    triggerEl = null;
  }

  async function startDetect(opts) {
    lastOpts = opts;
    reset();
    state.query = opts.query || "";
    state.site = opts.site || "auto";
    state.tab = opts.tab || "";
    state.jable = opts.jable || null;
    state.dmode = opts.dmode || opts.tab || "";
    show();
    setPhase("detecting");
    try {
      const body = buildParseBody({ ...state, limit: limit() });
      const det = await post("/api/detect", body);
      state.detect = det;
      if (det.kind === "need-site" || det.site === "unknown") {
        setPhase("error", {
          error: det.message || "无法判断来源。请选择 Jable、YouTube 或抖音后再解析。",
          needSite: true,
        });
        return;
      }
      await startParse();
    } catch (err) {
      setPhase("error", { error: (err && err.message) || "识别失败。检查网络后重试。" });
    }
  }

  async function startParse() {
    setPhase("parsing", { logs: [], error: "", needSite: false });
    try {
      const body = buildParseBody({ ...state, limit: limit() });
      if (!body.query && !body.jable) throw { message: "请输入链接或选择来源" };
      const task = await post("/api/parse", body);
      state.parseId = task.id;
      tasks.track({ ...task, title: state.query || kindLabel(state.detect), site: (state.detect && state.detect.site) || state.site });
      if (stopParse) stopParse();
      stopParse = sse(`/api/tasks/${task.id}/stream`, {
        log(line) {
          appendLog(line);
        },
        preview(preview) {
          applyPreview(preview);
        },
        error(message) {
          setPhase("error", { error: `解析失败：${message}。检查网络或 Cookie 后重试。` });
        },
        done(rec) {
          if (rec && rec.status === "error") return;
          if (state.phase === "parsing") live("预览已就绪");
        },
      });
    } catch (err) {
      setPhase("error", { error: (err && err.message) || "解析失败。检查网络后重试。" });
    }
  }

  function applyPreview(preview) {
    state.preview = preview;
    state.selected = new Set((preview.items || []).map((it) => it.id));
    state.filter = "";
    setPhase("preview");
  }

  async function confirmSave() {
    if (!state.parseId || !state.selected.size) return;
    setPhase("downloading", { logs: [], progress: { percent: 1, label: "排队保存", phase: "queued" } });
    try {
      const task = await post("/api/download", {
        parse_id: state.parseId,
        ids: [...state.selected],
        quality: state.quality,
        subs: state.subs,
      });
      state.downloadId = task.id;
      tasks.track({
        ...task,
        kind: "download",
        title: (state.preview && state.preview.title) || state.query,
        site: (state.preview && state.preview.site) || state.site,
        parseId: state.parseId,
        preview: state.preview,
      });
      if (stopDown) stopDown();
      stopDown = sse(`/api/tasks/${task.id}/stream`, {
        log(line) {
          appendLog(line);
        },
        progress(rec) {
          state.progress = rec;
          const box = qs(".drawer-body", host);
          if (box) box.innerHTML = bodyHtml(state);
        },
        error(message) {
          setPhase("error", { error: `保存失败：${message}。可重试或修改选项。` });
        },
        done(rec) {
          if (rec.status === "cancelled") {
            setPhase("error", { error: "已取消。可重新确认保存。" });
            return;
          }
          if (rec.status === "error") return;
          setPhase("done", { progress: { percent: 100, label: "完成", phase: "done" } });
        },
      });
    } catch (err) {
      setPhase("error", { error: (err && err.message) || "无法开始保存。" });
    }
  }

  async function cancelDownload() {
    if (!state.downloadId) return;
    try {
      await post(`/api/tasks/${state.downloadId}/cancel`);
    } catch (err) {
      toast(err.message || "无法取消", { type: "error" });
    }
  }

  function retry() {
    if (lastOpts) startDetect(lastOpts);
    else startParse();
  }

  async function reopen(taskId) {
    let snap = tasks.get(taskId);
    try {
      snap = await get(`/api/tasks/${taskId}`);
      tasks.track(snap);
    } catch {
      /* use local */
    }
    if (!snap) {
      toast("找不到该任务", { type: "error" });
      return;
    }
    reset();
    state.parseId = snap.kind === "parse" ? snap.id : snap.parse_id || snap.parseId || "";
    state.downloadId = snap.kind === "download" ? snap.id : "";
    if (snap.preview) {
      state.preview = snap.preview;
      state.selected = new Set((snap.preview.items || []).map((it) => it.id));
      state.site = snap.preview.site || snap.site || "auto";
    }
    show();
    if (snap.kind === "download" && (snap.status === "queued" || snap.status === "running")) {
      setPhase("downloading", { progress: snap });
      if (stopDown) stopDown();
      stopDown = sse(`/api/tasks/${snap.id}/stream`, {
        progress(rec) {
          state.progress = rec;
          render();
        },
        done(rec) {
          if (rec.status === "done") setPhase("done", { progress: { percent: 100, phase: "done", label: "完成" } });
        },
      });
    } else if (snap.preview) setPhase("preview");
    else if (snap.status === "done") setPhase("done");
    else setPhase("error", { error: snap.error || "无法恢复收藏单。可重新解析。" });
  }

  function isOpen() {
    return state.open;
  }

  return {
    open(opts) {
      return startDetect(opts || {});
    },
    reopen,
    close,
    isOpen,
    buildParseBody,
  };
}
