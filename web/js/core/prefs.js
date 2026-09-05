const KEYS = {
  theme: "od-theme",
  sidebar: "od-sidebar-collapsed",
  libraryView: "od-library-view",
};

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw == null ? fallback : raw;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export function getThemePref() {
  const v = read(KEYS.theme, "system");
  return v === "light" || v === "dark" || v === "system" ? v : "system";
}

export function resolveTheme(pref = getThemePref()) {
  if (pref === "light" || pref === "dark") return pref;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(pref = getThemePref()) {
  document.documentElement.dataset.theme = resolveTheme(pref);
  write(KEYS.theme, pref);
}

export function setThemePref(pref) {
  applyTheme(pref);
}

export function getSidebarCollapsed() {
  return read(KEYS.sidebar, "0") === "1";
}

export function setSidebarCollapsed(on) {
  write(KEYS.sidebar, on ? "1" : "0");
}

export function getLibraryView() {
  const v = read(KEYS.libraryView, "grid");
  return v === "list" ? "list" : "grid";
}

export function setLibraryView(mode) {
  write(KEYS.libraryView, mode === "list" ? "list" : "grid");
}

export function watchSystemTheme(onChange) {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const fn = () => {
    if (getThemePref() === "system") {
      applyTheme("system");
      if (onChange) onChange();
    }
  };
  if (mq.addEventListener) mq.addEventListener("change", fn);
  else mq.addListener(fn);
  return () => {
    if (mq.removeEventListener) mq.removeEventListener("change", fn);
    else mq.removeListener(fn);
  };
}
