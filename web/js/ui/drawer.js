import { html, raw, focusTrap } from "../core/dom.js";
import { icon } from "./icons.js";

/**
 * Drawer / Sheet：桌面右侧滑入，移动端由 CSS 变为底部 sheet。
 * openDrawer(el, { onClose, returnFocus })
 */
export function DrawerChrome({ title = "", kicker = "", steps = "", maximized = false } = {}) {
  return html`<header class="drawer-head">
    <div class="collect-title">
      <p class="source-cap">${kicker}</p>
      <h2>${title}</h2>
      ${steps ? raw(steps) : ""}
    </div>
    <button type="button" class="icon-btn" data-drawer-max aria-label="${maximized ? "还原宽度" : "最大化"}">${raw(icon("maximize"))}</button>
    <button type="button" class="icon-btn" data-drawer-close aria-label="关闭">${raw(icon("close"))}</button>
  </header>`;
}

export function openPanel(el, { returnFocus, autoFocus = true, installTrap = true } = {}) {
  const trigger = returnFocus || document.activeElement;
  el.hidden = false;
  el.classList.remove("is-closing");
  void el.offsetWidth;
  el.classList.add("is-open");
  const trap = installTrap ? focusTrap(el, { autoFocus }) : () => {};
  return {
    trigger,
    release() {
      trap();
    },
  };
}

export function closePanel(el, session) {
  if (!el) return;
  el.classList.add("is-closing");
  el.classList.remove("is-open");
  const done = () => {
    el.hidden = true;
    el.classList.remove("is-closing");
    if (session && session.release) session.release();
    if (session && session.trigger && session.trigger.focus) session.trigger.focus();
  };
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) done();
  else setTimeout(done, 180);
}

export function isMobileSheet() {
  return window.matchMedia("(max-width: 767px)").matches;
}
