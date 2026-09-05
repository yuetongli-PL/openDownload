import { html, raw, qs, delegate } from "../core/dom.js";
import { post } from "../core/api.js";
import { isActiveStatus, todayStart } from "../core/format.js";
import { Button } from "../ui/button.js";
import { TaskRow } from "../ui/task-row.js";
import { EmptyState } from "../ui/empty.js";
import { Dialog, openDialog } from "../ui/dialog.js";
import { toast } from "../ui/toast.js";

let ctx = null;
let root = null;
let off = null;
let unsub = null;

function groups(list) {
  const running = [];
  const queued = [];
  const history = [];
  list.forEach((it) => {
    if (it.status === "running") running.push(it);
    else if (it.status === "queued") queued.push(it);
    else history.push(it);
  });
  return { running, queued, history };
}

function paint() {
  if (!ctx || !root) return;
  const list = ctx.tasks.list();
  const g = groups(list);
  const start = todayStart();
  const today = list.filter((it) => it.kind === "download" && it.status === "done" && (it.finished || it.updated || it.created) >= start).length;
  root.innerHTML = html`<section class="view view-tasks">
    <h1>任务</h1>
    <div class="task-stats">
      <div class="task-stat"><strong>${g.running.length}</strong><span>进行中</span></div>
      <div class="task-stat"><strong>${g.queued.length}</strong><span>排队</span></div>
      <div class="task-stat"><strong>${today}</strong><span>今日完成</span></div>
    </div>
    ${list.length
      ? html`
          ${g.running.length ? html`<section class="task-group"><h2>进行中</h2>${g.running.map((t) => html`<div class="task-page-row">${TaskRow(t)}</div>`)}</section>` : ""}
          ${g.queued.length ? html`<section class="task-group"><h2>排队</h2>${g.queued.map((t) => html`<div class="task-page-row">${TaskRow(t)}</div>`)}</section>` : ""}
          ${g.history.length
            ? html`<section class="task-group">
                <h2>历史 ${Button({ variant: "ghost", label: "清空历史", attrs: "data-clear-hist" })}</h2>
                ${g.history.map((t) => html`<div class="task-page-row">${TaskRow(t)}</div>`)}
              </section>`
            : ""}
        `
      : EmptyState({ title: "还没有任务", text: "解析并确认保存后，进度会出现在这里。", action: { label: "去首页", id: "home" } })}
    <div id="task-dlg"></div>
  </section>`;
}

function confirmClear() {
  const host = qs("#task-dlg", root);
  const hist = ctx.tasks.list().filter((it) => !isActiveStatus(it.status));
  if (!hist.length) {
    toast("没有可清空的历史", { type: "info" });
    return;
  }
  openDialog(
    host,
    Dialog({
      title: "清空历史",
      body: html`<p>将删除 ${hist.length} 条已结束的任务记录。进行中的任务不会受影响。</p>`,
      foot: html`${Button({ variant: "ghost", label: "取消", attrs: "data-dialog-close" })}
        ${Button({ variant: "danger", label: "清空历史", attrs: "data-confirm-clear" })}`,
    })
  );
}

export default {
  mount(el, next) {
    root = el;
    ctx = next;
    paint();
    unsub = ctx.tasks.subscribe(() => paint());
    off = delegate(root, "click", "[data-act], [data-clear-hist], [data-confirm-clear], [data-empty-action]", (event, node) => {
      if (node.dataset.emptyAction === "home") {
        ctx.navigate("#/");
        return;
      }
      if (node.matches("[data-clear-hist]")) {
        confirmClear();
        return;
      }
      if (node.matches("[data-confirm-clear]")) {
        const hist = ctx.tasks.list().filter((it) => !isActiveStatus(it.status));
        hist.forEach((it) => ctx.tasks.dismiss(it.id));
        toast("已清空历史", { type: "ok" });
        const dlg = qs("dialog", root);
        if (dlg) dlg.close();
        return;
      }
      const row = node.closest("[data-task]");
      const id = row && row.dataset.task;
      const act = node.dataset.act;
      if (!id) return;
      if (act === "cancel") ctx.tasks.cancel(id);
      if (act === "open") post("/api/open-library").catch((err) => toast(err.message, { type: "error" }));
      if (act === "reopen") ctx.collect.reopen(id);
      if (act === "dismiss") ctx.tasks.dismiss(id);
    });
  },
  update(next) {
    ctx = next;
    paint();
  },
  unmount() {
    if (off) off();
    if (unsub) unsub();
    off = unsub = null;
    root = ctx = null;
  },
};
