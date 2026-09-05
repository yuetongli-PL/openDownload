function svg(d) {
  return `<svg class="nav-ico" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
}

export const icons = {
  download: svg('<path d="M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6"/>'),
  home: svg('<path d="m3 10 9-7 9 7M5 9v12h5v-7h4v7h5V9"/>'),
  library: svg('<path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v12H3V7Z"/>'),
  tasks: svg('<path d="M9 6h12M9 12h12M9 18h12M4 6h.01M4 12h.01M4 18h.01"/>'),
  settings: svg('<path d="M9 4h6l1 3 3 1 2 4-2 4-3 1-1 3H9l-1-3-3-1-2-4 2-4 3-1 1-3Zm3 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z"/>'),
  youtube: svg('<path d="M3 5h18v14H3V5Zm7 4 6 3-6 3V9Z"/>'),
  douyin: svg('<path d="M10 17V3l9 2v4l-6-2v10a4 4 0 1 1-3-3"/>'),
  search: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>'),
  menu: svg('<path d="M4 6h16M4 12h16M4 18h16"/>'),
  close: svg('<path d="m6 6 12 12M18 6 6 18"/>'),
  sun: svg('<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>'),
  moon: svg('<path d="M15 4a8 8 0 1 0 5 14 7 7 0 0 1-5-14Z"/>'),
  collapse: svg('<path d="M15 6 9 12l6 6"/>'),
  expand: svg('<path d="m9 6 6 6-6 6"/>'),
  maximize: svg('<path d="M14 4h6v6M20 4l-7 7M10 20H4v-6m0 6 7-7"/>'),
  folder: svg('<path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v12H3V7Z"/>'),
  copy: svg('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V6a2 2 0 0 1 2-2h10"/>'),
  trash: svg('<path d="M4 7h16M9 7V5h6v2m-8 0 1 14h8l1-14"/>'),
  refresh: svg('<path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v5h-5"/>'),
  grid: svg('<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>'),
  list: svg('<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>'),
  play: svg('<path d="m8 5 12 7-12 7V5Z"/>'),
  check: svg('<path d="m5 12 5 5 9-10"/>'),
  alert: svg('<path d="M12 9v4m0 4h.01M10.2 4.2 2.8 18a2 2 0 0 0 1.8 3h14.8a2 2 0 0 0 1.8-3L13.8 4.2a2 2 0 0 0-3.6 0Z"/>'),
  inbox: svg('<path d="M3 12 5 4h14l2 8v7H3v-7Zm0 0h6a3 3 0 0 0 6 0h6"/>'),
  chevron: svg('<path d="m9 6 6 6-6 6"/>'),
};

export function icon(name) {
  return icons[name] || "";
}
