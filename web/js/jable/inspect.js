import { html, qs } from "../core/dom.js";
import { get } from "../core/api.js";
import { coverUrl } from "../core/format.js";
import { playKey, state } from "./state.js";
import { inspectHash, listHashBase, watchHash } from "./route.js";
import { fmtWorkDate, markActiveCards, parseActors, rememberModelName } from "./cards.js";
import { knownItem } from "./data.js";
import {
  attachDmmPreview,
  attachInspectHls,
  cachedPlayStream,
  destroyInspectHls,
  getPlayInfo,
  loadHls,
  playErrorMessage,
  resetInspectVideo,
} from "./player.js";

function showInspectPanel(on) {
  const panel = qs("#jb-inspect");
  if (!panel) return;
  panel.hidden = !on;
  if (on) panel.removeAttribute("hidden");
  else panel.setAttribute("hidden", "");
}

export function setInspectPlayUi(mode) {
  state.inspectPlay = mode === "full" ? "full" : "preview";
  const badge = qs("#jb-inspect-badge");
  const fullBtn = qs("#jb-inspect-full");
  if (badge) badge.textContent = state.inspectPlay === "full" ? "完整视频" : "DMM 预览";
  if (fullBtn) {
    fullBtn.disabled = false;
    fullBtn.textContent = state.inspectPlay === "full" ? "预览短片" : "播放完整视频";
  }
}

function fillInspectChips(host, items, kind) {
  if (!host) return;
  // innerHTML: chip labels escaped by html``
  host.innerHTML = (items || [])
    .map((it) => {
      const name = typeof it === "string" ? it : (it && (it.name || it.title)) || "";
      const slug = typeof it === "string" ? "" : (it && it.slug) || "";
      if (!name) return "";
      if (kind === "tag") {
        const path = it && it.kind === "cat" ? "cat" : "tag";
        return html`<a class="jb-chip" href="${slug ? `#/jable/${path}/${encodeURIComponent(slug)}` : "#/jable"}">${name}</a>`;
      }
      if (kind === "actor") {
        if (slug) rememberModelName(slug, name);
        return html`<a class="jb-chip" href="${slug ? `#/jable/model/${encodeURIComponent(slug)}` : "#"}">${name}</a>`;
      }
      return html`<span class="jb-chip">${name}</span>`;
    })
    .join("");
}

function inferHomeInspectSource(code) {
  const key = playKey(code);
  const home = state.jableHome || {};
  const hot = ((home.hot || {}).items) || [];
  const latest = ((home.latest || {}).items) || [];
  const inHot = hot.some((it) => playKey(it && it.id) === key);
  const inLatest = latest.some((it) => playKey(it && it.id) === key);
  if (inLatest && !inHot) return "latest";
  return "hot";
}

function applyInspectSource(source) {
  if (state.jmode === "home") {
    const src = source || "hot";
    state.inspectSource = src;
    document.body.classList.toggle("jb-inspect-from-hot", src === "hot");
    document.body.classList.toggle("jb-inspect-from-latest", src === "latest");
    return;
  }
  state.inspectSource = "";
  document.body.classList.remove("jb-inspect-from-hot", "jb-inspect-from-latest");
}

export function inspectSourceFromCard(card) {
  if (!card) return "";
  if (card.closest("#jb-hot-grid, #jb-sec-hot")) return "hot";
  if (card.closest("#jb-latest, #jb-sec-latest")) return "latest";
  return "";
}

export function fillInspectFromApi(code) {
  const raw = playKey(code);
  if (!raw) return;
  get("/api/jable/inspect?code=" + encodeURIComponent(raw))
    .then((data) => {
      if (playKey(state.inspectCode) !== raw) return;
      const titleEl = qs("#jb-inspect-title");
      const dateEl = qs("#jb-inspect-date");
      const video = qs("#jb-inspect-video");
      if (titleEl) titleEl.textContent = data.title || titleEl.textContent;
      if (dateEl) dateEl.textContent = data.date || "";
      fillInspectChips(qs("#jb-inspect-actors"), data.actors, "actor");
      fillInspectChips(qs("#jb-inspect-tags"), data.tags, "tag");
      if (video && data.cover && !video.poster) video.poster = coverUrl(data.cover);
    })
    .catch(() => {});
}

export async function startInspectHls(code) {
  const raw = playKey(code || state.inspectCode);
  const video = qs("#jb-inspect-video");
  const statusEl = qs("#jb-inspect-status");
  const fullBtn = qs("#jb-inspect-full");
  if (!raw || !video) return;
  const seq = state.dmmSeq;
  const stillMine = () => playKey(state.inspectCode) === raw && state.dmmSeq === seq;
  const cached = cachedPlayStream(raw);
  const clearProgressive = () => {
    if (video.getAttribute("src")) {
      video.pause();
      video.removeAttribute("src");
    }
  };
  try {
    await loadHls();
  } catch {
    /* native HLS or DMM fallback */
  }
  if (cached) {
    clearProgressive();
    attachInspectHls(video, cached);
    setInspectPlayUi("full");
    if (statusEl) statusEl.textContent = "";
    fillInspectFromApi(raw);
    return;
  }
  if (fullBtn) {
    fullBtn.disabled = true;
    fullBtn.textContent = "正在解析 m3u8…";
  }
  if (statusEl) statusEl.textContent = "正在解析 m3u8…";
  try {
    const data = await getPlayInfo(raw);
    if (!stillMine()) return;
    if (!data || !data.stream) throw new Error("没有播放地址");
    clearProgressive();
    attachInspectHls(video, data.stream);
    setInspectPlayUi("full");
    if (statusEl) statusEl.textContent = "";
    fillInspectFromApi(raw);
  } catch (err) {
    if (!stillMine()) return;
    if (statusEl) statusEl.textContent = playErrorMessage(err);
    setInspectPlayUi("preview");
    const mine = () => stillMine() && state.inspectPlay === "preview";
    attachDmmPreview(raw, video, statusEl, mine);
  } finally {
    if (fullBtn && stillMine()) {
      fullBtn.disabled = false;
      fullBtn.textContent = state.inspectPlay === "full" ? "预览短片" : "播放完整视频";
    }
  }
}

export async function playInspectFull(code) {
  const raw = playKey(code || state.inspectCode);
  const video = qs("#jb-inspect-video");
  const statusEl = qs("#jb-inspect-status");
  if (!raw || !video) return;
  if (state.inspectPlay === "full") {
    state.dmmSeq += 1;
    setInspectPlayUi("preview");
    if (statusEl) statusEl.textContent = "";
    destroyInspectHls(true);
    video.pause();
    video.removeAttribute("src");
    try {
      video.load();
    } catch {
      /* ignore */
    }
    const mine = () => playKey(state.inspectCode) === raw && state.inspectPlay === "preview";
    attachDmmPreview(raw, video, statusEl, mine);
    return;
  }
  await startInspectHls(raw);
}

export function closeJableInspect(opts = {}) {
  const fromHash = opts.fromHash;
  const skipHash = opts.skipHash || fromHash;
  const wasOpen = !!state.inspectCode || document.body.classList.contains("jb-inspect-open");
  const previousCode = state.inspectCode;
  const panel = qs("#jb-inspect");
  const returnFocus = panel && panel.contains(document.activeElement);
  state.inspectCode = "";
  state.inspectSource = "";
  document.body.classList.remove("jb-inspect-open", "jb-inspect-from-hot", "jb-inspect-from-latest");
  showInspectPanel(false);
  resetInspectVideo();
  setInspectPlayUi("preview");
  const status = qs("#jb-inspect-status");
  if (status) status.textContent = "";
  markActiveCards(state.root, "");
  if (wasOpen && returnFocus && !opts.skipPaint) {
    const source = (state.root || document).querySelector(`.av-card[data-code="${previousCode}"]`);
    source?.focus({ preventScroll: true });
  }
  if (wasOpen && !skipHash && state.ctx) {
    const next = listHashBase();
    if (location.hash !== next) state.ctx.replace(next);
  }
}

export function openJableInspect(code, opts = {}) {
  let raw = String(code || "").trim();
  try {
    raw = decodeURIComponent(raw);
  } catch {
    /* keep */
  }
  if (!raw) return;
  const fromHash = opts.fromHash;
  const source = opts.source || "";
  if (playKey(state.inspectCode) === playKey(raw) && document.body.classList.contains("jb-inspect-open")) {
    if (source) applyInspectSource(source);
    if (!fromHash && state.ctx) {
      const next = inspectHash(raw);
      if (location.hash !== next) state.ctx.navigate(next);
    }
    return;
  }
  state.inspectCode = raw;
  document.body.classList.add("jb-inspect-open");
  applyInspectSource(source || (state.jmode === "home" ? inferHomeInspectSource(raw) : ""));
  showInspectPanel(true);
  qs("#jb-inspect-close")?.focus({ preventScroll: true });
  setInspectPlayUi("full");
  const watchLink = qs("#jb-inspect-watch");
  if (watchLink) watchLink.href = watchHash(raw);
  const known = knownItem(raw);
  const titleEl = qs("#jb-inspect-title");
  const dateEl = qs("#jb-inspect-date");
  const statusEl = qs("#jb-inspect-status");
  const video = qs("#jb-inspect-video");
  if (titleEl) titleEl.textContent = (known && (known.title || known.id)) || raw.toUpperCase();
  if (dateEl) dateEl.textContent = (known && fmtWorkDate(known.date)) || "";
  fillInspectChips(qs("#jb-inspect-actors"), (known && parseActors(known.actors, known.title)) || [], "actor");
  fillInspectChips(qs("#jb-inspect-tags"), []);
  if (statusEl) statusEl.textContent = "正在准备播放…";
  state.dmmSeq += 1;
  if (video) {
    const poster = (known && known.cover) || (knownItem(raw) && knownItem(raw).cover);
    if (poster) video.poster = coverUrl(poster);
    startInspectHls(raw);
  }
  markActiveCards(state.root, raw);
  if (!fromHash && state.ctx) {
    const next = inspectHash(raw);
    if (location.hash !== next) state.ctx.navigate(next);
  }
}

export function inspectPanelHtml() {
  return html`<div id="jb-inspect-divider" hidden tabindex="0" role="separator" aria-orientation="vertical" aria-label="调整详情分栏宽度">
    <span></span>
  </div>
  <aside id="jb-inspect" hidden>
    <div class="inspect-toolbar">
      <span>作品详情</span>
      <div>
        <button type="button" id="jb-inspect-size" class="btn btn-ghost" aria-pressed="false"><span>放大视频</span></button>
        <button type="button" id="jb-inspect-close" class="btn btn-ghost jb-inspect-close" aria-label="关闭详情">关闭</button>
      </div>
    </div>
    <div class="jb-inspect-player">
      <video id="jb-inspect-video" playsinline muted></video>
      <span id="jb-inspect-badge" class="jb-inspect-badge">完整视频</span>
    </div>
    <p id="jb-inspect-status" class="jable-status"></p>
    <div class="jb-inspect-meta">
      <p id="jb-inspect-date" class="jb-inspect-date"></p>
      <h3 id="jb-inspect-title"></h3>
      <div class="jb-inspect-actions">
        <button type="button" id="jb-inspect-full" class="btn btn-secondary">播放完整视频</button>
        <button type="button" id="jb-inspect-save" class="btn btn-primary jb-inspect-save">下载此片</button>
        <a id="jb-inspect-watch" class="btn btn-ghost" href="#/jable">打开播放页</a>
      </div>
      <div class="jb-inspect-block">
        <span>演员</span>
        <div id="jb-inspect-actors" class="jb-chip-row"></div>
      </div>
      <div class="jb-inspect-block">
        <span>类型</span>
        <div id="jb-inspect-tags" class="jb-chip-row"></div>
      </div>
    </div>
  </aside>`;
}

export function bindInspectLayout(view) {
  const stage = qs("#jb-stage", view);
  const list = qs("#jb-stage-main", view);
  const panel = qs("#jb-inspect", view);
  const divider = qs("#jb-inspect-divider", view);
  const sizeButton = qs("#jb-inspect-size", view);
  if (!view || !stage || !list || !panel || !divider || !sizeButton) return () => {};

  const stacked = matchMedia("(max-width: 1023px)");
  const DEFAULT_SHARE = 58;
  let share = DEFAULT_SHARE;
  let restoreShare = DEFAULT_SHARE;
  let expanded = false;
  let isOpen = false;
  let lastCode = "";
  let dragPointer = null;
  let priorPageScroll = 0;
  let measureFrame = 0;
  let finishFrame = 0;

  function limits() {
    if (stacked.matches) return { min: 48, max: 72 };
    const width = stage.getBoundingClientRect().width;
    return { min: 48, max: Math.max(48, Math.min(72, Math.floor(((width - 304) / width) * 100))) };
  }

  function applyShare(value, persist = false) {
    const range = limits();
    share = Math.max(range.min, Math.min(range.max, Number(value) || DEFAULT_SHARE));
    view.style.setProperty("--inspect-share", `${share}%`);
    divider.setAttribute("aria-valuemin", range.min);
    divider.setAttribute("aria-valuemax", range.max);
    divider.setAttribute("aria-valuenow", Math.round(share));
    divider.setAttribute("aria-valuetext", `视频 ${Math.round(share)}%，列表 ${Math.round(100 - share)}%`);
    sizeButton.setAttribute("aria-pressed", String(expanded));
    const label = sizeButton.querySelector("span");
    if (label) label.textContent = expanded ? "恢复比例" : "放大视频";
    sizeButton.title = expanded ? "恢复刚才的列表与视频比例" : "增大播放器占比";
    if (persist) {
      try {
        localStorage.setItem("od-inspect-share", String(share));
      } catch {
        /* optional */
      }
    }
  }

  function measure() {
    cancelAnimationFrame(measureFrame);
    measureFrame = requestAnimationFrame(() => {
      if (!isOpen || stacked.matches) return;
      const top = stage.getBoundingClientRect().top;
      view.style.setProperty("--inspect-height", `${Math.max(320, innerHeight - Math.max(68, top) - 20)}px`);
      applyShare(share);
    });
  }

  function endDrag() {
    if (dragPointer !== null && divider.hasPointerCapture(dragPointer)) divider.releasePointerCapture(dragPointer);
    dragPointer = null;
    document.body.classList.remove("inspect-resizing");
  }

  function sync() {
    const open = document.body.classList.contains("jb-inspect-open") && !panel.hidden;
    divider.hidden = !open || stacked.matches;
    const code = view.querySelector(".av-card.is-inspect")?.dataset.code || "";
    if (open && !isOpen) {
      cancelAnimationFrame(finishFrame);
      priorPageScroll = scrollY;
      isOpen = true;
      try {
        const saved = Number(localStorage.getItem("od-inspect-share"));
        if (saved >= 48 && saved <= 72) share = saved;
      } catch {
        /* default */
      }
      applyShare(share);
      finishFrame = requestAnimationFrame(() => {
        if (!isOpen) return;
        if (stacked.matches) panel.scrollIntoView({ block: "start", behavior: "instant" });
        else {
          window.scrollTo({ top: 0, behavior: "instant" });
          view.querySelector(".av-card.is-inspect")?.scrollIntoView({ block: "nearest", behavior: "instant" });
        }
        measure();
      });
    } else if (!open && isOpen) {
      isOpen = false;
      cancelAnimationFrame(finishFrame);
      endDrag();
      if (expanded) share = restoreShare;
      expanded = false;
      lastCode = "";
      list.scrollTop = 0;
      if (document.body.dataset.site === "jable" && document.body.dataset.jmode !== "watch") {
        finishFrame = requestAnimationFrame(() => window.scrollTo({ top: priorPageScroll, behavior: "instant" }));
      }
    }
    if (open && code !== lastCode) {
      panel.scrollTop = 0;
      lastCode = code;
    }
  }

  const onDown = (event) => {
    if (event.button !== 0 || stacked.matches) return;
    dragPointer = event.pointerId;
    divider.setPointerCapture(dragPointer);
    document.body.classList.add("inspect-resizing");
    expanded = false;
    divider.focus({ preventScroll: true });
    event.preventDefault();
  };
  const onMove = (event) => {
    if (event.pointerId !== dragPointer) return;
    const rect = stage.getBoundingClientRect();
    applyShare(((rect.right - event.clientX - 12) / rect.width) * 100);
  };
  const onUp = () => {
    if (dragPointer !== null) applyShare(share, true);
    endDrag();
  };
  const onKey = (event) => {
    const step = event.shiftKey ? 5 : 2;
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    expanded = false;
    const next = event.key === "Home" ? DEFAULT_SHARE : event.key === "End" ? limits().max : share + (event.key === "ArrowLeft" ? step : -step);
    applyShare(next, true);
  };
  const onSize = () => {
    if (expanded) {
      expanded = false;
      applyShare(restoreShare);
    } else {
      restoreShare = share;
      expanded = true;
      applyShare(limits().max);
    }
  };
  const onStack = () => {
    endDrag();
    sync();
    if (isOpen && !stacked.matches) window.scrollTo({ top: 0, behavior: "instant" });
    measure();
  };

  divider.addEventListener("pointerdown", onDown);
  divider.addEventListener("pointermove", onMove);
  divider.addEventListener("pointerup", onUp);
  divider.addEventListener("pointercancel", endDrag);
  divider.addEventListener("lostpointercapture", endDrag);
  divider.addEventListener("dblclick", () => {
    expanded = false;
    applyShare(DEFAULT_SHARE, true);
  });
  divider.addEventListener("keydown", onKey);
  sizeButton.addEventListener("click", onSize);
  const bodyOb = new MutationObserver(sync);
  const panelOb = new MutationObserver(sync);
  const listOb = new MutationObserver(() => {
    if (isOpen) sync();
  });
  bodyOb.observe(document.body, { attributes: true, attributeFilter: ["class", "data-site"] });
  panelOb.observe(panel, { attributes: true, attributeFilter: ["hidden"] });
  listOb.observe(list, { childList: true, subtree: true });
  const ro = new ResizeObserver(measure);
  ro.observe(stage);
  window.addEventListener("resize", measure);
  window.addEventListener("scroll", measure, { passive: true });
  stacked.addEventListener("change", onStack);
  sync();

  return () => {
    cancelAnimationFrame(measureFrame);
    cancelAnimationFrame(finishFrame);
    endDrag();
    bodyOb.disconnect();
    panelOb.disconnect();
    listOb.disconnect();
    ro.disconnect();
    divider.removeEventListener("pointerdown", onDown);
    divider.removeEventListener("pointermove", onMove);
    divider.removeEventListener("pointerup", onUp);
    divider.removeEventListener("pointercancel", endDrag);
    divider.removeEventListener("lostpointercapture", endDrag);
    divider.removeEventListener("keydown", onKey);
    sizeButton.removeEventListener("click", onSize);
    window.removeEventListener("resize", measure);
    window.removeEventListener("scroll", measure);
    stacked.removeEventListener("change", onStack);
    view.style.removeProperty("--inspect-share");
    view.style.removeProperty("--inspect-height");
  };
}
