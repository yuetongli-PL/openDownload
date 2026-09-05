import { html, delegate } from "../core/dom.js";
import { get, post, del, sse } from "../core/api.js";
import { createStore } from "../core/store.js";
import { isActiveStatus, taskTitle } from "../core/format.js";
import { TaskRow } from "../ui/task-row.js";
import { toast } from "../ui/toast.js";

function normalize(snap = {}) {
  const preview = snap.preview || null;
  return {
    id: snap.id,
    kind: snap.kind || "",
    status: snap.status || "",
    percent: Number(snap.percent) || 0,
    phase: snap.phase || "",
    label: snap.label || "",
    error: snap.error || "",
    created: snap.created || 0,
    updated: snap.updated || 0,
    finished: snap.finished || null,
    title: snap.title || (preview && preview.title) || snap.label || "",
    site: snap.site || (preview && preview.site) || "",
    count: snap.count || (preview && preview.items && preview.items.length) || 0,
    live: snap.live !== false,
    preview,
    result: snap.result || null,
    parseId: snap.parse_id || snap.parseId || "",
    downloadId: snap.download_id || snap.downloadId || "",
  };
}

export function createTasks({ onBadge, onReopen }) {
  const store = createStore({ items: [] });
  const streams = new Map();
  let trayEl = null;
  let expanded = false;
  let unbind = null;

  function items() {
    return store.get("items") || [];
  }

  function upsert(snap) {
    const next = normalize(snap);
    if (!next.id) return next;
    const list = items().filter((it) => it.id !== next.id);
    list.unshift(next);
    list.sort((a, b) => (b.updated || b.created || 0) - (a.updated || a.created || 0));
    store.patch({ items: list });
    syncStream(next);
    paint();
    if (onBadge) onBadge(active().length);
    return next;
  }

  function active() {
    return items().filter((it) => isActiveStatus(it.status));
  }

  function closeStream(id) {
    const stop = streams.get(id);
    if (stop) stop();
    streams.delete(id);
  }

  function syncStream(task) {
    if (!isActiveStatus(task.status)) {
      closeStream(task.id);
      return;
    }
    if (streams.has(task.id)) return;
    const stop = sse(`/api/tasks/${task.id}/stream`, {
      log() {},
      progress(rec) {
        const cur = items().find((it) => it.id === task.id) || task;
        upsert({
          ...cur,
          percent: rec.percent ?? cur.percent,
          phase: rec.phase || cur.phase,
          label: rec.label || cur.label,
          status: "running",
          speed: rec.speed,
          eta: rec.eta,
          item: rec.item,
          items: rec.items,
        });
      },
      preview(preview, rec) {
        const cur = items().find((it) => it.id === task.id) || task;
        upsert({
          ...cur,
          preview,
          title: (preview && preview.title) || cur.title,
          site: (preview && preview.site) || cur.site,
          status: (rec && rec.status) || cur.status,
        });
      },
      error(message) {
        const cur = items().find((it) => it.id === task.id) || task;
        upsert({ ...cur, error: message, status: cur.status === "cancelled" ? "cancelled" : "error" });
      },
      done(rec) {
        const cur = items().find((it) => it.id === task.id) || task;
        const status = rec.status || "done";
        upsert({
          ...cur,
          status,
          percent: status === "done" ? 100 : cur.percent,
          phase: status === "done" ? "done" : cur.phase,
          label: status === "done" ? "完成" : cur.label,
          finished: Date.now() / 1000,
        });
        closeStream(task.id);
        if (status === "done" && cur.kind === "download") {
          toast("已收入馆藏", {
            type: "ok",
            action: { label: "打开目录", onClick: () => post("/api/open-library").catch(() => {}) },
          });
        }
      },
    });
    streams.set(task.id, stop);
  }

  function paint() {
    if (!trayEl) return;
    const running = active();
    if (!running.length) {
      trayEl.hidden = true;
      trayEl.innerHTML = "";
      return;
    }
    trayEl.hidden = false;
    const avg = Math.round(running.reduce((s, it) => s + (Number(it.percent) || 0), 0) / running.length);
    const rows = running.slice(0, 5);
    trayEl.innerHTML = html`<div class="task-tray">
      ${expanded
        ? html`<div class="tray-panel">
            ${rows.map((it) => TaskRow(it, { compact: false }))}
            <button type="button" class="btn btn-ghost" data-tray-all>查看全部</button>
          </div>`
        : ""}
      <button type="button" class="tray-pill" data-tray-toggle aria-expanded="${expanded ? "true" : "false"}">
        ${running.length} 个任务进行中 · ${avg}%
      </button>
    </div>`;
  }

  function mountTray(el) {
    trayEl = el;
    if (unbind) unbind();
    unbind = delegate(el, "click", "[data-tray-toggle], [data-tray-all], [data-act]", (event, node) => {
      if (node.matches("[data-tray-toggle]")) {
        expanded = !expanded;
        paint();
        return;
      }
      if (node.matches("[data-tray-all]")) {
        location.hash = "#/tasks";
        return;
      }
      const row = node.closest("[data-task]");
      const id = row && row.dataset.task;
      const act = node.dataset.act;
      if (!id) return;
      if (act === "cancel") cancel(id);
      if (act === "open") post("/api/open-library").catch(() => {});
      if (act === "reopen" && onReopen) onReopen(id);
      if (act === "dismiss") dismiss(id);
    });
    paint();
  }

  async function cancel(id) {
    try {
      const snap = await post(`/api/tasks/${id}/cancel`);
      upsert(snap);
    } catch (err) {
      toast(err.message || "无法取消", { type: "error" });
    }
  }

  async function dismiss(id) {
    try {
      await del(`/api/tasks/${id}`);
    } catch (err) {
      if (err.status && err.status !== 404) {
        toast(err.message || "无法删除", { type: "error" });
        return;
      }
    }
    store.patch({ items: items().filter((it) => it.id !== id) });
    closeStream(id);
    paint();
    if (onBadge) onBadge(active().length);
  }

  function track(snapshot) {
    return upsert(snapshot);
  }

  async function restore() {
    try {
      const data = await get("/api/tasks?limit=50");
      const list = (data.items || []).map(normalize);
      store.patch({ items: list });
      list.filter((it) => isActiveStatus(it.status)).forEach(syncStream);
    } catch (err) {
      if (!err || err.status !== 404) {
        /* keep empty */
      }
      store.patch({ items: [] });
    }
    paint();
    if (onBadge) onBadge(active().length);
  }

  return {
    list: items,
    subscribe: store.subscribe,
    cancel,
    dismiss,
    track,
    restore,
    mountTray,
    get(id) {
      return items().find((it) => it.id === id) || null;
    },
  };
}
