import { html, raw, qs } from "../core/dom.js";
import { get } from "../core/api.js";
import { state } from "./state.js";

const HOT_SORTS = [
  { id: "hot", name: "今日观看" },
  { id: "week", name: "每周观看" },
  { id: "month", name: "每月观看" },
  { id: "all", name: "最多观看" },
];

const MODEL_SORTS = [
  { id: "post_date", name: "发布时间" },
  { id: "video_viewed", name: "最多观看" },
];

function opt(attr, id, name, on) {
  return html`<button type="button" ${raw(attr)}="${id}" class="${on ? "on" : ""}">${name}</button>`;
}

function ddHtml(key, label, value, menu, wide) {
  return html`<div class="av-dd dropdown" data-dd="${key}">
    <button type="button" class="av-dd-btn dropdown-btn" aria-expanded="false">
      <span class="av-dd-label">${label}:</span>
      <span class="av-dd-value">${value}</span>
    </button>
    <div class="av-dd-menu dropdown-menu ${wide ? "wide" : ""}" hidden>${raw(menu)}</div>
  </div>`;
}

export function findListName(slug) {
  if (!slug) return "";
  const cat = state.catalog || {};
  const hit = (cat.categories || []).find((c) => c.slug === slug);
  if (hit) return hit.name;
  for (const group of cat.groups || []) {
    const tag = (group.tags || []).find((t) => t.slug === slug);
    if (tag) return tag.name;
  }
  return slug;
}

export function findTagGroup(slug) {
  if (!slug) return "";
  for (const group of (state.catalog && state.catalog.groups) || []) {
    if ((group.tags || []).some((t) => t.slug === slug)) return group.name;
  }
  return "";
}

export function cascadeHtml(groups, currentGroup, currentTag) {
  const left =
    opt("data-group", "", "全部", !currentGroup) +
    groups
      .map(
        (g) =>
          html`<button type="button" data-group="${g.name}" class="${g.name === currentGroup ? "on" : ""}">${g.name}<span class="av-dd-more" aria-hidden="true">›</span></button>`
      )
      .join("");
  const groupObj = groups.find((g) => g.name === currentGroup);
  const right = !currentGroup
    ? html`<p class="av-dd-hint">请选择一级</p>`
    : opt("data-tag", "", "全部", !currentTag) +
      (groupObj && groupObj.tags ? groupObj.tags : [])
        .map((t) => opt("data-tag", t.slug, t.name, t.slug === currentTag))
        .join("");
  return html`<div class="av-cascade">
    <div class="av-cascade-col" data-cascade="1">
      <div class="av-cascade-hd">一级</div>
      <div class="av-cascade-list">${raw(left)}</div>
    </div>
    <div class="av-cascade-col" data-cascade="2">
      <div class="av-cascade-hd">二级</div>
      <div class="av-cascade-list">${raw(right)}</div>
    </div>
  </div>`;
}

export function fillCascadeLevel2() {
  const list = qs('#jb-filters [data-cascade="2"] .av-cascade-list');
  const groups = (state.catalog && state.catalog.groups) || [];
  const groupObj = groups.find((g) => g.name === state.listGroup);
  const currentTag = state.jmode === "tag" ? state.listSlug : "";
  if (list) {
    // innerHTML: cascade options go through html`` / opt()
    list.innerHTML = !state.listGroup
      ? html`<p class="av-dd-hint">请选择一级</p>`
      : opt("data-tag", "", "全部", !currentTag) +
        (groupObj && groupObj.tags ? groupObj.tags : [])
          .map((t) => opt("data-tag", t.slug, t.name, t.slug === currentTag))
          .join("");
  }
  document.querySelectorAll('#jb-filters [data-cascade="1"] [data-group]').forEach((btn) => {
    btn.classList.toggle("on", (btn.dataset.group || "") === (state.listGroup || ""));
  });
  const val = qs('#jb-filters [data-dd="tag"] .av-dd-value');
  if (val) {
    val.textContent = currentTag ? findListName(currentTag) || currentTag : state.listGroup || "全部";
  }
}

export function closeFilterMenus(except) {
  document.querySelectorAll("#jb-filters .av-dd.open").forEach((el) => {
    if (el === except) return;
    el.classList.remove("open");
    const menu = qs(".av-dd-menu", el);
    if (menu) menu.hidden = true;
    const btn = qs(".av-dd-btn", el);
    if (btn) btn.setAttribute("aria-expanded", "false");
  });
}

export function toggleFilterMenu(box) {
  const open = box && !box.classList.contains("open");
  closeFilterMenus(box);
  if (!box) return;
  box.classList.toggle("open", open);
  const menu = qs(".av-dd-menu", box);
  if (menu) menu.hidden = !open;
  const btn = qs(".av-dd-btn", box);
  if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
}

export function renderFilterBar() {
  const left = qs("#jb-filter-left");
  const right = qs("#jb-filter-right");
  if (!left || !right) return;
  const cat = state.catalog || {};
  const isHot = ["hot", "week", "month", "all"].includes(state.jmode);
  const isLatest = state.jmode === "latest";
  const isType = ["type", "cat", "tag"].includes(state.jmode);
  const isModel = state.jmode === "model";
  let leftHtml = "";
  let rightHtml = "";
  if (isHot) {
    const sorts = cat.hot_sorts && cat.hot_sorts.length ? cat.hot_sorts : HOT_SORTS;
    const current = sorts.find((s) => s.id === state.jmode) || sorts[0];
    rightHtml = ddHtml("sort", "排序", current.name, sorts.map((s) => opt("data-sort", s.id, s.name, s.id === state.jmode)).join(""));
  } else if (isLatest) {
    const years = cat.years && cat.years.length ? cat.years : Array.from({ length: 27 }, (_, i) => String(2026 - i));
    const months = cat.months && cat.months.length ? cat.months : Array.from({ length: 12 }, (_, i) => ({ id: String(i + 1), name: `${i + 1}月` }));
    leftHtml =
      ddHtml(
        "year",
        "年份",
        state.listYear || "全部",
        opt("data-year", "", "全部", !state.listYear) + years.map((y) => opt("data-year", String(y), String(y), String(y) === state.listYear)).join("")
      ) +
      ddHtml(
        "month",
        "月份",
        state.listMonth ? `${state.listMonth}月` : "全部",
        opt("data-month", "", "全部", !state.listMonth) +
          months
            .map((m) => {
              const id = m.id || String(m);
              return opt("data-month", id, m.name || `${id}月`, id === state.listMonth);
            })
            .join("")
      );
  } else if (isModel) {
    const current = MODEL_SORTS.find((s) => s.id === state.listSort) || MODEL_SORTS[0];
    rightHtml = ddHtml("sort", "排序", current.name, MODEL_SORTS.map((s) => opt("data-sort", s.id, s.name, s.id === state.listSort)).join(""));
  } else if (isType) {
    if (!state.catalog) return;
    const cats = cat.categories || [];
    const groups = cat.groups || [];
    if (state.jmode === "tag" && state.listSlug && !state.listGroup) state.listGroup = findTagGroup(state.listSlug);
    const catVal = state.jmode === "cat" ? findListName(state.listSlug) || state.listSlug || "全部" : "全部";
    const currentTag = state.jmode === "tag" ? state.listSlug : "";
    const shownGroup = state.listGroup || (groups[0] && groups[0].name) || "";
    const tagVal = currentTag ? findListName(currentTag) || currentTag : state.listGroup || "全部";
    const catMenu =
      opt("data-cat", "", "全部", state.jmode !== "cat") +
      cats.map((c) => opt("data-cat", c.slug, c.name, state.jmode === "cat" && c.slug === state.listSlug)).join("");
    leftHtml = ddHtml("cat", "分类", catVal, catMenu) + ddHtml("tag", "标签", tagVal, cascadeHtml(groups, shownGroup, currentTag), true);
  }
  // innerHTML: filter chrome is built with html``
  left.innerHTML = leftHtml;
  right.innerHTML = rightHtml;
}

function refreshOpenCascade() {
  const menu = qs('#jb-filters [data-dd="tag"] .av-dd-menu');
  const groups = (state.catalog && state.catalog.groups) || [];
  if (!menu || !groups.length) {
    renderFilterBar();
    return;
  }
  const currentTag = state.jmode === "tag" ? state.listSlug : "";
  const shownGroup = state.listGroup || groups[0].name || "";
  if (!state.listGroup && shownGroup) state.listGroup = shownGroup;
  // innerHTML: cascade rebuilt with html`` / opt()
  menu.innerHTML = cascadeHtml(groups, shownGroup, currentTag);
}

function paintFiltersIfIdle() {
  const open = document.querySelector("#jb-filters .av-dd.open");
  if (open && open.getAttribute("data-dd") === "tag") {
    refreshOpenCascade();
    return;
  }
  if (open) return;
  renderFilterBar();
}

export async function loadCatalog() {
  if (state.catalog) {
    paintFiltersIfIdle();
    return state.catalog;
  }
  try {
    state.catalog = await get("/api/jable/catalog");
    paintFiltersIfIdle();
    return state.catalog;
  } catch {
    state.catalog = { hot_sorts: HOT_SORTS, years: Array.from({ length: 27 }, (_, i) => 2026 - i), months: [], categories: [], groups: [] };
    paintFiltersIfIdle();
    return state.catalog;
  }
}
