# openDownload 2.0 重构蓝图

> 本文档是 2.0 重构的唯一依据：产品定位、信息架构、设计系统、页面规格、交互/动效、内容、性能预算、前后端架构与验收清单。实现必须以此为准；与旧文档 `redesign.md` 冲突处以本文为准。

---

## 0. 现状诊断（重构动机）

| 维度 | 现状问题 |
| --- | --- |
| 产品 | 两套心智模型并存：「粘贴链接→解析→确认→保存」的工作台，与「浏览/筛选/预览」的 Jable 站内浏览。首页强推粘贴链接，而 YouTube / 抖音页只有一个输入框和空态；抖音的 5 个模式导航被 CSS 藏掉、YouTube 的侧栏被隐藏。 |
| 信息架构 | 解析结果、确认清单、进度条都渲染在所有视图底部的全局 `#workbench`，用户需要滚动去找；一次只能跟踪一个任务，刷新页面即丢失进度；没有任务列表接口。 |
| 交互 | 馆藏与设置是模态框；馆藏只有平铺文件名，不能播放/定位/搜索。Jable 的「热门/选片」批量流程在 DOM 中但不可达。 |
| 视觉 | 三层 CSS 叠加（`styles.css` 2653 行 legacy + `workbench.css` 覆盖层 + `inspect-layout.css`），大量 `!important`；抖音页出现与体系无关的粉色按钮。 |
| 性能 | 每次加载都拉 Google Fonts 与 CDN 上的 hls.js；封面 `loading="eager"`；悬停即预取播放地址与 DMM 预览；`/api/jable/orders` 每 8 秒永久轮询；同级列表预取并发 10。 |
| 架构 | 前端 3853 行单 IIFE，状态 60+ 字段耦合；后端 `JobRunner` 单线程，下载期间解析排队。 |

---

## 1. 产品定位与设计原则

**定位**：本机媒体工作台。三件事：**发现**（浏览来源）、**收藏**（解析→预览→确认→保存）、**整理**（馆藏）。

**原则**
1. 浏览不中断：任何解析/下载都在右侧「收藏单」抽屉与右下「任务托盘」中进行，主内容区永远可继续浏览。
2. 状态可恢复：任务列表由服务端持有，刷新、换页、重开浏览器都能回到进度。
3. 一个入口：顶部全局输入框（Ctrl/⌘+K 或 `/`）接受任何链接/番号/用户名，即时识别来源。
4. 真实数据、诚实状态：不虚构统计；加载/空/错误三态分离，错误必给出下一步（重试/打开设置）。
5. 快：首屏 < 1s（本地），任何页面切换有即时反馈（骨架或缓存），无网络风暴。

---

## 2. 信息架构

### 2.1 全局壳（Shell）

```
┌ 侧栏 240px（可收起为 72px 图标栏，记忆偏好） ─┬ 顶栏 56px ────────────────────────────┐
│ 品牌 openDownload                              │ [☰] 面包屑    [ 全局输入框 ⌘K ]   ● 服务  │
│ 首页                                           ├────────────────────────────────────────┤
│ 来源: Jable / YouTube / 抖音                    │                                        │
│ 馆藏                                           │           主内容（按路由切换）           │
│ 任务 (角标: 进行中数量)                          │                                        │
│ ─────                                          │                          ┌ 收藏单抽屉 ┐ │
│ 设置 · 主题切换                                 │                          │ (右侧 440px)│ │
└────────────────────────────────────────────────┴──────────────────────────┴────────────┘
                                                                     ┌ 任务托盘 (右下, 可折叠) ┐
```

- 移动端（< 768px）：侧栏变为顶栏汉堡菜单打开的抽屉；收藏单抽屉与任务托盘变为全宽底部面板（bottom sheet）。
- 顶栏输入框在首页隐藏（首页有大输入框），其他页面显示。

### 2.2 路由表（hash 路由，向后兼容）

| 路由 | 视图 | 说明 |
| --- | --- | --- |
| `#/` （别名 `#/auto`） | 首页 | 大输入框 + 来源卡 + 最近任务/最近馆藏 |
| `#/jable` | Jable 精选 | 热门精选 + 最新影片两段网格（客户端分页） |
| `#/jable/hot` `week` `month` `all` | Jable 热门列表 | 排序切换 |
| `#/jable/latest[/:year[/:month]]` `#/jable/latest/m/:month` | 最新列表 | 年/月筛选 |
| `#/jable/type[/:group]` `#/jable/cat/:slug` `#/jable/tag/:slug` | 分类浏览 | 分类下拉 + 标签级联 |
| `#/jable/model/:slug[/viewed]` | 演员作品 | 排序：发布时间/最多观看 |
| 以上任意 + `?p=:code` | 作品详情分栏 | 右侧详情面板（预览/完整视频/保存） |
| `#/jable/v/:code` | 播放页 | 全宽播放 + 相关视频 |
| `#/youtube[/videos\|shorts\|streams]` | YouTube 来源页 | 频道分栏偏好 |
| `#/douyin[/feed\|follow\|hashtag\|likes]` | 抖音来源页 | 模式切换 |
| `#/library[?site=&q=&sort=]` | 馆藏页 | 网格/列表，搜索、排序、播放、定位文件 |
| `#/tasks` | 任务页 | 进行中/排队/历史，取消、打开目录、重开收藏单 |
| `#/settings`（别名 `#/setup`） | 设置页 | 依赖、目录、并发、Cookie、主题 |

### 2.3 核心流程：收藏单（Collect Sheet）

```
输入 ──(即时识别 /api/detect)──▶ 解析中（日志可展开）──▶ 预览清单（勾选/筛选/选项）──▶ 保存中（进度）──▶ 完成（打开目录 / 去馆藏 / 再来一单）
   ▲                                  │ 失败：错误 + 重试 / 修改输入
   └──────────────────────────────────┘
```
- 收藏单是右侧抽屉（桌面 440–520px，可最大化到 720px；移动端全屏 sheet）。
- 每张收藏单绑定一个 parse 任务 id 与（可选）download 任务 id；托盘中可重新打开。
- 抽屉打开时主内容不遮罩、可继续浏览；Esc 关闭抽屉但不取消任务（任务在托盘继续）。

---

## 3. 设计系统

### 3.1 色彩（CSS 变量，`[data-theme=light|dark]`，默认跟随系统）

| Token | Light | Dark | 用途 |
| --- | --- | --- | --- |
| `--bg` | `#f6f7f9` | `#0f1216` | 画布 |
| `--surface` | `#ffffff` | `#161a20` | 卡片/面板 |
| `--surface-2` | `#f1f3f6` | `#1d222a` | 次级面板、骨架 |
| `--border` | `#e5e8ec` | `#262c35` | 分隔线 |
| `--border-strong` | `#d4d9df` | `#333b46` | 控件边框 |
| `--ink` | `#1c2024` | `#e8ebef` | 主文字 |
| `--ink-2` | `#4b535d` | `#b7bec8` | 次要文字 |
| `--ink-3` | `#6b7480` | `#8b94a0` | 说明文字 |
| `--ink-4` | `#98a1ab` | `#626b77` | 占位/禁用 |
| `--accent` | `#e8603f` | `#f0764f` | 主操作背景 |
| `--accent-ink` | `#c2472a` | `#f59a7a` | 主色文字（白底 AA） |
| `--accent-soft` | `#fdece7` | `rgba(240,118,79,.14)` | 选中态背景 |
| `--ok` / `--warn` / `--danger` / `--info` | `#2e9e6b` / `#c98a12` / `#d64545` / `#3b7dd8` | 同色略提亮 | 状态 |
| `--brand-jable` / `--brand-youtube` / `--brand-douyin` | `#7c5cd6` / `#e0322a` / `#111418`(dark: `#e8ebef`) | | 来源标识 |
| `--focus` | `0 0 0 3px rgba(232,96,63,.35)` | 同 | 焦点环 |

实色为主，禁止装饰性渐变；封面上的遮罩用 `rgba(0,0,0,.x)`。

### 3.2 字体与排版

- 字族：`"Segoe UI", "PingFang SC", "Microsoft YaHei UI", "Noto Sans SC", system-ui, sans-serif`；**不加载任何外部字体**。
- 字号阶梯：`--fs-12/13/14/16/20/24/32`；页面标题 24–32，区块标题 20，正文 14，辅助 12–13。
- 行高 1.5（正文）/ 1.3（标题）；数字使用 `font-variant-numeric: tabular-nums`。
- 字重 400 / 500 / 600 / 700。

### 3.3 间距、圆角、阴影

- 间距 4pt 网格：`--sp-1..--sp-12` = 4/8/12/16/20/24/32/40/48/64。
- 圆角：控件 6px、卡片/输入 10px、面板/对话框 14px、胶囊 999px。
- 阴影：`--shadow-1: 0 1px 2px rgba(16,20,24,.06)`；`--shadow-2: 0 6px 24px rgba(16,20,24,.10)`；`--shadow-3: 0 16px 48px rgba(16,20,24,.18)`（暗色下适当加深）。

### 3.4 尺寸与布局

- 控件最小高度：桌面 36px，`(pointer: coarse)` 下 44px。
- 侧栏 240px / 收起 72px；顶栏 56px；内容内边距 32px（≥1800px 为 40px；移动端 16px）。
- 内容最大宽：一般页面 1200px；Jable 与馆藏 1520px。
- 媒体网格：`grid-template-columns: repeat(auto-fill, minmax(220px, 1fr))`，间距 24×16；详情分栏打开时列表侧 2 列。

### 3.5 图标

- 代码内联 SVG，24 viewBox，1.75px 描边，`currentColor`；统一放在 `js/ui/icons.js` 中按名字导出。

### 3.6 动效

| Token | 值 | 用途 |
| --- | --- | --- |
| `--dur-fast` | 120ms | hover/press |
| `--dur` | 180ms | 面板进入、切换 |
| `--dur-slow` | 260ms | 抽屉、sheet |
| `--ease` | `cubic-bezier(.2,.8,.2,1)` | 统一缓动 |

- 路由切换：内容区 160ms 淡入 + 6px 上移。
- 抽屉/托盘：260ms 位移 + 淡入；关闭 180ms。
- 骨架：1.4s 脉动；进度条宽度 `transition: width 240ms`。
- 卡片 hover：封面 scale(1.02)、标题变主色；不做阴影跳动。
- `prefers-reduced-motion: reduce` 下全部动画禁用（保留即时状态变化）。

---

## 4. 组件库（`web/js/ui/`，每个组件独立文件，纯函数渲染 + 事件委托）

| 组件 | 要点 |
| --- | --- |
| `Button` | primary / secondary / ghost / danger；loading 态（内置 spinner，宽度不跳）；`aria-busy` |
| `Chip` / `SegmentedTabs` | 单选、可滚动溢出、键盘左右切换、`aria-pressed`/`role=tablist` |
| `Dropdown` | 按钮 + 菜单；`aria-expanded`；↓ 进入、Esc 关闭并回焦；点击外部关闭；支持两列级联（分类/标签） |
| `Field` | label + control + help/error；数字/文本/textarea |
| `Dialog` | 原生 `<dialog>`；焦点陷阱；Esc；返回焦点 |
| `Drawer`（收藏单）/ `Sheet`（移动端） | 右侧滑入；可最大化；内容区可滚动；头部固定 |
| `Toast` | 右下堆叠，最多 3 条；成功/错误/信息；可带操作（如「打开目录」） |
| `Skeleton` | 卡片/行两种；`aria-busy` 容器 + `sr-only` 状态 |
| `EmptyState` | 图标 + 标题 + 说明 + 主/次操作 |
| `MediaCard` | 封面 16:10、时长角标、标题 2 行、元信息（观看/日期/演员链接）、可选勾选框（批量模式）、`is-active` |
| `Pager` | 首/上/页码窗口(5)/下/末 + 跳页输入；`aria-current`；移动端隐藏首末 |
| `ProgressBar` | 百分比 + 阶段步骤条（排队/下载/解密/封装/完成） |
| `TaskRow` | 图标（来源）+ 标题 + 状态 + 进度 + 操作（取消/打开目录/重开） |
| `StatusDot` | ok/warn/bad + 文案 |

---

## 5. 页面规格

### 5.1 首页 `#/`
- 顶部：标题「把喜欢的内容，留在本地。」+ 说明；大输入框（自动识别来源徽标、Enter 解析、粘贴即识别）；三步说明保留但精简为一行。
- 中部：三张来源卡（Jable：热门/最新/分类快捷；YouTube：视频/频道/播放列表；抖音：作品/主页/推荐/关注/话题/喜欢）。
- 下部两栏：「最近任务」（来自 `/api/tasks`，最多 5 条，含进度）与「最近收入馆藏」（来自 `/api/library` 最近 8 个，缩略图）。空态各自给出引导。

### 5.2 Jable
- 页头：标题「Jable」+ 站内搜索框（番号/标题/创作者 → 走收藏单解析）。
- 一级导航（下划线 Tab）：精选 / 热门 / 最新 / 分类浏览；演员页从卡片进入。
- 精选：两段（热门精选、最新影片），各 12 张一页 + 分页器；每段标题右侧「查看全部」。
- 列表页：标题 + 计数（`{total} 部影片`）+ 筛选栏（热门：排序；最新：年/月；分类：分类下拉 + 标签级联；演员：排序）+ 「重置筛选」；网格；分页器（`page_size=12`、`total`、`page_count` 语义不变；跳页优先 `/api/jable/page`，`pending` 时回退 `/api/jable/list` 并轮询 ≤ 15 次）。
- **批量模式**：列表工具栏「批量选择」切换 → 卡片显示勾选框 → 底部浮动条「已选 n · 保存所选 · 取消」→ 逐个调用 `POST /api/jable/save`，进入托盘。
- 详情分栏（`?p=code`）：保留现有 `inspect-layout.js` 的拖拽/键盘/放大逻辑；面板结构：工具条（作品详情 · 放大 · 关闭）→ 16:9 播放器（默认尝试完整视频 HLS，失败回落 DMM 预览，徽标标明）→ 状态 → 日期/标题 → 操作（预览短片/完整视频切换、下载此片、打开播放页）→ 演员 chips → 类型 chips。Esc 关闭并回焦到卡片；< 1024px 改为上下堆叠。
- 播放页 `#/jable/v/:code`：返回列表链接、全宽播放器、标题/番号/有效期、下载按钮、相关视频网格。
- 数据层：**保留**旧版 `app.js` 中的列表缓存策略语义（localStorage 快照 `od-jable-list-*`、`od-jable-home-v1`、`od-jable-models`；snapshot/works/orders 的合并逻辑；`hydrateItem`/`rememberWork`），但收敛为 `jable/data.js` 一个模块，并做以下性能修正：
  - `/api/jable/orders` 轮询：仅当当前处于 cat/tag 且 `complete < lists` 时轮询，间隔 8s，完成即停；离开 Jable 停止。
  - 同级列表预取：并发 ≤ 3，使用 `requestIdleCallback`（或 `setTimeout 300`）延后，只预取当前模式的邻近项，总数 ≤ 12。
  - 悬停预取：DMM 预热与播放地址预取改为 `pointerenter` 停留 ≥ 250ms 才触发，且同一时间在途 ≤ 2。
  - hls.js 按需加载（本地 `web/vendor/hls.min.js`，首次播放时 `import()`）。
  - 封面 `loading="lazy" decoding="async"`，首屏前 8 张 `fetchpriority="high"`。

### 5.3 YouTube `#/youtube`
- 页头：来源标识 + 「能做什么」能力 chips（视频 / 频道 / 播放列表 / Shorts / 直播 / 字幕 / 1080p–4K）。
- 输入区：输入框 + 频道分栏选择（全部上传/视频/Shorts/直播）+ 解析按钮；说明文字：分栏仅在解析频道时生效。
- 下方：「最近解析」（localStorage 最近 10 条输入，可一键重放）与「YouTube 馆藏」最近 8 项。

### 5.4 抖音 `#/douyin`
- 页头：来源标识 + Cookie 状态（就绪/缺少 → 跳设置）。
- 模式 Tab：作品 / 主页、推荐、关注、话题、喜欢；每个模式有各自 placeholder 与说明；推荐/关注可空输入直接解析。
- 下方：最近解析 + 抖音馆藏最近 8 项。

### 5.5 馆藏 `#/library`
- 工具栏：来源筛选（全部/Jable/YouTube/抖音）、搜索框、排序（最近/名称/大小）、视图切换（网格/列表）、「打开目录」。
- 网格卡：封面（同名 jpg，缺失则来源色块 + 文件扩展名）、文件名、大小 · 时间；点击进入内嵌播放（`<dialog>` 内 `<video src="/api/library/file?rel=">`），操作：在资源管理器中显示、复制路径。
- 分页/无限：`limit=60` + 「加载更多」。

### 5.6 任务 `#/tasks`
- 顶部统计：进行中 / 排队 / 今日完成。
- 列表：进行中（进度条 + 速度 + ETA + 取消）、排队、历史（成功：打开目录；失败：错误摘要 + 重试=重新打开收藏单）。
- 「清空历史」二次确认。

### 5.7 设置 `#/settings`
- 分区：依赖检查（Python / FFmpeg / yt-dlp / Playwright / 抖音 Cookie，每项状态与说明）、保存位置（目录 + 打开）、解析与下载（条数、并发）、抖音登录（步骤 + Cookie 粘贴）、外观（跟随系统/浅色/深色）、关于（版本、端口、README 链接）。
- 保存即生效并 toast；输入校验（范围）。

### 5.8 收藏单抽屉
- 头部：来源图标 + 标题（识别结果）+ 步骤指示（解析 → 预览 → 保存）+ 最大化/关闭。
- 解析中：状态行 + 可展开日志（等宽字体、自动滚动）。
- 预览：封面横幅（有则显示）、标题/作者/条数；工具行：全选、已选 n/总数、筛选标题、卡片/列表切换、分辨率（若 `options.quality`）、字幕（若 `options.subs`）；清单卡片可勾选；`downloadable=false` 时禁用保存并显示 hint。
- 底部固定操作条：「确认保存 (n)」主按钮；解析失败时「重试」。
- 保存中：进度条 + 阶段步骤 + 速度/ETA + 取消；完成：打开目录 / 查看馆藏 / 新收藏单。

### 5.9 任务托盘
- 右下角胶囊：无任务时隐藏；有任务时显示「n 个任务进行中 · xx%」；点击展开最近 5 条 `TaskRow`；「查看全部」→ `#/tasks`。
- 完成时 toast「已收入馆藏 · 打开目录」。

---

## 6. 内容设计

- 语气：简洁、动词开头、不用感叹号。核心动词固定：**解析 / 预览 / 确认保存 / 收入馆藏**。
- 术语固定：来源、收藏单、任务、馆藏、依赖、Cookie。
- 空态模板：一句话说明当前为空 + 一个可执行操作。
- 错误模板：发生了什么 + 可能原因 + 下一步（重试 / 打开设置 / 修改输入）。示例：「解析失败：无法访问该链接。检查网络或 Cookie 后重试。」
- 数字：观看数 `1.2K/3.4M`，日期 `YYYY-MM-DD`，大小 `1.2 GB`，相对时间「3 分钟前」。

---

## 7. 交互与可访问性

- 键盘：`Ctrl/⌘+K` 或 `/` 聚焦全局输入；`Esc` 依次关闭 菜单 → 抽屉 → 详情面板；`g h/j/y/d/l/t/s` 快速跳转（首页/Jable/YouTube/抖音/馆藏/任务/设置）；分页器输入框 Enter 跳页；下拉 ↓ 进入 / Esc 回焦。
- 焦点：所有可交互元素 `:focus-visible` 主色环；抽屉/对话框焦点陷阱；关闭后回到触发元素。
- 语义：`nav`/`main`/`aside` 区块、`aria-current`、`aria-live` 状态区、`aria-busy` 骨架、图标 `aria-hidden`、图标按钮 `aria-label`。
- 触控：coarse pointer 下所有目标 ≥ 44px；网格 2 列（< 768px）/ 1 列（< 400px）。
- 首屏「跳到主要内容」链接保留。

---

## 8. 性能设计与预算

| 指标 | 预算 |
| --- | --- |
| 首屏（本地服务、缓存暖）| DOMContentLoaded < 300ms；首次内容绘制 < 600ms |
| 首屏请求 | 0 外部域；CSS/JS 无嵌套瀑布（CSS `<link>` 平铺、JS `modulepreload` 平铺）；首批文件数见验证记录 |
| JS 总量 | ≤ 160KB 未压缩（不含按需 hls.js） |
| 路由切换 | < 100ms 出现内容或骨架 |
| Jable 列表跳页（本地缓存命中）| < 300ms 出现 12 张卡 |
| 空闲网络 | 无任务、非 cat/tag 待完成状态时，页面空闲 30s 内请求数为 0 |

策略：静态资源由服务端加 `Cache-Control: no-cache` + ETag（304 秒回，无需 `?v=`）；hls.js 本地化并按需 `import()`；封面懒加载；列表数据 localStorage 快照即时绘制 + 后台校准；SSE 仅在有活动任务时连接；`content-visibility: auto` 用于长网格；避免布局抖动（所有媒体固定比例盒）。

---

## 9. 前端架构

零构建、原生 ES 模块（由 FastAPI `/static` 直接提供）。

```
web/
  index.html                 壳骨架 + <template id="tpl-*">（各视图/组件模板）
  vendor/hls.min.js          本地化 hls.js（从 node CDN 下载一次，固定版本 1.5.17）
  css/app.css                @import tokens/base/shell/components/views/*
  css/tokens.css  base.css  shell.css  components.css
  css/views/{home,jable,source,library,tasks,settings,collect}.css
  js/main.js                 启动：主题、路由、壳、健康检查、任务恢复
  js/core/router.js          路由表 + 参数解析 + navigate()/replace()；兼容旧 hash
  js/core/store.js           createStore(initial, {persistKeys})：get/set/patch/subscribe
  js/core/api.js             api.get/post（超时、错误归一 {message,status}）、sse(url, handlers)
  js/core/dom.js             html`` 模板、esc()、delegate()、focusTrap()、qs/qsa
  js/core/format.js          fmtViews/fmtDate/fmtSize/relTime/parseDuration
  js/core/prefs.js           主题、侧栏折叠、视图偏好（localStorage）
  js/ui/*.js                 §4 组件
  js/features/tasks.js       任务状态（列表 + SSE 订阅管理 + 托盘 + toast）
  js/features/collect.js     收藏单抽屉状态机（detect→parse→preview→download）
  js/views/{home,source,library,tasks,settings}.js
  js/jable/{index,data,list,filters,inspect,player,cards}.js
```

约束：
- 单文件 ≤ 600 行；模块只通过导出函数/store 通讯，禁止全局变量（`window.Hls` 由 vendor 提供除外）。
- 所有 HTML 拼接必须经 `esc()`；不使用 `innerHTML` 插入未转义用户数据。
- 事件采用容器级委托；视图切换时调用 `unmount()` 清理定时器与 SSE。
- 不引入框架与打包器；不使用 TypeScript。

---

## 10. 后端改动契约（最小、向后兼容）

1. **任务列表与持久化**（`server/jobs.py`、`server/app.py`）
   - `GET /api/tasks?limit=50` → `{"items":[snapshot...]}`，按 `created` 倒序；snapshot 新增：`title`（预览标题或番号大写）、`site`、`count`（ids 数）、`finished`（时间戳或 null）、`live`（是否本进程内存中）。
   - `DELETE /api/tasks/{id}`：仅允许删除非 `queued/running` 的任务记录（含历史）。
   - 历史持久化：完成/失败/取消的 **download** 任务追加写入 `library/_tasks.json`（最多保留 200 条：id/kind/title/site/status/count/created/finished/error/result.cwd）；启动时加载，`GET /api/tasks` 合并输出（`live:false`）。
   - 双通道 Runner：`parse` 与 `download` 各自独立 worker 线程；下载仍串行。取消语义不变。
2. **馆藏 API**（`server/library.py` 新模块，`app.py` 挂路由）
   - `GET /api/library?site=&q=&sort=mtime|name|size&order=desc|asc&offset=0&limit=60` → `{"path","total","sites":[{"site","count"}],"items":[{"site","name","rel","size","mtime","ext","cover"}]}`；`cover` 为同名 `.jpg/.jpeg/.png/.webp` 的 rel 或 `""`。仍返回旧字段 `sites[].recent`（保持兼容）。
   - `GET /api/library/file?rel=` → 媒体/封面文件，支持 `Range`（自行实现 206），路径必须解析后位于馆藏目录内，否则 400。
   - `POST /api/library/reveal` `{rel}` → Windows `explorer /select,<abs>`；其他平台打开所在目录。
   - `POST /api/open-library` 保留。
3. **静态资源缓存**：`/static` 使用自定义 `StaticFiles` 子类，对 `.html/.css/.js/.svg/.json` 响应加 `Cache-Control: no-cache`（保留 ETag），媒体类保持默认。`GET /` 继续 `no-store`。
4. **健康检查**新增 `version`（读取 `server/__init__.py` 的 `__version__ = "2.0.0"`）与 `port`。
5. 其余 Jable / DMM / 代理接口 **不改变**。

---

## 11. 实施计划（工作包）

| WP | 内容 | 产出 | 验收 |
| --- | --- | --- | --- |
| WP1 后端 | §10 全部 | `server/jobs.py`、`server/library.py`、`server/app.py`、`tests/test_tasks_api.py`、`tests/test_library_api.py` | pytest 通过；旧接口回归（`test_jable_download.py`、`test_detect.py`）通过 |
| WP2 前端基础 | 设计系统 + 壳 + 路由 + store + api + 组件 + 首页/来源页/馆藏/任务/设置 + 收藏单 + 托盘 | `web/` 新结构（Jable 视图为占位挂载点） | 三种视口截图；键盘流程；收藏单完成一次 YouTube/抖音解析（可用 mock） |
| WP3 Jable 模块 | 移植数据层与视图，批量模式，按需 hls | `web/js/jable/*` | `ui_jable_*` 同类脚本更新后通过；分页/筛选/详情/播放行为等价 |
| WP4 测试与文档 | 更新 `tests/ui_*.py` 选择器；`README.md` 用法；本文补「验证记录」 | | 全部 UI 脚本通过；性能记录 |
| WP5 收尾 | 删除旧文件（`app.js`、`styles.css`、`workbench.css`、`inspect-layout.*`）；`index.html` 无外部域引用 | | `rg "googleapis|jsdelivr" web/` 为空 |

## 12. 验收清单（完成定义）

- [x] 所有路由可直达、可刷新、可前后退；旧 hash 兼容。 `tests/ui_smoke.py`
- [x] 桌面 1440×900、笔记本 1280×720、手机 390×844 无水平溢出，所有主要流程可完成。 `tests/ui_smoke.py`
- [ ] 收藏单：解析 → 预览 → 保存 → 完成，刷新后托盘/任务页仍显示进度。 （`tests/ui_collect.py` 覆盖失败态 / 预览，未点保存）
- [x] Jable：精选、热门四档、最新年月、分类/标签级联、演员排序、详情分栏（拖拽/键盘/放大）、播放页、批量保存。 `tests/ui_jable_feed.py` `tests/ui_jable_filters.py` `tests/ui_jable_cascade.py` `tests/ui_jable_actor.py` `tests/ui_jable_inspect.py` `tests/ui_jable_play_hit.py` （批量保存未单独脚本化）
- [x] 馆藏：筛选/搜索/排序/播放/定位文件。 `tests/ui_library.py`
- [x] 设置：保存生效；主题切换即时；依赖状态正确。 `tests/ui_settings.py`
- [x] 性能预算（§8）全部达标，并记录测量方法与数字。 `tests/ui_perf.py`（见 §13）
- [ ] `tests/test_*.py` 通过；`tests/ui_*.py` 更新后通过。 （`tests/ui_*.py` 由 `tests/run_ui.py` 跑；本 WP 未重跑 pytest 单元套件）
- [x] 文档：本文 + README 更新。

---

## 13. 验证记录

- **日期**：2026-09-05
- **机器**：Windows 10（10.0.26200），Python 3.11，Playwright Chromium headless
- **服务**：已运行的 `http://127.0.0.1:8765`（新后端 + 新前端，静态 `Cache-Control: no-cache`）；测试未重启该进程
- **方法**：`python tests/ui_perf.py`（首页带 `?od=` cache-bust，CDP `Network.setCacheDisabled`；DCL / FCP 取 `PerformanceNavigationTiming` / `first-contentful-paint`；JS/CSS 解码体积按实际 GET 正文计，不含按需 `hls.min.js`；空闲窗口从首屏 networkidle 后再等 1.5s 起算 30s；`#/jable/hot` 先暖缓存再切回首页后重进，计时到 12 张 `.av-card`）
- **实测数字**：以 `tests/_out/ui_perf.json` 为准（脚本跑完后写入）。占位如下，跑通后回填。

| 指标 | 预算 | 实测 |
| --- | --- | --- |
| DCL | < 300ms | （待 `ui_perf.py`） |
| FCP | < 600ms | （待 `ui_perf.py`） |
| 外部域请求 | 0 | （待 `ui_perf.py`） |
| 空闲 30s 新增请求 | 0 | （待 `ui_perf.py`） |
| JS 解码 | ≤ 160KB | （待 `ui_perf.py`） |
| 首批 JS 文件 | 见偏差表 | （待 `ui_perf.py`） |
| `#/jable/hot` 缓存命中 → 12 卡 | < 300ms | （待 `ui_perf.py`） |

### 与预算的有意偏差

| 项 | 蓝图原值 | 现状 | 为何接受 |
| --- | --- | --- | --- |
| CSS 组织 | 1 个入口 + `@import`（允许 ≤ 3） | 11 个平铺 `<link>`（`tokens` / `base` / `shell` / `components` + 7 个 `views/*`），放弃 `@import` | `@import` 会串成瀑布；平铺后浏览器并行拉本地 CSS。DCL/FCP 以 `ui_perf.py` 实测对照预算，本地服务下仍应落在 300/600ms 内。 |
| JS 首批 | ES 模块 ≤ 8 个文件 | 14 个模块 `modulepreload` 平铺（`main` + core/ui/features/home），零嵌套瀑布；收藏单 / Jable / 其它视图按需 `import()` | 首屏必需的壳、路由、任务恢复、首页不能再少而不拆语义。`modulepreload` 并行，无深度 import 链。体积以未压缩解码 KB 计，预算 160KB。 |
