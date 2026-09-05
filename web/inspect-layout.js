/* UI-only split layout. Resizing never recreates or reloads the video element. */
(() => {
  const body = document.body;
  const view = document.getElementById("view-jable");
  const stage = document.getElementById("jb-stage");
  const list = document.getElementById("jb-stage-main");
  const panel = document.getElementById("jb-inspect");
  const divider = document.getElementById("jb-inspect-divider");
  const sizeButton = document.getElementById("jb-inspect-size");
  if (!view || !stage || !list || !panel || !divider || !sizeButton) return;

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
    return { min: 48, max: Math.max(48, Math.min(72, Math.floor((width - 304) / width * 100))) };
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
    sizeButton.querySelector("span").textContent = expanded ? "恢复比例" : "放大视频";
    sizeButton.title = expanded ? "恢复刚才的列表与视频比例" : "增大播放器占比";
    if (persist) {
      try { localStorage.setItem("od-inspect-share", String(share)); } catch { /* Optional preference. */ }
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

  function sync() {
    const open = body.classList.contains("jb-inspect-open") && !panel.hidden;
    divider.hidden = !open || stacked.matches;
    const code = view.querySelector(".av-card.is-inspect")?.dataset.code || "";
    if (open && !isOpen) {
      cancelAnimationFrame(finishFrame);
      priorPageScroll = scrollY;
      isOpen = true;
      try {
        const saved = Number(localStorage.getItem("od-inspect-share"));
        if (saved >= 48 && saved <= 72) share = saved;
      } catch { /* Default layout still works. */ }
      applyShare(share);
      // Opening a split pane changes document geometry. Bring both panes into view.
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
      // Restore browsing position only if closing within the same Jable view.
      if (body.dataset.site === "jable" && body.dataset.jmode !== "watch") {
        finishFrame = requestAnimationFrame(() => window.scrollTo({ top: priorPageScroll, behavior: "instant" }));
      }
    }
    if (open && code !== lastCode) {
      panel.scrollTop = 0;
      lastCode = code;
    }
  }

  function endDrag() {
    if (dragPointer !== null && divider.hasPointerCapture(dragPointer)) divider.releasePointerCapture(dragPointer);
    dragPointer = null;
    body.classList.remove("inspect-resizing");
  }

  divider.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || stacked.matches) return;
    dragPointer = event.pointerId;
    divider.setPointerCapture(dragPointer);
    body.classList.add("inspect-resizing");
    expanded = false;
    divider.focus({ preventScroll: true });
    event.preventDefault();
  });
  divider.addEventListener("pointermove", (event) => {
    if (event.pointerId !== dragPointer) return;
    const rect = stage.getBoundingClientRect();
    applyShare((rect.right - event.clientX - 12) / rect.width * 100);
  });
  divider.addEventListener("pointerup", () => { if (dragPointer !== null) applyShare(share, true); endDrag(); });
  divider.addEventListener("pointercancel", endDrag);
  divider.addEventListener("lostpointercapture", endDrag);
  divider.addEventListener("dblclick", () => { expanded = false; applyShare(DEFAULT_SHARE, true); });
  divider.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 5 : 2;
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    expanded = false;
    const next = event.key === "Home" ? DEFAULT_SHARE : event.key === "End" ? limits().max : share + (event.key === "ArrowLeft" ? step : -step);
    applyShare(next, true);
  });
  sizeButton.addEventListener("click", () => {
    if (expanded) { expanded = false; applyShare(restoreShare); }
    else { restoreShare = share; expanded = true; applyShare(limits().max); }
  });

  new MutationObserver(sync).observe(body, { attributes: true, attributeFilter: ["class", "data-site"] });
  new MutationObserver(sync).observe(panel, { attributes: true, attributeFilter: ["hidden"] });
  new MutationObserver(() => { if (isOpen) sync(); }).observe(list, { childList: true, subtree: true });
  new ResizeObserver(measure).observe(stage);
  window.addEventListener("resize", measure);
  window.addEventListener("scroll", measure, { passive: true });
  stacked.addEventListener("change", () => {
    endDrag();
    sync();
    if (isOpen && !stacked.matches) window.scrollTo({ top: 0, behavior: "instant" });
    measure();
  });
  sync();
})();
