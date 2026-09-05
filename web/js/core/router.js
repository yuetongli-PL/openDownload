function parseQuery(search) {
  const query = {};
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  params.forEach((value, key) => {
    query[key] = value;
  });
  return query;
}

function normalizeHash(raw) {
  let hash = String(raw || location.hash || "#/");
  if (!hash.startsWith("#")) hash = "#" + hash;
  if (hash === "#" || hash === "") hash = "#/";
  const body = hash.slice(1);
  const qAt = body.indexOf("?");
  const path = (qAt >= 0 ? body.slice(0, qAt) : body).replace(/^\/+/, "");
  const search = qAt >= 0 ? body.slice(qAt) : "";
  let segments = path.split("/").filter(Boolean);
  if (segments[0] === "auto") segments = [];
  if (segments[0] === "setup") segments = ["settings"];
  return { hash: "#/" + (segments.join("/") || "") + search, segments, query: parseQuery(search) };
}

function routeFrom(parsed) {
  const { segments, query } = parsed;
  const head = segments[0] || "";
  let name = "home";
  const params = {};
  if (!head) name = "home";
  else if (head === "jable") name = "jable";
  else if (head === "youtube" || head === "douyin") name = "source";
  else if (head === "library") name = "library";
  else if (head === "tasks") name = "tasks";
  else if (head === "settings") name = "settings";
  else name = "home";

  if (head === "youtube") params.tab = segments[1] || "all";
  if (head === "douyin") params.mode = segments[1] || "link";
  if (head === "jable") {
    params.mode = segments[1] || "home";
    params.rest = segments.slice(2);
  }
  if (head === "library") {
    params.site = query.site || "";
    params.q = query.q || "";
    params.sort = query.sort || "mtime";
  }
  return { name, segments, params, query, hash: parsed.hash };
}

export function parseLocation(hash = location.hash) {
  return routeFrom(normalizeHash(hash));
}

export function navigate(hash, opts = {}) {
  const next = normalizeHash(hash).hash;
  if (opts.replace) {
    history.replaceState(null, "", next);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    if (location.hash === next) {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
      return next;
    }
    location.hash = next;
  }
  return next;
}

export function replace(hash) {
  return navigate(hash, { replace: true });
}

const viewLoaders = {
  home: () => import("../views/home.js"),
  source: () => import("../views/source.js"),
  library: () => import("../views/library.js"),
  tasks: () => import("../views/tasks.js"),
  settings: () => import("../views/settings.js"),
  jable: () =>
    import("../jable/index.js").catch(() => import("../views/jable-placeholder.js")),
};

export function createRouter({ root, getCtx }) {
  let current = null;
  let currentName = "";
  let enterTimer = 0;
  let seq = 0;

  async function loadView(name) {
    const loader = viewLoaders[name] || viewLoaders.home;
    const mod = await loader();
    return mod.default || mod;
  }

  async function apply() {
    const my = ++seq;
    const route = parseLocation();
    const ctx = { ...getCtx(), route, navigate, replace };
    if (current && currentName === route.name && current.update) {
      current.update(ctx);
      document.body.dataset.route = route.name;
      document.body.dataset.site = route.segments[0] || "home";
      return;
    }
    if (current && current.unmount) current.unmount();
    current = null;
    currentName = "";
    document.body.dataset.route = route.name;
    document.body.dataset.site = route.segments[0] || "home";
    const view = await loadView(route.name);
    if (my !== seq) return;
    root.innerHTML = "";
    current = view;
    currentName = route.name;
    view.mount(root, ctx);
    root.classList.remove("is-enter");
    void root.offsetWidth;
    root.classList.add("is-enter");
    clearTimeout(enterTimer);
    enterTimer = setTimeout(() => root.classList.remove("is-enter"), 180);
  }

  function start() {
    if (!location.hash || location.hash === "#") history.replaceState(null, "", "#/");
    window.addEventListener("hashchange", apply);
    apply();
    return { apply, stop: () => window.removeEventListener("hashchange", apply) };
  }

  return { start, apply, navigate, replace, parseLocation };
}
