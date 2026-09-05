# openDownload 2.1 设计创新规格（视觉 UI · 组件 · 交互 · 信息架构）

> 状态：规划稿，作为 WP6a / WP6b 的实施依据。基于 2.0（`redesign-v2.md`）已落地的架构，不推翻，只在四个维度上做「有依据的创新」。所有创新必须同时满足：零构建原生 ES 模块、可访问性不退步、性能预算（§7）不超、`prefers-reduced-motion` 下退化为无动效。

## 0. 现状读感（2026-09-05 实测截图）

| 页面 | 观察 | 问题定性 |
| --- | --- | --- |
| 首页 | 每次访问都是营销式 hero（大标题 + 三步说明），占据首屏黄金位置；「最近任务 / 最近收入」被挤到下半区 | 静态 IA，不随用户状态变化 |
| Jable 列表 | 1920px 宽下 6 列小卡，封面约 150px，标题 12px；页头「Jable / 精选热门最新分类 / 热门 38,933」三层标题堆叠 | 密度与视口脱钩；层级冗余 |
| Jable 详情分栏 | 分栏可用，但列表中被选中的卡**没有选中态**；面板是平板色块，与封面内容无关 | 状态反馈缺失；视觉与内容脱节 |
| 馆藏 | 两张卡漂在空白页；点卡直接播放，没有信息面板 | 与 Jable 的「看详情」心智不一致 |
| 收藏单抽屉 | 功能完整（识别 → 解析 → 预览 → 保存），但右侧抽屉拥挤、hero 缩略图与条目缩略图重复 | 组件密度失衡 |
| 任务页 | 三个 0 的统计卡占了整行；历史区只有一行 | 「统计卡」是后台管理系统的套路，对单人本地工具无信息量 |
| 整体 | 中性灰蓝 + 橙色点缀的通用暗色后台风格，与「媒体」无关 | 缺乏产品性格 |

结论：2.0 完成了「正确」，2.1 要做「独特而克制」——所有个性都从**内容（封面/进度/来源）**生长出来，而不是装饰。

---

## 1. 设计立意：内容即界面（Content-lit UI）

1. **封面是光源**：详情面板、播放页、首页「最近收入」用封面主色做环境光（ambient），铬（chrome）保持中性；亮度由内容决定，界面像影院。
2. **番号是标识符**：Jable 的 code 用等宽小字号大写呈现，成为可扫读的锚点；数字（次数、体积、时长、页码）一律 `tabular-nums`。
3. **来源有体温**：Jable 紫 / YouTube 红 / 抖音墨三种色相贯穿导航、卡片边、任务行、托盘 chip、筛选 chip，取代目前只有一个小圆点的做法。
4. **浏览与收集不分家**：一个跨页面、跨会话的「待收藏架（Shelf）」代替一次性的「批量选择」；卡片本身显示「已在馆藏 / 排队中 / 下载 42%」。
5. **键盘与拖放是一等公民**：`Ctrl+K` 命令面板、`?` 快捷键表、任意位置粘贴/拖入链接即解析。

---

## 2. 信息架构 2.1

### 2.1 对象模型

```
来源(Source) ──浏览──▶ 条目(Item) ──加入──▶ 待收藏架(Shelf) ──保存──▶ 任务(Task) ──完成──▶ 馆藏(LibraryFile)
                          │                                                          ▲
                          └────────────── 已在馆藏？（LibraryIndex 反查）────────────┘
```

- **Shelf**（新）：客户端持久（`localStorage: od-shelf-v1`，≤ 200 条，去重键 `site:id`），条目 `{ key, site, id, title, cover, meta, addedAt }`。Jable 卡片、收藏单预览条目、命令面板结果都可「加入待收藏」。保存时按 site 分流：Jable → 逐个 `POST /api/jable/save`（沿用现有语义）；YouTube/抖音 → 重开收藏单并预勾选。
- **LibraryIndex**（新，纯客户端）：`GET /api/library?limit=200` 每 60s 或任务完成事件后刷新一次，导出 `inLibrary(site, id)`（Jable 用文件名前缀匹配番号，大小写不敏感）。用于卡片「已在馆藏」角标与收藏单预览的提示。
- **Inspector**（统一）：Jable 详情、馆藏文件详情、任务结果详情共用一个分栏检视器组件（§4.1）。点任何媒体 = 打开检视器，这是全站唯一的「看详情」心智。

### 2.2 全局壳

- 顶栏：面包屑 · 全局输入（右侧 `Ctrl K` 键帽提示，点击或快捷键打开命令面板；直接输入 + Enter 仍是「解析」）· 服务状态（悬停显示 `本地服务 · v2.0.0 · :8765`）。
- 侧栏：当前项左侧 3px 来源色条；`折叠` 状态持久；≥1800px 时侧栏 260px。
- **移动端（<768px）改为底部 Tab 栏**：首页 / Jable / 馆藏 / 任务 / 更多（更多 → 设置、主题、YouTube、抖音）。Dock 悬浮在 Tab 栏之上。
- **Dock**（替代任务托盘，§4.2）：右下角胶囊，左段进度环 + 「N 进行中」，右段「待收藏 M」；展开为带三个标签页的面板。

### 2.3 自适应首页

| 状态 | 首屏内容 |
| --- | --- |
| 首次访问（`od-visits` < 2）或设置里开启「显示引导」 | 现有 hero + 三步说明 + 来源卡 |
| 回访 | 紧凑输入行（占位「粘贴链接、番号或输入命令 · Ctrl K」）→ **继续**（上次 Jable 列表位置：如「热门 · 今日观看 · 第 3 页」；上次馆藏视图）→ **进行中**（有活动任务时才出现，行内进度）→ **最近收入**（封面瓦片 + 环境光）→ 来源快捷行 |

### 2.4 路由不变

沿用 2.0 路由表；新增查询参数：`#/library?p=<rel>`（打开馆藏检视器）、`#/tasks?f=active|done|error`（筛选）。

---

## 3. 视觉系统 2.1（在 `tokens.css` 上**追加**，不重命名既有变量）

### 3.1 新增 Token

```css
:root {
  /* 层级表面 */
  --surface-3: #ffffff;                       /* popover / palette；暗色 #222831 */
  --surface-glass: rgba(255,255,255,.72);     /* 顶栏/Dock 玻璃；暗色 rgba(22,26,32,.72) */
  --overlay: rgba(16,20,24,.45);              /* 移动端遮罩；暗色 rgba(0,0,0,.6) */
  --line-hover: color-mix(in oklab, var(--accent) 35%, var(--border));

  /* 来源色相（hsl 分量，便于派生 soft/line） */
  --hue-jable: 258; --hue-youtube: 4; --hue-douyin: 212;
  --brand-jable-soft: hsl(var(--hue-jable) 70% 55% / .14);
  --brand-youtube-soft: hsl(var(--hue-youtube) 75% 55% / .14);
  --brand-douyin-soft: hsl(var(--hue-douyin) 20% 50% / .14);

  /* 环境光：由 JS 通过 style.setProperty('--ambient', 'hsl(...)') 注入到检视器/瓦片元素 */
  --ambient: transparent;
  --ambient-bg: color-mix(in oklab, var(--ambient) 18%, var(--surface));
  --ambient-line: color-mix(in oklab, var(--ambient) 40%, var(--border));

  /* 字体 */
  --font-mono: ui-monospace, "Cascadia Code", "JetBrains Mono", Consolas, monospace;
  --fs-display: clamp(28px, 1.6vw + 14px, 40px);
  --fs-title: clamp(20px, .6vw + 14px, 26px);
  --lh-tight: 1.2; --lh: 1.5;

  /* 圆角（略放大，柔化） */
  --r-card: 12px; --r-panel: 16px;

  /* 动效 */
  --ease-out: cubic-bezier(.16, 1, .3, 1);
  --ease-spring: cubic-bezier(.34, 1.4, .64, 1);
  --dur-enter: 220ms; --dur-exit: 160ms;

  /* 密度（默认舒适） */
  --card-min: 208px; --card-gap: 18px;
}
[data-density="compact"] { --card-min: 168px; --card-gap: 12px; --ctrl-h: 32px; }
[data-theme="light"] { --bg: #f7f6f3; }        /* 暖纸色，替代冷灰 */
@media (prefers-reduced-motion: reduce) { :root { --dur-fast: 0ms; --dur: 0ms; --dur-slow: 0ms; --dur-enter: 0ms; --dur-exit: 0ms; } }
```

### 3.2 排版规则

- 页面标题 `--fs-display`，`letter-spacing: -0.01em`，`line-height: var(--lh-tight)`；页头只保留**一层**标题 + 一行说明（Jable 页去掉「Jable」大标题，直接以当前视图名为 H1：如「热门」，说明行「38,933 部 · 今日观看」）。
- 番号：`.code { font: 600 12px/1 var(--font-mono); letter-spacing: .04em; text-transform: uppercase; color: var(--ink-2); }`。
- 所有数字容器 `font-variant-numeric: tabular-nums`。
- 正文最小 13px；卡片标题 14px 两行截断（`-webkit-line-clamp: 2`）。

### 3.3 表面与光

- 顶栏、Dock、移动端 Tab 栏：`background: var(--surface-glass); backdrop-filter: saturate(1.2) blur(12px)`；不支持时退化为 `--surface`。
- 卡片 hover：边框色 `--line-hover` + 「聚光」高光：容器监听 `pointermove`（rAF 节流，单监听）写入 `--mx/--my`，卡片 `::before` 为 `radial-gradient(240px circle at var(--mx) var(--my), rgba(255,255,255,.08), transparent 60%)`；`prefers-reduced-motion` 与 `pointer: coarse` 下关闭。
- 检视器、播放页、首页最近收入瓦片：`background: var(--ambient-bg); border-color: var(--ambient-line)`。
- 来源色条：`.src-jable { --src: var(--brand-jable); --src-soft: var(--brand-jable-soft) }` 等三类，用于 `border-left: 3px solid var(--src)` 与 chip 背景。

### 3.4 网格

`grid-template-columns: repeat(auto-fill, minmax(var(--card-min), 1fr)); gap: var(--card-gap)`；1920px 舒适密度下约 6–7 列、每列 ≥ 208px；紧凑密度 8–9 列。密度由设置或列表工具条分段控件切换（`document.documentElement.dataset.density`，持久 `od-density`）。

### 3.5 图标

沿用 `icons.js` 20px 描边；新增：`command`（⌘）、`shelf`（书架）、`ring`（进度环由 SVG 组件生成，不是图标）、`drop`（拖入）、`keyboard`。

---

## 4. 组件 2.1（`web/js/ui/`，纯函数渲染 + 容器委托；新增文件均 ≤ 300 行）

### 4.1 `inspector.js` — 统一分栏检视器

```js
createInspector({ host, storageKey, onClose, onPrev, onNext }) → {
  open({ header, body, ambient, hasPrev, hasNext }), update({ body }), setAmbient(color), close(), isOpen(), el
}
```
- 结构：`aside.inspector[role=region][aria-label=详情]` → 工具条（标题 slot · 上一条/下一条 · 放大 · 关闭）→ `body` slot。分隔条 `div.inspector-handle[role=separator][aria-orientation=vertical][aria-valuenow]`，支持指针拖拽与 `←/→` 键盘调宽（步长 24px，持久到 `storageKey`）。放大 = 面板占满内容区。
- 键盘：焦点在检视器内且不在输入控件时，`Esc` 关闭并回焦到打开它的元素；`ArrowLeft/ArrowRight`（或 `J/K`）调用 `onPrev/onNext`。
- `<1024px`：上下堆叠；`<768px`：改为全屏 sheet（复用 `drawer.js` 的 sheet 行为）。
- 打开/切换条目时若 `document.startViewTransition` 存在则包裹调用（`core/motion.js#withTransition`），否则直接更新。
- 从现有 `jable/inspect.js` 抽取拖拽/键盘/放大逻辑到此组件；`jable/inspect.js` 只负责 Jable 的 header/body 内容与播放器。

### 4.2 `dock.js` — 任务 + 待收藏 Dock（替代 `task-tray`）

- 折叠态：`button.dock-pill[aria-expanded]`，左段 `ProgressRing(avgPercent)` + 「N 进行中」；右段「待收藏 M」；任一为 0 则隐藏对应段；两者都为 0 时整个 Dock 隐藏。
- 展开态：面板 `role=dialog aria-label=Dock`，`Segmented` 三个标签：**待收藏**（Shelf 列表：封面 40×60/56×32、标题、来源 chip、移除；底部「全部保存 (M)」「清空」）/ **进行中**（TaskRow 紧凑版，取消）/ **最近完成**（最多 5 条，打开目录 / 定位文件）。
- 动效：展开用 `--ease-out --dur-enter`，从胶囊位置放大；`Esc` 关闭；焦点管理与 `drawer.js` 一致。
- 文档标题联动：有活动下载时 `document.title = "↓ 42% · openDownload"`，完成后恢复。

### 4.3 `palette.js` — 命令面板（懒加载）

- 触发：`Ctrl/⌘+K`、点击全局输入右侧键帽、移动端「更多」里的「搜索与命令」。
- 结构：`dialog.palette[role=dialog aria-modal]` → 输入框（`role=combobox aria-expanded aria-controls`）→ `ul[role=listbox]` 分组：
  1. **识别**：对输入调用共享 `detect(query)`（从 `features/collect.js` 抽到 `features/detect.js`），如「解析为 YouTube 视频」「解析为 Jable 番号 LULU-445」「打开 Jable 详情 LULU-445」。
  2. **跳转**：路由表（首页 / Jable 热门 / 最新 / 分类 / YouTube / 抖音 / 馆藏 / 任务 / 设置），模糊匹配中文与拼音首字母（内置小表即可，不引库）。
  3. **最近**：`od-recent-queries`（≤ 10，收藏单成功解析后写入）。
  4. **操作**：切换主题、切换密度、打开馆藏目录、显示快捷键。
- 键盘：`↑/↓` 移动 `aria-activedescendant`，`Enter` 执行，`Esc` 关闭并回焦触发元素；`Tab` 循环在面板内。
- 首屏不加载：`main.js` 在快捷键/点击时 `import("./ui/palette.js")`。

### 4.4 其它新组件

| 文件 | API | 要点 |
| --- | --- | --- |
| `segmented.js` | `Segmented({ name, value, options:[{value,label,icon}], size })` | `div[role=radiogroup]` + `button[role=radio][aria-checked]`；`data-seg=name data-value`；`←/→` 切换 |
| `filter-bar.js` | `FilterBar({ groups:[{key,label,options,value,multi}], applied:[{key,value,label}], moreLabel })` | 主行显示前 N 个 chip，溢出进「更多筛选」popover（`data-dropdown` 复用 `dropdown.js`）；已应用筛选以可移除 chip 汇总（`data-filter-remove="key:value"`）；`Esc` 关 popover |
| `progress-ring.js` | `ProgressRing({ value, size=20, stroke=2.5, label })` | SVG `circle` 两层，`stroke-dasharray` 动画 `--dur`；`role=img aria-label` |
| `kbd.js` | `Kbd("Ctrl","K")` | `<kbd>` 组合，mono 字体，`aria-hidden` 视觉提示 |
| `toast.js`（升级） | `toast(msg, { type, action, undo, group, duration })` | 同 `group` 2s 内合并为「已加入 N 个任务」；`undo` 显示「撤销」按钮，5s 后执行提交回调；容器 `aria-live=polite`；最多同时 3 条 |
| `media-card.js`（升级） | `MediaCard(item, { selected, inLibrary, progress, quickActions, index })` | 状态类 `is-selected / is-in-library / is-queued / is-downloading`；封面底部 2px 进度条；角标「已在馆藏」；hover/focus 显示快速操作（★ 加入待收藏 · 详情）；`tabindex` 由 roving 管理，`data-index` |
| `bottom-tabs.js` | `BottomTabs({ items, current })` | 移动端 `nav[aria-label=主导航]`；含 Dock 上移 safe-area |
| `sheet 升级（drawer.js）` | `openDrawer({ snap: ["peek","half","full"] })` | 移动端拖拽把手在三档间吸附（`touch-action: none` 只在把手上）；桌面无变化 |

### 4.5 核心工具

| 文件 | 内容 |
| --- | --- |
| `core/motion.js` | `withTransition(fn)`（View Transitions 包裹，缺失或 reduced-motion 时直接执行）、`reducedMotion()`、`installSpotlight(container)` |
| `core/color.js` | `dominantColor(imgEl) → "hsl(h s% l%)"|null`：16×16 canvas 采样，跳过极暗/极亮像素，饱和度下限 .25，亮度夹到 [.35,.6]；`Map` 缓存 per `src`；异常返回 `null` |
| `core/keys.js` | `registerShortcuts({ "ctrl+k": fn, "/": fn, "?": fn, "g h": fn, ... }, { scope })`；输入控件聚焦时只响应 `Esc`；和弦 1s 超时；返回卸载函数 |
| `features/shelf.js` | Shelf store（§2.1） |
| `features/library-index.js` | LibraryIndex（§2.1） |
| `features/detect.js` | 从 `collect.js` 抽出的纯函数 `detect(query) → { site, kind, id?, label }` |
| `features/dropzone.js` | 全页 `dragenter/dragover/drop`（读取 `text/uri-list` 或 `text/plain`）与 `paste`（焦点不在输入控件时）→ `collect.open(query)`；拖入时显示虚线全屏覆盖「释放以解析」 |

---

## 5. 交互 2.1

### 5.1 全局快捷键（`?` 打开速查表对话框）

| 键 | 行为 |
| --- | --- |
| `Ctrl/⌘ K` | 命令面板 |
| `/` | 聚焦全局输入 |
| `?` | 快捷键速查 |
| `T` | 切换主题 |
| `G H` / `G J` / `G L` / `G T` | 去首页 / Jable / 馆藏 / 任务 |
| `[` / `]` | 列表上一页 / 下一页 |
| `↑↓←→` | 网格内移动焦点（按实际列数计算） |
| `Enter` | 打开检视器 |
| `S` | 焦点卡片加入 / 移出待收藏 |
| `D` | 焦点卡片直接保存（Jable）或打开收藏单 |
| `Esc` | 关闭最上层（面板 / 检视器 / Dock / 抽屉） |
| 检视器内 `J/K` 或 `←/→` | 上一条 / 下一条 |
| 播放器内 `Space` `←/→` `F` `M` | 播放暂停 / ±5s / 全屏 / 静音 |

### 5.2 浏览 ⇄ 收集

- 卡片 hover / focus 显示两枚快速操作；点 ★ 立即加入待收藏（卡片角标 + Dock 计数 +1，`--ease-spring` 微弹）。
- 「批量选择」模式改名「加入待收藏」：勾选即入架，跨页、跨刷新保留；Dock 里「全部保存」。
- 卡片实时反映任务：从 `tasks` store 按 `site:id` 查到活动任务 → 进度条；完成后 LibraryIndex 刷新 → 「已在馆藏」。

### 5.3 乐观更新与撤销

- 删除任务记录、清空历史、移出待收藏：立即从界面消失 + 「撤销」toast（5s）；超时才真正发 `DELETE`。

### 5.4 检视器灯箱式导航

- 打开检视器后，列表中对应卡片 `is-selected`（来源色边框 + 轻微上浮），并 `scrollIntoView({ block: "nearest" })`；`←/→` 切换相邻条目，URL `?p=` 同步 `replace`。

### 5.5 任意处粘贴 / 拖入

- 焦点不在输入控件时 `Ctrl+V` 粘贴文本 → `detect()` 命中则打开收藏单；拖入链接同理。未命中给一条中性 toast「没识别出链接或番号」。

### 5.6 移动端

- 底部 Tab 栏；收藏单三档吸附；卡片长按 = 快速操作菜单（`dropdown.js`）；Dock 在 Tab 栏之上。

### 5.7 动效清单

| 场景 | 动效 |
| --- | --- |
| 打开检视器 | View Transition（封面从卡片到面板的位置/尺寸过渡，`view-transition-name` 按 `code` 动态设置） |
| Dock 展开 | 从胶囊放大 `--dur-enter --ease-out` |
| 加入待收藏 | 角标 `scale(.6→1)` `--ease-spring` 220ms |
| 进度环 | `stroke-dashoffset` 过渡 `--dur` |
| 卡片进入 | 无（保持 `content-visibility: auto`，不做入场瀑布） |
| Toast | 上滑淡入 160ms，淡出 120ms |

全部受 `prefers-reduced-motion` 约束归零。

---

## 6. 页面改动清单

| 页面 | 改动 |
| --- | --- |
| 壳 | 键帽提示、Dock、移动端 Tab 栏、侧栏来源色条、服务状态 tooltip |
| 首页 | 自适应（§2.3）；最近收入瓦片带环境光；「继续」卡 |
| Jable 列表 | 单层标题；`FilterBar`（分类/标签级联 + 已应用 chip）；`Segmented`（排序、密度）；卡片 v2 状态；roving 焦点 + 方向键；`[`/`]`；批量 → 待收藏架 |
| Jable 详情 | 采用 `inspector.js`；环境光；选中态；`←/→` 相邻导航 |
| 播放页 | 环境光背景；播放器快捷键 |
| 馆藏 | 点卡打开检视器（播放器 + 名称/体积/时间/来源/相对路径 + 定位文件 / 复制路径）；`Segmented` 排序与密度；`FilterBar` 站点 |
| 任务 | 去掉三张统计卡 → `Segmented` 筛选（全部/进行中/已完成/失败）+ 一行摘要文字；行内 `ProgressRing`、速度/ETA、来源色条；清空历史带撤销 |
| 设置 | 新增「外观」（主题：跟随系统/浅/深；密度；动效：跟随系统/减少；悬停预览开关，默认关；显示引导）与「快捷键」表 |
| 收藏单 | 使用共享 `detect()`；预览条目显示「已在馆藏」；移动端三档吸附；去掉与条目重复的 hero 缩略图（保留标题行 + 来源 chip） |

---

## 7. 性能预算（2.1 修订）

| 指标 | 预算 | 说明 |
| --- | --- | --- |
| 首屏 DCL / FCP（本地，缓存暖） | < 300ms / < 600ms | 与 2.0 相同 |
| 首批 JS（`modulepreload` 平铺） | ≤ 60KB 解码 | 2.0 实测 46KB；palette / inspector / dock 面板体 / jable 全部懒加载 |
| JS 总量（不含 hls.js） | ≤ 320KB | 2.0 实测 232KB（Jable 模块 118KB），原 160KB 预算已不现实，改为按路由懒加载约束：**任一路由首次进入新增 JS ≤ 130KB** |
| 外部域请求 | 0 | 不变 |
| 空闲 30s 请求 | 0 | LibraryIndex 60s 刷新只在页面可见且有卡片依赖它时进行（`document.visibilityState`） |
| 主色提取 | 单张 ≤ 2ms（16×16 canvas），结果缓存 | 仅对可见封面执行 |
| 聚光效果 | 单个 `pointermove` 监听 + rAF | 无布局抖动（只改自定义属性） |

---

## 8. 可访问性守则（新增项）

- 所有新组件有明确 `role`/`aria-*`；命令面板遵循 WAI-ARIA combobox + listbox 模式。
- Roving tabindex 网格：`Tab` 进入网格只落一个焦点，方向键内部移动；`Home/End` 首尾。
- 环境光背景与文字对比 ≥ 4.5:1：`--ambient-bg` 只混 18%，且文字用 `--ink`；实现后用 `ui_a11y.py` 抽样校验对比度。
- 快速操作按钮在触屏上常显（`pointer: coarse`），不依赖 hover。

---

## 9. 工作包

| WP | 范围（文件所有权） | 交付 |
| --- | --- | --- |
| **WP6a 基础与壳** | `web/css/tokens.css base.css shell.css components.css views/{home,library,tasks,settings}.css`；`web/js/main.js core/* ui/*（除 media-card 由 6a 升级）features/{tasks,shelf,library-index,detect,dropzone}.js views/{home,source,library,tasks,settings}.js`；`web/index.html`；相关 `tests/ui_*.py` | §3 全部 token；§4 全部组件；§5.1/5.3/5.5/5.6 壳级交互；§6 首页/馆藏/任务/设置/壳 |
| **WP6b Jable 与收藏单** | `web/js/jable/*`、`web/js/features/collect*.js`、`web/css/views/{jable,collect}.css`；相关 `tests/ui_jable_*.py`、`ui_collect.py` | §6 Jable 列表/详情/播放页/收藏单；采用 6a 的 inspector / shelf / library-index / detect / segmented / filter-bar / media-card |

顺序：6a → 6b（6b 依赖 6a 的组件 API）。每个 WP 结束条件：`python -m pytest tests/test_*.py -q` 与 `python tests/run_ui.py` 全绿（允许修改自己范围内的测试并新增 `ui_palette.py`、`ui_shelf.py`、`ui_keys.py`、`ui_inspector.py`）；`ui_perf.py` 满足 §7；三视口截图更新到 `tests/_out/`。

---

## 10. 验收清单（2.1）

- [ ] 回访首页为紧凑态并出现「继续」卡；首次访问显示引导。
- [ ] `Ctrl+K` 打开命令面板：能识别 YouTube 链接 / Jable 番号、跳转路由、切换主题；`Esc` 回焦。
- [ ] 任意处粘贴 YouTube 链接打开收藏单；拖入链接同理。
- [ ] Jable 卡片：hover/focus 显示快速操作；★ 入架后 Dock 计数变化并跨刷新保留；已在馆藏的番号显示角标；下载中卡片显示进度条。
- [ ] 检视器：Jable 与馆藏共用；拖拽/键盘调宽持久；`←/→` 切换相邻条目且列表选中态同步；环境光随封面变化。
- [ ] 键盘：`/`、`?`、`T`、`G H/J/L/T`、`[`/`]`、方向键网格导航、`S`、`D` 全部生效；输入框聚焦时不误触。
- [ ] 删除任务 / 清空历史有 5s 撤销，撤销后服务端数据未变。
- [ ] 移动端 390×844：底部 Tab 栏、Dock 不遮挡、收藏单三档吸附、卡片长按菜单。
- [ ] `prefers-reduced-motion: reduce` 下无过渡动画；`pointer: coarse` 下快速操作常显。
- [ ] §7 预算全部达标并写入 `redesign-v2.md` §13 验证记录。
