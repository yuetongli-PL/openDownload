# -*- coding: utf-8 -*-
"""登录态网页拦截：推荐、用户作品、喜欢、关注列表。

只打开官网页面，读取浏览器自己发出的 JSON。不算签名、不直打加固接口。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from douyin_parse import die, parse_profile_payload, summarize_author, summarize_aweme

HERE = Path(__file__).resolve().parent
LOGIN_COOKIE_NAMES = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt"}
FEED_HINTS = (
    "tab/feed",
    "module/feed",
    "aweme/v1/web/tab",
    "aweme/v1/web/module",
    "aweme/v1/web/general/feed",
    "aweme/v1/web/hot",
    "aweme/v1/web/aweme/detail",
    "aweme/v1/web/aweme/related",
    "aweme/v1/web/related",
    "aweme/v1/web/nearby/feed",
    "recommend/item",
    "aweme/v2/feed",
    "/web/api/v2/aweme",
    "aweme/v1/feed",
)
POST_HINTS = (
    "aweme/v1/web/aweme/post",
    "aweme/v1/web/aweme/list",
    "/web/api/v2/aweme/post",
    "aweme/post",
)
LIKE_HINTS = (
    "aweme/v1/web/aweme/favorite",
    "/web/api/v2/aweme/like",
    "aweme/favorite",
    "aweme/like",
    "favoritelist",
)
FOLLOWING_HINTS = (
    "user/following/list",
    "following/list",
    "aweme/v1/web/user/following",
)
FOLLOWER_HINTS = (
    "user/follower/list",
    "follower/list",
    "aweme/v1/web/user/follower",
)
FOLLOW_FEED_HINTS = (
    "aweme/v1/web/follow/feed",
    "/follow/feed",
    "aweme/v1/web/tab/feed",
    "aweme/v1/web/module/feed",
    "aweme/v2/web/module/feed",
)
DETAIL_HINTS = (
    "aweme/v1/web/aweme/detail",
    "aweme/detail",
)
RELATED_HINTS = (
    "aweme/v1/web/aweme/related",
    "aweme/related",
)
HASHTAG_HINTS = (
    "aweme/v1/web/challenge/aweme",
    "aweme/v1/web/challenge/detail",
    "challenge/aweme",
    "challenge/detail",
    "aweme/v1/web/search/item",
    "general/search",
)
PROFILE_HINTS = (
    "user/profile/other",
    "user/profile/self",
)
SKIP_URL = (
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".woff",
    "webmsdk",
    "sentry",
    "slardar",
    "bytedtsdk",
    "mcs.zijieapi",
)
POST_TAB_SELECTORS = (
    '[data-e2e="user-tab-post"]',
    '[data-e2e="user-post-tab"]',
    'span:has-text("作品")',
    'div[role="tab"]:has-text("作品")',
)
LIKE_TAB_SELECTORS = (
    '[data-e2e="user-tab-like"]',
    '[data-e2e="user-like-tab"]',
    'span:has-text("喜欢")',
    'div[role="tab"]:has-text("喜欢")',
)


def default_cookie_path() -> Path | None:
    names = ("cookie.txt", "cookies.txt", "Cookie.txt", "Cookies.txt")
    for folder in (Path.cwd(), HERE):
        for name in names:
            path = folder / name
            if path.is_file() and path.stat().st_size > 20:
                return path
    return None


def _cookie_item(name: str, value: str, domain: str = ".douyin.com") -> dict[str, Any]:
    return {
        "name": name.strip(),
        "value": value,
        "domain": domain,
        "path": "/",
        "secure": True,
        "httpOnly": False,
    }


def load_header_cookies(text: str) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    blob = " ".join(line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#"))
    if "\t" in blob and blob.count("\t") >= 6:
        return []
    for part in blob.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if not name or name.lower() in {"douyin.com", "path", "domain", "secure", "httponly"}:
            continue
        cookies.append(_cookie_item(name, value.strip()))
    return cookies


def load_netscape_cookies(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    header = load_header_cookies(text)
    if header:
        return header
    cookies: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        http_only = False
        if line.startswith("#HttpOnly_"):
            http_only = True
            line = line[len("#HttpOnly_") :]
        elif not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, cpath, secure, expires, name, value = parts[:7]
        item: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain if domain.startswith(".") else domain,
            "path": cpath or "/",
            "secure": secure.upper() == "TRUE",
            "httpOnly": http_only,
        }
        if expires.isdigit() and int(expires) > 0:
            item["expires"] = int(expires)
        cookies.append(item)
    return cookies


def require_login_cookies(cookies: list[dict[str, Any]], path: Path | None = None) -> None:
    names = {c.get("name") for c in cookies}
    if not (names & LOGIN_COOKIE_NAMES):
        shown = path or (HERE / "cookie.txt")
        die(
            f"{shown} 里没有 sessionid / sid_tt，不是登录态或文件已被清空。\n"
            "请重新在 Chrome 登录抖音，用 Get cookies.txt LOCALLY 导出，覆盖该文件。\n"
            "不要让 curl 把登录 cookie 写成空的 Netscape 文件。"
        )


def cookie_help() -> str:
    return (
        "登录后的推荐 / 作品 / 喜欢 / 关注 / 粉丝 / 话题需要 cookies.txt（账号 cookie）。\n"
        "1. Chrome 打开并登录 https://www.douyin.com/?recommend=1\n"
        "2. 安装扩展 Get cookies.txt LOCALLY，导出 Netscape 格式\n"
        f"3. 保存为 {HERE / 'cookie.txt'}\n"
        "4. 推荐: douyin.bat https://www.douyin.com/?recommend=1\n"
        "   用户作品: douyin.bat https://www.douyin.com/user/<sec_uid>\n"
        "   喜欢: douyin.bat --likes [user-url]\n"
        "   关注列表: douyin.bat --following [user-url]\n"
        "   粉丝: douyin.bat --followers [user-url]\n"
        "   关注作品流: douyin.bat https://www.douyin.com/follow\n"
        "   相关推荐: douyin.bat --related https://www.douyin.com/video/<id>\n"
        "   话题: douyin.bat https://www.douyin.com/hashtag/<name>\n"
        "游客推荐请加 --guest\n"
    )


def _iter_aweme(obj: Any):
    if isinstance(obj, dict):
        if obj.get("aweme_id") and isinstance(obj.get("video"), dict):
            yield obj
        inner = obj.get("aweme_info") or obj.get("aweme_detail")
        if isinstance(inner, dict) and inner.get("aweme_id"):
            yield inner
        for value in obj.values():
            yield from _iter_aweme(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_aweme(item)


def parse_feed_payload(data: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for aweme in _iter_aweme(data):
        aweme_id = str(aweme.get("aweme_id") or "")
        if not aweme_id or aweme_id in seen:
            continue
        seen.add(aweme_id)
        item = summarize_aweme(aweme)
        item["kind"] = "video"
        if item.get("best"):
            items.append(item)
    return items


def summarize_user(obj: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    if obj.get("aweme_id") and isinstance(obj.get("video"), dict):
        return None
    inner = obj
    for key in ("user_info", "user", "author", "owner"):
        cand = obj.get(key)
        if isinstance(cand, dict) and (
            cand.get("sec_uid") or cand.get("sec_user_id") or cand.get("secUid")
        ):
            inner = cand
            break
    if inner.get("aweme_id") and isinstance(inner.get("video"), dict):
        return None
    return summarize_author(inner) or summarize_author(obj)


def _iter_user(obj: Any):
    if isinstance(obj, dict):
        item = summarize_user(obj)
        if item:
            yield item
        for value in obj.values():
            yield from _iter_user(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_user(value)


def parse_user_payload(data: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for item in _iter_user(data):
        sec = item.get("sec_uid") or ""
        if not sec or sec in seen:
            continue
        seen.add(sec)
        items.append(item)
    return items


def _ingest_render_blob(text: str, ingest) -> None:
    if not text:
        return
    candidates = [text]
    try:
        candidates.append(unquote(text))
    except Exception:
        pass
    for blob in candidates:
        blob = blob.strip()
        if not blob:
            continue
        try:
            ingest(json.loads(blob))
            return
        except Exception:
            continue


def _domain_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        c
        for c in cookies
        if any(
            key in (c.get("domain") or "")
            for key in ("douyin", "snssdk", "amemv", "iesdouyin", "byteoversea", "365yg")
        )
    ]


def _looks_logged_out(url: str, allow_substr: str = "") -> bool:
    ul = (url or "").lower()
    if allow_substr and allow_substr.lower() in ul:
        return False
    return any(token in ul for token in ("/login", "passport", "sso."))


def _click_first(page, selectors: tuple[str, ...], timeout: int = 1500) -> bool:
    for sel in selectors:
        try:
            page.locator(sel).first.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def _dismiss_popups(page) -> None:
    try:
        page.evaluate(
            """() => {
                const box = document.querySelector('#uc-second-verify');
                if (box) box.remove();
                document.querySelectorAll('[class*=second_verify_mask]').forEach(el => el.remove());
            }"""
        )
    except Exception:
        pass
    try:
        for sel in (
            "text=跳过",
            'button:has-text("取消")',
            'button:has-text("关闭")',
            '[class*="close"]',
        ):
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=800)
    except Exception:
        pass


def _ingest_page_state(page, ingest) -> None:
    try:
        for blob in page.eval_on_selector_all(
            "script#RENDER_DATA, script#RENDER_DATA_1, script#__NEXT_DATA__",
            "els => els.map(e => e.textContent || '')",
        ) or []:
            _ingest_render_blob(blob, ingest)
        state = page.evaluate(
            """() => {
                if (window._ROUTER_DATA) return JSON.stringify(window._ROUTER_DATA);
                if (window.__INIT_PROPS__) return JSON.stringify(window.__INIT_PROPS__);
                return null;
            }"""
        )
        _ingest_render_blob(state, ingest)
    except Exception:
        pass


def _scroll_overflow(page, selectors: tuple[str, ...], fallback_links: str) -> None:
    try:
        page.evaluate(
            """(args) => {
                const selectors = args.selectors;
                const linkSel = args.links;
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (!el || el.scrollHeight <= el.clientHeight + 20) continue;
                    el.scrollTop = el.scrollHeight;
                    const last = el.querySelectorAll(linkSel)[el.querySelectorAll(linkSel).length - 1];
                    if (last) last.scrollIntoView({block: 'end'});
                    return;
                }
                const links = document.querySelectorAll(linkSel);
                const last = links[links.length - 1];
                if (last) last.scrollIntoView({block: 'end'});
                window.scrollBy(0, 1800);
            }""",
            {"selectors": list(selectors), "links": fallback_links},
        )
    except Exception:
        try:
            page.mouse.wheel(0, 2400)
        except Exception:
            pass


def _scroll_user_grid(page) -> None:
    _scroll_overflow(
        page,
        (
            '[data-e2e="user-post-list"]',
            '[data-e2e="scroll-list"]',
            '[data-e2e="user-like-list"]',
            '[class*="route-scroll-container"]',
        ),
        'a[href*="/video/"], a[href*="/note/"]',
    )


def _scroll_follow_panel(page) -> None:
    _scroll_overflow(
        page,
        (
            '[data-e2e="user-fans-container"]',
            '[role="dialog"]',
            '[class*="follow"]',
            '[class*="user-list"]',
            '[class*="UserList"]',
            '[class*="modal"]',
            '[class*="drawer"]',
        ),
        'a[href*="/user/"]',
    )


_COUNT_TEXT = re.compile(r"^[\d.]+[万wWkK千]?[+]?$")


def _wait_follow_panel(page, timeout: int = 8000) -> bool:
    try:
        page.wait_for_function(
            """() => {
                const box = document.querySelector('[data-e2e="user-fans-container"]')
                    || document.querySelector('[role="dialog"]');
                if (!box) return false;
                const text = (box.innerText || '').trim();
                if (text.length < 2) return false;
                return box.querySelectorAll('a[href*="/user/"]').length > 0
                    || /不可见|未公开|私密|没有/.test(text)
                    || text.length > 8;
            }""",
            timeout=timeout,
        )
        return True
    except Exception:
        return False


def _open_stat_count(page, e2e: str, label: str, click_root: bool = False) -> bool:
    # user-info-follow also contains「N人正在直播」; click the number, not the box.
    # Popular accounts show 280.3万 instead of a raw integer.
    # Use Playwright mouse click: element.click() in page.evaluate does not open the drawer.
    try:
        page.wait_for_selector(f'[data-e2e="{e2e}"]', timeout=15000)
    except Exception:
        return False
    root = page.locator(f'[data-e2e="{e2e}"]').first
    clicked = False
    shown = ""
    try:
        num = root.get_by_text(_COUNT_TEXT, exact=True).first
        shown = (num.inner_text(timeout=2000) or "").strip()
        num.click(force=True, timeout=4000)
        clicked = True
    except Exception:
        pass
    if not clicked:
        try:
            child = root.locator("xpath=./div[last()]").first
            shown = (child.inner_text(timeout=1500) or "").strip() or shown
            child.click(force=True, timeout=4000)
            clicked = True
        except Exception:
            pass
    if not clicked:
        try:
            root.click(force=True, timeout=4000)
            clicked = True
            shown = shown or "box"
        except Exception:
            if not click_root:
                return False
    if not clicked:
        return False
    print(f"  {label} count: {shown or 'clicked'}", flush=True)
    opened = _wait_follow_panel(page)
    if not opened:
        try:
            root.click(force=True, timeout=2000)
            opened = _wait_follow_panel(page, timeout=5000)
        except Exception:
            pass
    if opened:
        print(f"  {label} panel: open", flush=True)
    else:
        print(f"  {label} panel: not detected", flush=True)
    return opened


def _open_follow_list(page) -> bool:
    return _open_stat_count(page, "user-info-follow", "following")


def _open_follower_list(page) -> bool:
    return _open_stat_count(page, "user-info-fans", "followers", click_root=True)


def _collect_panel_users(page, skip_sec: str = "") -> list[dict[str, Any]]:
    try:
        rows = page.evaluate(
            """() => {
                const box = document.querySelector('[data-e2e="user-fans-container"]')
                    || document.querySelector('[role="dialog"]');
                if (!box) return [];
                const seen = new Set();
                const out = [];
                for (const a of box.querySelectorAll('a[href*="/user/"]')) {
                    const href = a.getAttribute('href') || a.href || '';
                    const m = href.match(/\\/user\\/([^/?#]+)/);
                    if (!m) continue;
                    const sec = decodeURIComponent(m[1]);
                    if (!sec || sec === 'self' || seen.has(sec)) continue;
                    seen.add(sec);
                    const text = (a.innerText || '').trim().split('\\n').filter(Boolean);
                    const at = (text.find(t => t.startsWith('@')) || '').replace(/^@/, '');
                    out.push({
                        sec_uid: sec,
                        nickname: text[0] || null,
                        unique_id: at || null,
                        url: href.startsWith('http') ? href : ('https://www.douyin.com/user/' + sec),
                    });
                }
                return out;
            }"""
        )
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for row in rows or []:
        sec = str(row.get("sec_uid") or "")
        if not sec or sec == skip_sec or sec == "self":
            continue
        nick = row.get("nickname")
        unique = row.get("unique_id") or ""
        if unique.startswith("@"):
            unique = unique[1:]
        items.append(
            {
                "kind": "user",
                "nickname": nick,
                "unique_id": unique or None,
                "sec_uid": sec,
                "url": row.get("url") or f"https://www.douyin.com/user/{sec}",
            }
        )
    return items


def _collect_video_hrefs(page) -> list[str]:
    try:
        hrefs = page.eval_on_selector_all(
            'a[href*="/video/"]',
            "els => els.map(e => e.href)",
        )
        return list(hrefs or [])
    except Exception:
        return []


def _make_on_response(
    ingest,
    hints: tuple[str, ...],
    extra_keys: tuple[str, ...],
    stats: dict[str, int],
    strict_hint: bool = False,
):
    def on_response(resp) -> None:
        url = resp.url or ""
        try:
            if resp.status != 200:
                return
        except Exception:
            return
        ul = url.lower()
        hinted = any(hint in url for hint in hints)
        if hinted:
            stats["hinted"] = stats.get("hinted", 0) + 1
        elif strict_hint:
            return
        else:
            if any(skip in ul for skip in SKIP_URL):
                return
            if extra_keys and not any(key in ul for key in extra_keys):
                return
        try:
            ctype = (resp.headers.get("content-type") or "").lower()
        except Exception:
            ctype = ""
        if ctype and "json" not in ctype and "text/plain" not in ctype and not hinted:
            return
        try:
            data = resp.json()
        except Exception:
            return
        ingest(data)

    return on_response


def _logged_in_session(
    cookies_path: Path,
    start_url: str,
    *,
    headed: bool,
    abort_images: bool,
    on_response,
    after_goto: Callable[[Any], None] | None,
    drive: Callable[[Any], None],
    login_ok: str = "",
    abort_media: bool = True,
) -> None:
    cookies = _domain_cookies(load_netscape_cookies(cookies_path))
    require_login_cookies(cookies, cookies_path)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        die("需要 playwright：pip install playwright 且已安装浏览器")

    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    launch_kwargs: dict[str, Any] = {
        "headless": not headed,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
    }
    if chrome.is_file():
        launch_kwargs["executable_path"] = str(chrome)

    abort_types: set[str] = set()
    if abort_media:
        abort_types.add("media")
    if abort_images:
        abort_types.update({"image", "font"})

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception:
            launch_kwargs.pop("executable_path", None)
            browser = p.chromium.launch(channel="chrome", headless=not headed)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            viewport={"width": 1400, "height": 900},
        )

        if abort_types:

            def abort_heavy(route) -> None:
                if route.request.resource_type in abort_types:
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", abort_heavy)
        context.add_cookies(cookies)
        page = context.new_page()
        page.on("response", on_response)
        page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        if _looks_logged_out(page.url or "", login_ok):
            browser.close()
            die("cookie 已失效，页面跳到登录。请重新导出 cookie.txt")
        _dismiss_popups(page)
        if after_goto:
            after_goto(page)
        drive(page)
        browser.close()


def _author_matches(prof: dict[str, Any] | None, user_id: str) -> bool:
    if not prof:
        return False
    if user_id in {"self", ""}:
        return True
    return prof.get("sec_uid") == user_id


def _looks_user_list(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    for key in (
        "user_list",
        "followings",
        "followers",
        "follow_list",
        "follower_list",
        "users",
        "user_info_list",
    ):
        val = data.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return True
    inner = data.get("data")
    if isinstance(inner, dict) and inner is not data:
        return _looks_user_list(inner)
    return False


def _ingest_follow_payload(
    data: Any,
    stats: dict[str, Any],
    items_map: dict[str, dict[str, Any]],
    user_id: str,
) -> None:
    _update_paging(data, stats)
    prof = parse_profile_payload(data)
    if _author_matches(prof, user_id):
        stats["author"] = prof
    if not _looks_user_list(data):
        return
    owner_sec = (stats.get("author") or {}).get("sec_uid") or (
        user_id if user_id not in {"self", ""} else ""
    )
    for item in parse_user_payload(data):
        if owner_sec and item.get("sec_uid") == owner_sec:
            continue
        if user_id not in {"self", ""} and item.get("sec_uid") == user_id:
            continue
        if not item.get("nickname") and not item.get("unique_id"):
            continue
        items_map[item["sec_uid"]] = item


def _update_paging(data: Any, stats: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        return
    if "has_more" in data:
        stats["has_more"] = data.get("has_more")
    for key in ("total", "mix_count"):
        val = data.get(key)
        if isinstance(val, int) and val > 0:
            stats["total"] = val
            break


def _has_more_false(stats: dict[str, Any] | None) -> bool:
    if not stats or "has_more" not in stats:
        return False
    return stats.get("has_more") in (0, False, "0", "false", "False")


def _parsed_label(now: int, count: int, stats: dict[str, Any] | None) -> str:
    if count > 0:
        return f"{now}/{count}"
    total = int((stats or {}).get("total") or 0)
    if total > 0:
        return f"{now}/{total}"
    return str(now)


def _take_items(items_map: dict, count: int) -> list:
    items = list(items_map.values())
    if count > 0:
        return items[:count]
    return items


def _scroll_until(
    page,
    items_map: dict,
    count: int,
    *,
    press_down: bool = False,
    scroll_fn: Callable[[Any], None] | None = None,
    click_feed: bool = False,
    stats: dict[str, Any] | None = None,
) -> None:
    if click_feed:
        try:
            page.mouse.click(700, 420)
        except Exception:
            pass
    last_count = len(items_map)
    stagnant = 0
    unlimited = count <= 0
    total_hint = int((stats or {}).get("total") or 0)
    if unlimited:
        max_rounds = max(total_hint * 3, 10000)
    else:
        max_rounds = max(count + 40, 80)
    print(f"  parsed {_parsed_label(len(items_map), count, stats)}", flush=True)
    for round_i in range(max_rounds):
        now = len(items_map)
        if count > 0 and now >= count:
            break
        total_hint = int((stats or {}).get("total") or 0)
        if unlimited and total_hint and now >= total_hint:
            break
        if press_down:
            try:
                page.keyboard.press("ArrowDown")
            except Exception:
                pass
        if scroll_fn:
            scroll_fn(page)
        else:
            try:
                page.mouse.wheel(0, 2400)
            except Exception:
                pass
        page.wait_for_timeout(650 if stagnant < 8 else 1100)
        now = len(items_map)
        if now != last_count:
            last_count = now
            stagnant = 0
            print(f"  parsed {_parsed_label(now, count, stats)}", flush=True)
        else:
            stagnant += 1
            if round_i % 8 == 0:
                print(f"  parsed {_parsed_label(now, count, stats)}", flush=True)
        if _has_more_false(stats) and stagnant >= 4 and now > 0:
            break
        if stagnant >= 25 and now > 0:
            break
        if now == 0 and stagnant >= 20:
            break


def fetch_logged_in_feed(
    cookies_path: Path,
    count: int = 100,
    headed: bool = False,
) -> dict[str, Any]:
    start_url = "https://www.douyin.com/?recommend=1"
    items_map: dict[str, dict[str, Any]] = {}
    video_hrefs: list[str] = []
    stats = {"hinted": 0}

    def ingest(data: Any) -> None:
        _update_paging(data, stats)
        for item in parse_feed_payload(data):
            items_map[item["id"]] = item

    def after_goto(page) -> None:
        _ingest_page_state(page, ingest)

    def drive(page) -> None:
        _scroll_until(
            page, items_map, count, press_down=True, click_feed=True, stats=stats
        )
        video_hrefs.extend(_collect_video_hrefs(page))

    _logged_in_session(
        cookies_path,
        start_url,
        headed=headed,
        abort_images=True,
        on_response=_make_on_response(
            ingest, FEED_HINTS, ("aweme", "feed", "recommend"), stats
        ),
        after_goto=after_goto,
        drive=drive,
        login_ok="recommend",
    )

    items = _take_items(items_map, count)
    if not items and video_hrefs:
        ids = []
        seen_href: set[str] = set()
        for href in video_hrefs:
            m = re.search(r"/video/(\d{5,})", href)
            if m and m.group(1) not in seen_href:
                seen_href.add(m.group(1))
                ids.append(m.group(1))
        die(
            "已登录打开推荐页，但没有拦到带播放地址的 feed。\n"
            f"页面上看到 {len(ids)} 个作品链接。请确认 cookie.txt 含 sessionid 后重试，或加 --headed 看浏览器。"
        )
    if not items:
        die("没有拦到登录推荐。加 --headed 查看是否已登录，或重新导出 cookies.txt")
    if count > 0 and len(items) < count:
        print(f"warning: only parsed {len(items)}/{count} logged-in recommends", flush=True)
    return {
        "kind": "feed",
        "id": "recommend-login",
        "url": start_url,
        "logged_in": True,
        "count": len(items),
        "items": items,
    }


def fetch_user_posts(
    cookies_path: Path,
    user_id: str,
    count: int = 0,
    headed: bool = False,
) -> dict[str, Any]:
    start_url = f"https://www.douyin.com/user/{user_id}"
    items_map: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"hinted": 0}

    def ingest(data: Any) -> None:
        _update_paging(data, stats)
        prof = parse_profile_payload(data)
        if _author_matches(prof, user_id):
            stats["author"] = prof
        for item in parse_feed_payload(data):
            items_map[item["id"]] = item

    def after_goto(page) -> None:
        if _click_first(page, POST_TAB_SELECTORS):
            print("  tab: 作品", flush=True)
            page.wait_for_timeout(1200)
        _ingest_page_state(page, ingest)

    def drive(page) -> None:
        _scroll_until(page, items_map, count, scroll_fn=_scroll_user_grid, stats=stats)

    _logged_in_session(
        cookies_path,
        start_url,
        headed=headed,
        abort_images=False,
        on_response=_make_on_response(
            ingest,
            POST_HINTS + PROFILE_HINTS,
            ("aweme/post", "user/profile"),
            stats,
        ),
        after_goto=after_goto,
        drive=drive,
    )

    items = _take_items(items_map, count)
    if not items:
        die(
            f"打开了用户主页 {start_url}，但没有拦到带播放地址的作品。\n"
            "可能是私密账号、仅粉丝可见，或页面未加载完。加 --headed 查看。"
        )
    if count > 0 and len(items) < count:
        print(f"warning: only parsed {len(items)}/{count} user posts", flush=True)
    else:
        print(f"parsed all {len(items)} user posts", flush=True)
    out = {
        "kind": "user",
        "id": user_id,
        "url": start_url,
        "logged_in": True,
        "count": len(items),
        "items": items,
    }
    if stats.get("author"):
        out["author"] = stats["author"]
    return out


def fetch_likes(
    cookies_path: Path,
    user_id: str = "self",
    count: int = 0,
    headed: bool = False,
) -> dict[str, Any]:
    start_url = f"https://www.douyin.com/user/{user_id}?showTab=like"
    items_map: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"hinted": 0}

    def ingest(data: Any) -> None:
        _update_paging(data, stats)
        if isinstance(data, dict):
            owner_sec = str(data.get("sec_uid") or "")
            if user_id not in {"self", ""} and owner_sec and owner_sec != user_id:
                return
        prof = parse_profile_payload(data)
        if _author_matches(prof, user_id):
            stats["author"] = prof
        for item in parse_feed_payload(data):
            items_map[item["id"]] = item

    def after_goto(page) -> None:
        if _click_first(page, LIKE_TAB_SELECTORS):
            print("  tab: 喜欢", flush=True)
            page.wait_for_timeout(1500)
        _ingest_page_state(page, ingest)

    def drive(page) -> None:
        _scroll_until(page, items_map, count, scroll_fn=_scroll_user_grid, stats=stats)

    _logged_in_session(
        cookies_path,
        start_url,
        headed=headed,
        abort_images=False,
        on_response=_make_on_response(
            ingest,
            LIKE_HINTS + PROFILE_HINTS,
            ("aweme/favorite", "aweme/like", "favoritelist", "user/profile"),
            stats,
            strict_hint=True,
        ),
        after_goto=after_goto,
        drive=drive,
    )

    items = _take_items(items_map, count)
    if not items:
        print(
            "warning: no liked videos (empty, private list, or likes tab did not load)",
            flush=True,
        )
    elif count > 0 and len(items) < count:
        print(f"warning: only parsed {len(items)}/{count} liked videos", flush=True)
    else:
        print(f"parsed all {len(items)} liked videos", flush=True)
    out = {
        "kind": "like",
        "id": user_id,
        "url": start_url,
        "logged_in": True,
        "count": len(items),
        "items": items,
    }
    if stats.get("author"):
        out["author"] = stats["author"]
    return out


def fetch_following(
    cookies_path: Path,
    user_id: str = "self",
    count: int = 0,
    headed: bool = False,
) -> dict[str, Any]:
    start_url = f"https://www.douyin.com/user/{user_id}"
    items_map: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"hinted": 0}

    def ingest(data: Any) -> None:
        _ingest_follow_payload(data, stats, items_map, user_id)

    def after_goto(page) -> None:
        if _open_follow_list(page):
            print("  open: 关注列表", flush=True)
            page.wait_for_timeout(2500)
        else:
            print("  warning: following panel did not open", flush=True)

    def scroll_and_dom(page) -> None:
        _scroll_follow_panel(page)
        skip = user_id if user_id not in {"self", ""} else ""
        for item in _collect_panel_users(page, skip):
            items_map.setdefault(item["sec_uid"], item)

    def drive(page) -> None:
        scroll_and_dom(page)
        if not items_map and user_id not in {"self", ""}:
            print("  following list not available on this page", flush=True)
            return
        _scroll_until(page, items_map, count, scroll_fn=scroll_and_dom, stats=stats)

    _logged_in_session(
        cookies_path,
        start_url,
        headed=headed,
        abort_images=False,
        abort_media=False,
        on_response=_make_on_response(
            ingest, FOLLOWING_HINTS + PROFILE_HINTS, (), stats, strict_hint=True
        ),
        after_goto=after_goto,
        drive=drive,
    )

    items = _take_items(items_map, count)
    is_self = user_id in {"self", ""}
    if not items and stats.get("hinted"):
        print("warning: following list empty (private or no users)", flush=True)
    elif not items:
        msg = (
            f"打开了 {start_url}，但没有拦到关注列表。\n"
            "对方可能已关闭公开关注，或需要加 --headed 点开主页「关注」数字。"
        )
        if is_self:
            die(msg)
        print(f"warning: {msg}", flush=True)
    elif count > 0 and len(items) < count:
        print(f"warning: only parsed {len(items)}/{count} following users", flush=True)
    else:
        print(f"parsed all {len(items)} following users", flush=True)
    out = {
        "kind": "following",
        "id": user_id,
        "url": start_url,
        "logged_in": True,
        "count": len(items),
        "items": items,
    }
    if stats.get("author"):
        out["author"] = stats["author"]
    return out


def _finish_user_list(
    items: list,
    count: int,
    stats: dict[str, Any],
    *,
    kind: str,
    user_id: str,
    start_url: str,
    label: str,
) -> dict[str, Any]:
    is_self = user_id in {"self", ""}
    if not items and stats.get("hinted"):
        print(f"warning: {label} list empty (private or no users)", flush=True)
    elif not items:
        msg = (
            f"打开了 {start_url}，但没有拦到{label}列表。\n"
            f"对方可能已关闭公开{label}，或需要加 --headed 查看。"
        )
        if is_self:
            die(msg)
        print(f"warning: {msg}", flush=True)
    elif count > 0 and len(items) < count:
        print(f"warning: only parsed {len(items)}/{count} {label} users", flush=True)
    else:
        print(f"parsed all {len(items)} {label} users", flush=True)
    out = {
        "kind": kind,
        "id": user_id,
        "url": start_url,
        "logged_in": True,
        "count": len(items),
        "items": items,
    }
    if stats.get("author"):
        out["author"] = stats["author"]
    return out


def fetch_followers(
    cookies_path: Path,
    user_id: str = "self",
    count: int = 0,
    headed: bool = False,
) -> dict[str, Any]:
    start_url = f"https://www.douyin.com/user/{user_id}"
    items_map: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"hinted": 0}

    def ingest(data: Any) -> None:
        _ingest_follow_payload(data, stats, items_map, user_id)

    def after_goto(page) -> None:
        if _open_follower_list(page):
            print("  open: 粉丝列表", flush=True)
            page.wait_for_timeout(2500)
        else:
            print("  warning: followers panel did not open", flush=True)

    def scroll_and_dom(page) -> None:
        _scroll_follow_panel(page)
        skip = user_id if user_id not in {"self", ""} else ""
        for item in _collect_panel_users(page, skip):
            items_map.setdefault(item["sec_uid"], item)

    def drive(page) -> None:
        scroll_and_dom(page)
        if not items_map and user_id not in {"self", ""}:
            print("  followers list not available on this page", flush=True)
            return
        _scroll_until(page, items_map, count, scroll_fn=scroll_and_dom, stats=stats)

    _logged_in_session(
        cookies_path,
        start_url,
        headed=headed,
        abort_images=False,
        abort_media=False,
        on_response=_make_on_response(
            ingest, FOLLOWER_HINTS + PROFILE_HINTS, (), stats, strict_hint=True
        ),
        after_goto=after_goto,
        drive=drive,
    )
    return _finish_user_list(
        _take_items(items_map, count),
        count,
        stats,
        kind="followers",
        user_id=user_id,
        start_url=start_url,
        label="粉丝",
    )


def fetch_follow_feed(
    cookies_path: Path,
    count: int = 0,
    headed: bool = False,
) -> dict[str, Any]:
    start_url = "https://www.douyin.com/follow"
    items_map: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"hinted": 0}

    def ingest(data: Any) -> None:
        _update_paging(data, stats)
        for item in parse_feed_payload(data):
            items_map[item["id"]] = item

    def after_goto(page) -> None:
        _ingest_page_state(page, ingest)

    def drive(page) -> None:
        _scroll_until(
            page, items_map, count, press_down=True, click_feed=True, stats=stats
        )

    _logged_in_session(
        cookies_path,
        start_url,
        headed=headed,
        abort_images=True,
        on_response=_make_on_response(
            ingest, FOLLOW_FEED_HINTS, ("follow/feed",), stats
        ),
        after_goto=after_goto,
        drive=drive,
        login_ok="follow",
    )
    items = _take_items(items_map, count)
    if not items:
        die(
            "打开了关注作品流，但没有拦到带播放地址的视频。加 --headed 查看是否已登录。"
        )
    if count > 0 and len(items) < count:
        print(f"warning: only parsed {len(items)}/{count} follow-feed videos", flush=True)
    else:
        print(f"parsed all {len(items)} follow-feed videos", flush=True)
    return {
        "kind": "follow_feed",
        "id": "follow-feed",
        "url": start_url,
        "logged_in": True,
        "count": len(items),
        "items": items,
    }


def fetch_hashtag(
    cookies_path: Path,
    tag: str,
    count: int = 0,
    headed: bool = False,
) -> dict[str, Any]:
    start_url = f"https://www.douyin.com/hashtag/{tag}"
    search_url = f"https://www.douyin.com/search/{tag}?type=video"
    items_map: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"hinted": 0}
    harvested: list[str] = []

    def ingest(data: Any) -> None:
        _update_paging(data, stats)
        for item in parse_feed_payload(data):
            items_map[item["id"]] = item

    def harvest(page) -> None:
        for href in _collect_video_hrefs(page):
            if "baiduspider" in (href or "").lower():
                continue
            m = re.search(r"/video/(\d{5,})", href or "")
            if m and m.group(1) not in harvested:
                harvested.append(m.group(1))

    def after_goto(page) -> None:
        _ingest_page_state(page, ingest)
        _click_first(
            page,
            (
                'span:has-text("视频")',
                'div[role="tab"]:has-text("视频")',
                'span:has-text("综合")',
            ),
        )
        harvest(page)
        if items_map:
            return
        print("  fallback: search page", flush=True)
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            _dismiss_popups(page)
            _ingest_page_state(page, ingest)
            _click_first(page, ('span:has-text("视频")', 'div[role="tab"]:has-text("视频")'))
            harvest(page)
        except Exception:
            pass

    def drive(page) -> None:
        if items_map:
            _scroll_until(page, items_map, count, scroll_fn=_scroll_user_grid, stats=stats)
            return
        harvest(page)
        ids = list(harvested)
        if not ids:
            _scroll_until(page, items_map, count, scroll_fn=_scroll_user_grid, stats=stats)
            harvest(page)
            ids = list(harvested)
        if items_map or not ids:
            return
        limit = count if count > 0 else min(len(ids), 40)
        print(f"  fallback: open {min(len(ids), limit)} video pages", flush=True)
        for vid in ids:
            if count > 0 and len(items_map) >= count:
                break
            if len(items_map) >= limit:
                break
            try:
                page.goto(
                    f"https://www.douyin.com/video/{vid}",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                page.wait_for_timeout(1800)
            except Exception:
                continue

    _logged_in_session(
        cookies_path,
        start_url,
        headed=headed,
        abort_images=False,
        abort_media=False,
        on_response=_make_on_response(
            ingest,
            HASHTAG_HINTS + DETAIL_HINTS,
            ("challenge", "hashtag", "search/item", "aweme/detail"),
            stats,
        ),
        after_goto=after_goto,
        drive=drive,
    )
    items = _take_items(items_map, count)
    if not items:
        die(
            f"打开了话题页 {start_url}，但没有拦到带播放地址的作品。加 --headed 查看。"
        )
    if count > 0 and len(items) < count:
        print(f"warning: only parsed {len(items)}/{count} hashtag videos", flush=True)
    else:
        print(f"parsed all {len(items)} hashtag videos", flush=True)
    return {
        "kind": "hashtag",
        "id": tag,
        "url": start_url,
        "logged_in": True,
        "count": len(items),
        "items": items,
    }


def fetch_video_page(
    cookies_path: Path,
    video_id: str,
    *,
    related: bool = False,
    count: int = 0,
    headed: bool = False,
) -> dict[str, Any]:
    start_url = f"https://www.douyin.com/video/{video_id}"
    detail: dict[str, Any] = {}
    related_map: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"hinted": 0}

    def ingest(data: Any) -> None:
        _update_paging(data, stats)
        for item in parse_feed_payload(data):
            if item.get("id") == video_id:
                detail.update(item)
            elif related:
                related_map[item["id"]] = item
        prof = parse_profile_payload(data)
        if (
            prof
            and detail.get("sec_uid")
            and prof.get("sec_uid") == detail.get("sec_uid")
        ):
            stats["author"] = prof

    def after_goto(page) -> None:
        _ingest_page_state(page, ingest)
        try:
            page.mouse.click(700, 420)
        except Exception:
            pass

    def drive(page) -> None:
        if related:
            _scroll_until(
                page, related_map, count, press_down=True, click_feed=False, stats=stats
            )
        else:
            page.wait_for_timeout(2000)

    hints = DETAIL_HINTS + RELATED_HINTS + PROFILE_HINTS
    extra = ("aweme/detail", "aweme/related", "user/profile")
    _logged_in_session(
        cookies_path,
        start_url,
        headed=headed,
        abort_images=False,
        abort_media=True,
        on_response=_make_on_response(ingest, hints, extra, stats),
        after_goto=after_goto,
        drive=drive,
    )
    if not detail:
        die(
            f"打开了作品页 {start_url}，但没有拦到带播放地址的详情。加 --headed 查看。"
        )
    related_items = _take_items(related_map, count) if related else list(related_map.values())
    if related:
        if count > 0 and len(related_items) < count:
            print(
                f"warning: only parsed {len(related_items)}/{count} related videos",
                flush=True,
            )
        else:
            print(f"parsed all {len(related_items)} related videos", flush=True)
    out: dict[str, Any] = {
        "kind": "related" if related else "video",
        "id": video_id,
        "url": start_url,
        "logged_in": True,
        "detail": detail,
        "count": len(related_items) if related else 1,
        "items": ([detail] + related_items) if related else [detail],
    }
    if detail.get("author_profile"):
        out["author"] = detail["author_profile"]
    if stats.get("author"):
        merged = dict(out.get("author") or {})
        merged.update({k: v for k, v in stats["author"].items() if v not in (None, "")})
        out["author"] = merged
    return out
