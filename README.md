# openDownload

本机媒体工作台：浏览 Jable / YouTube / 抖音，先解析出预览，勾选确认后再写入本地目录。

核心约定只有一条：**下载不会在你点「确认保存」之前开始。** 解析与保存都在右侧「收藏单」和右下「任务托盘」里进行，主内容区可以继续浏览；任务由服务端持有，刷新后进度还在。

成品和网页都在本目录。四个原文件夹（`Desktop\Jable`、`Desktop\Youtube`、`Desktop\抖音`、`Desktop\Youtube - 副本`）只被复制过脚本，没有改过，这里也不引用它们的路径。

## 运行

1. Python 3.11+
2. FFmpeg（YouTube / Jable 封装 mp4，需在 PATH 或常见安装位置）
3. `requirements.txt` 会安装 FastAPI、uvicorn、yt-dlp、Playwright、pycryptodome
4. 抖音登录类功能需要 Playwright 浏览器：`pip install playwright` 后执行 `playwright install chromium`

双击 `start.bat`，或：

```bat
cd /d C:\Users\lyt-p\Desktop\openDownload
python -m pip install -r requirements.txt
python -m server
```

浏览器打开 http://127.0.0.1:8765/ （默认端口，可在设置或 `settings.json` 的 `port` 修改）。不要同时再开一份服务。

## 界面导览

地址栏是 hash 路由。侧栏始终提供首页、三个来源、馆藏、任务、设置；顶栏有全局输入框（首页隐藏，其它页显示）和本地服务状态。

### 首页 `#/`

大标题「把喜欢的内容，留在本地。」下面是大输入框（Enter 解析、粘贴即识别来源）和三步说明。中部三张来源卡跳到 Jable / YouTube / 抖音。下部是最近任务与最近收入馆藏。

### 来源页

- **Jable** `#/jable`：精选（热门 + 最新两段网格）、热门四档、最新年月、分类 / 标签级联、演员作品。卡片打开右侧详情分栏（预览 / 完整视频 / 保存）；`#/jable/v/:code` 是全宽播放页。列表可「批量选择」后逐条加入任务。
- **YouTube** `#/youtube`：粘贴视频 / 频道 / 播放列表；解析频道时可先选全部上传、视频、Shorts、直播。清晰度与字幕在收藏单预览里再选。
- **抖音** `#/douyin`：作品 / 主页、推荐、关注、话题、喜欢。后几项需要 cookie；页头会显示 Cookie 是否就绪。

旧地址 `#/auto` 仍进首页，`#/setup` 仍进设置。

### 收藏单（三步）

任意页的全局输入框（`Ctrl/⌘+K` 或 `/`）或来源页输入框回车，右侧抽出收藏单：

1. **解析**：识别来源，拉取预览（日志可展开）
2. **预览**：勾选条目，可筛选标题、切卡片 / 列表、选分辨率与字幕
3. **确认保存**：进度在抽屉与托盘里走；完成后可打开目录或去馆藏

Esc 关闭抽屉，不取消任务。解析失败会给出错误与重试。

### 馆藏 `#/library`

按来源筛选、搜索文件名、按最近 / 名称 / 大小排序，网格或列表。「打开目录」打开整个馆藏文件夹。点开一张卡在对话框里播放（`/api/library/file`，支持 Range），可「在资源管理器中显示」或复制路径。

默认目录是仓库下的 `library\`，再按来源分成 `jable\`、`youtube\`、`douyin\`。

### 任务与托盘 `#/tasks`

进行中 / 排队 / 历史。进行中可取消；失败可重开收藏单；结束的记录可删除。「清空历史」会二次确认。右下托盘在有进行中任务时出现，点开看最近几条，或「查看全部」。

### 设置 `#/settings`

依赖检查（Python / FFmpeg / yt-dlp / Playwright / 抖音 Cookie）、馆藏路径、列表条数、并行连接数、抖音 Cookie 粘贴、外观（跟随系统 / 浅色 / 深色）、关于（版本与端口）。保存即生效。

### 主题

侧栏「主题」按钮在浅色 / 深色之间切换，立即改 `html[data-theme]`，并写入 `localStorage`。设置页也可以选跟随系统。

## 快捷键

| 按键 | 作用 |
| --- | --- |
| `Ctrl/⌘+K` 或 `/` | 聚焦输入框 |
| `Enter` | 解析（输入框）或跳页（分页器） |
| `Esc` | 依次关闭菜单 → 收藏单 → 详情面板 |
| `g` 然后 `h` / `j` / `y` / `d` / `l` / `t` / `s` | 跳到首页 / Jable / YouTube / 抖音 / 馆藏 / 任务 / 设置 |
| `↓` / `Esc` | 下拉：进入菜单 / 关闭并回焦 |

侧栏当前项带 `aria-current="page"`。页面顶部有「跳到主要内容」。收藏单打开后 Tab 循环留在抽屉内。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 依赖、版本、端口、当前 `settings` |
| GET / POST | `/api/settings` | 读取 / 保存馆藏路径、条数、并发、端口 |
| POST | `/api/cookie` | 写入 `python/cookie.txt` |
| POST | `/api/detect` | 识别链接 / 番号 / 用户名属于哪个来源 |
| POST | `/api/parse` | 提交解析任务，返回任务快照 |
| POST | `/api/download` | 按解析结果与勾选 id 开始保存 |
| GET | `/api/tasks?limit=` | 任务列表（内存 + 历史），按创建时间倒序 |
| GET | `/api/tasks/{id}` | 单条任务 |
| DELETE | `/api/tasks/{id}` | 删除非进行中 / 非排队的记录 |
| POST | `/api/tasks/{id}/cancel` | 取消进行中的任务 |
| GET | `/api/tasks/{id}/stream` | SSE：日志、预览、进度、结束 |
| POST | `/api/jable/save` | 按番号直接加入下载任务 |
| GET | `/api/jable/*` | 目录、首页、列表、分页、封面元数据、播放地址等（浏览用） |
| GET | `/api/library?site=&q=&sort=&order=&offset=&limit=` | 馆藏列表 |
| GET | `/api/library/file?rel=` | 媒体 / 封面，支持 Range（206） |
| POST | `/api/library/reveal` | 在资源管理器中定位文件 |
| POST | `/api/open-library` | 打开馆藏根目录 |

## 目录结构

```
openDownload/
  web/                 前端（零构建，原生 ES 模块）
    index.html         壳 + 路由入口
    css/               设计令牌、壳、组件、各视图
    js/core/           路由、请求、store、偏好
    js/ui/             按钮、抽屉、分页等
    js/features/       收藏单、任务托盘
    js/views/          首页、来源、馆藏、任务、设置
    js/jable/          Jable 列表 / 筛选 / 详情 / 播放
    vendor/hls.min.js  按需加载的本地 hls.js
  server/              FastAPI 后端（`python -m server`）
  python/              各来源下载脚本的复制件
  library/             默认馆藏（按来源分子目录，已被 gitignore）
  tests/               pytest 与 Playwright UI 脚本
  docs/design/         2.0 重构蓝图
  requirements.txt
  start.bat
```

## 测试

单元 / 接口（不启浏览器）：

```bat
python -m pytest tests/test_*.py -q
```

界面（对着已运行的 http://127.0.0.1:8765 ，可用 `OD_BASE` 覆盖）：

```bat
python tests/run_ui.py
python tests/run_ui.py --only jable
python tests/ui_smoke.py
```

`run_ui.py` 会依次跑全部 `tests/ui_*.py`，每个超时 180 秒，打印脚本 / 结果 / 耗时；任一失败则退出码非 0。截图写到 `tests/_out/`。

## 脚本从哪来

`python\` 是复制件：

| 来源 | 复制的文件 |
| --- | --- |
| Jable | `jable_*.py` |
| Youtube - 副本（比 Youtube 新） | `youtube_*.py` |
| 抖音 | `douyin_*.py`、`cookie.txt` |

下载仍由这些脚本执行，网页负责路由、确认、进度和馆藏。

## 抖音 cookie

登录后的主页 / 喜欢 / 关注 / 话题 / 推荐需要 `python\cookie.txt`。设置页可以粘贴覆盖。游客推荐可解析公开作品链接。

请只下载你有权保存的内容。

## 常见问题

**打不开 8765。** 确认只开了一份 `python -m server`，端口没被占用；看控制台是否报错。可用 `settings.json` 的 `port` 改端口。

**YouTube / Jable 保存失败，提示 FFmpeg。** 安装 FFmpeg 并保证 `ffmpeg` 在 PATH，或使用常见的 WinGet / `C:\ffmpeg\bin` 安装位置。设置页「依赖检查」应显示就绪。

**抖音主页 / 喜欢 / 关注是空的或报错。** 先在设置里粘贴 Netscape 格式 cookie，并执行过 `playwright install chromium`。

**解析很慢或列表在转圈。** Jable 分类 / 标签若本地索引未完成，会先出骨架再回填。热门 / 最新有本地缓存时应秒开。

**刷新后任务还在吗？** 进行中的任务在服务端内存里；已结束的下载会写入 `library/_tasks.json`，任务页能看到历史。

**主题刷新后变回去。** 用侧栏主题按钮或设置里的浅色 / 深色，不要只依赖「跟随系统」却在系统主题变化时期待固定颜色。
