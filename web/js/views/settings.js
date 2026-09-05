import { html, qs, delegate } from "../core/dom.js";
import { get, post } from "../core/api.js";
import { applyTheme, getThemePref } from "../core/prefs.js";
import { Button } from "../ui/button.js";
import { Field } from "../ui/field.js";
import { SegmentedTabs, bindSegmented } from "../ui/chip.js";
import { toast } from "../ui/toast.js";

let ctx = null;
let root = null;
let off = null;
let health = {};
let settings = { library: "", limit: 40, workers: 64 };
let errors = {};

function healthItems(h) {
  return [
    { ok: !!h.python, name: "Python", help: "运行工作台", detail: h.python || "未找到" },
    { ok: !!h.ffmpeg, name: "FFmpeg", help: "YouTube / Jable 封装 mp4", detail: h.ffmpeg || "未找到" },
    { ok: !!h.yt_dlp, name: "yt-dlp", help: "YouTube 解析与下载", detail: h.yt_dlp || "未找到" },
    { ok: !!h.playwright, name: "Playwright", help: "抖音登录类页面", detail: h.playwright ? "已安装" : "未安装" },
    { ok: !!h.cookie, name: "抖音 cookie", help: "主页 / 喜欢 / 关注 / 话题", detail: h.cookie ? "已加载" : "未找到" },
  ];
}

function paint() {
  const items = healthItems(health);
  const theme = getThemePref();
  const showAbout = health.version || health.port;
  root.innerHTML = html`<section class="view view-settings">
    <h1>设置</h1>
    <section class="set-block">
      <h2>依赖检查</h2>
      <ul class="health-list">
        ${items.map(
          (it) => html`<li><span>${it.name}<small>${it.help} · ${it.detail}</small></span><span class="status-dot ${it.ok ? "is-ok" : "is-bad"}"><i></i>${it.ok ? "就绪" : "缺少"}</span></li>`
        )}
      </ul>
    </section>
    <section class="set-block">
      <h2>保存位置</h2>
      <div class="set-row">
        ${Field({ label: "馆藏目录", id: "set-library", value: settings.library || "" })}
        ${Button({ variant: "secondary", label: "打开目录", attrs: "data-open-lib" })}
      </div>
    </section>
    <section class="set-block">
      <h2>解析与下载</h2>
      ${Field({
        label: "列表解析条数",
        id: "set-limit",
        type: "number",
        min: 1,
        max: 500,
        value: settings.limit || 40,
        help: "频道、主页、热门列表一次最多展开多少条。",
        error: errors.limit || "",
      })}
      ${Field({
        label: "并行分片 / 连接数",
        id: "set-workers",
        type: "number",
        min: 1,
        max: 256,
        value: settings.workers || 64,
        help: "Jable 分片与抖音并行下载用。网络不稳时可调低。",
        error: errors.workers || "",
      })}
    </section>
    <section class="set-block">
      <h2>抖音登录</h2>
      <ol class="set-steps">
        <li>用 Chrome 登录 <a href="https://www.douyin.com/?recommend=1" target="_blank" rel="noreferrer">douyin.com</a></li>
        <li>用 Get cookies.txt LOCALLY 导出 Netscape 格式</li>
        <li>把全文粘贴到下方并保存，文件会写入本目录 python/cookie.txt</li>
      </ol>
      ${Field({ label: "Cookie", id: "set-cookie", type: "textarea", rows: 5, placeholder: "sessionid=... 或 Netscape cookies.txt" })}
    </section>
    <section class="set-block">
      <h2>外观</h2>
      ${SegmentedTabs({
        items: [
          { id: "system", name: "跟随系统" },
          { id: "light", name: "浅色" },
          { id: "dark", name: "深色" },
        ],
        value: theme,
        name: "theme",
      })}
    </section>
    ${showAbout
      ? html`<section class="set-block">
          <h2>关于</h2>
          <p class="source-note">${health.version ? `版本 ${health.version}` : ""} ${health.port ? `· 端口 ${health.port}` : ""}</p>
        </section>`
      : ""}
    ${Button({ variant: "primary", label: "保存", attrs: "data-save-set" })}
  </section>`;
}

function readForm() {
  const library = qs("#set-library", root)?.value || "";
  const limit = Number(qs("#set-limit", root)?.value || 40);
  const workers = Number(qs("#set-workers", root)?.value || 64);
  const cookie = qs("#set-cookie", root)?.value.trim() || "";
  errors = {};
  if (!Number.isFinite(limit) || limit < 1 || limit > 500) errors.limit = "条数需在 1–500 之间";
  if (!Number.isFinite(workers) || workers < 1 || workers > 256) errors.workers = "并发需在 1–256 之间";
  return { library, limit, workers, cookie };
}

async function save() {
  const form = readForm();
  if (errors.limit || errors.workers) {
    paint();
    qs("#set-library", root).value = form.library;
    qs("#set-limit", root).value = form.limit;
    qs("#set-workers", root).value = form.workers;
    qs("#set-cookie", root).value = form.cookie;
    return;
  }
  try {
    const saved = await post("/api/settings", { library: form.library, limit: form.limit, workers: form.workers });
    settings = { ...settings, ...saved };
    if (form.cookie) await post("/api/cookie", { text: form.cookie });
    health = await get("/api/health").catch(() => health);
    ctx.store.patch({ settings, health, limit: settings.limit });
    toast("环境已保存", { type: "ok" });
    paint();
  } catch (err) {
    toast(err.message || "保存失败", { type: "error" });
  }
}

export default {
  async mount(el, next) {
    root = el;
    ctx = next;
    try {
      const [s, h] = await Promise.all([get("/api/settings"), get("/api/health")]);
      settings = s;
      health = h;
      ctx.store.patch({ settings, health, limit: s.limit });
    } catch (err) {
      toast(err.message || "无法读取设置", { type: "error" });
    }
    paint();
    bindSegmented(root);
    off = delegate(root, "click", "[data-save-set], [data-open-lib], [role=tab]", (event, node) => {
      if (node.matches("[role=tab]") && node.closest('[data-seg="theme"]')) {
        applyTheme(node.dataset.value);
        ctx.store.patch({ theme: node.dataset.value });
        toast("外观已更新", { type: "ok" });
        return;
      }
      if (node.matches("[data-save-set]")) save();
      if (node.matches("[data-open-lib]")) post("/api/open-library").catch((e) => toast(e.message, { type: "error" }));
    });
  },
  update(next) {
    ctx = next;
  },
  unmount() {
    if (off) off();
    off = null;
    root = ctx = null;
  },
};
