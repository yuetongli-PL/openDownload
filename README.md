# openDownload

本地收藏工作台：把 Jable、YouTube、抖音三套下载脚本收进同一个本机网站。

核心约定只有一条：**先解析出预览，勾选确认，再写入本地目录。** 下载不会在你点「确认保存」之前开始。

成品和网页都在本目录。四个原文件夹（`Desktop\Jable`、`Desktop\Youtube`、`Desktop\抖音`、`Desktop\Youtube - 副本`）只被复制过脚本，没有改过，这里也不引用它们的路径。

## 运行

1. Python 3.11+、FFmpeg（YouTube / Jable 封装 mp4）
2. 抖音登录类功能需要 Playwright：`pip install playwright` 后 `playwright install chromium`
3. 双击 `start.bat`，或：

```bat
cd /d C:\Users\lyt-p\Desktop\openDownload
python -m pip install -r requirements.txt
python -m server
```

浏览器打开 http://127.0.0.1:8765/

## 用法

工作台按来源切换，地址栏是 `#/jable`、`#/youtube` 这类路由。

1. 顶部选择 **智能 / Jable / YouTube / 抖音**。智能模式会在输入时即时识别来源。
2. 在输入框粘贴链接，或用户名 / 番号 / 抖音号，点 **解析**。
   - Jable：还可切到 **热门** 或 **选片**，按时间档、主题、标签浏览列表。
   - YouTube：解析频道时可先选 **全部上传 / 视频 / Shorts / 直播**；清晰度与字幕在预览里再选。
   - 抖音：除作品 / 主页外，可直接解析 **推荐、关注流、话题、喜欢**。后四项需要 cookie。
3. 预览清单出来后勾选要保存的条目，需要时筛选标题、切换卡片 / 列表。
4. 点 **确认保存**。进度停在页面下方，可取消；完成后可打开 **馆藏** 查看最近文件，或在资源管理器中打开目录。

**环境**（右上角）负责：馆藏路径、列表条数、并行连接数、抖音 cookie，以及 FFmpeg / yt-dlp / Playwright 是否就绪。

保存目录默认是本仓库下的 `library\`，按来源分成 `jable\`、`youtube\`、`douyin\`。

## 脚本从哪来

`python\` 是复制件：

| 来源 | 复制的文件 |
| --- | --- |
| Jable | `jable_*.py` |
| Youtube - 副本（比 Youtube 新） | `youtube_*.py` |
| 抖音 | `douyin_*.py`、`cookie.txt` |

下载仍由这些脚本执行，网页负责路由、确认、进度和馆藏。

## 抖音 cookie

登录后的主页 / 喜欢 / 关注 / 话题 / 推荐需要 `python\cookie.txt`。环境页可以粘贴覆盖。游客推荐可解析公开作品链接。

请只下载你有权保存的内容。
