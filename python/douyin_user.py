# -*- coding: utf-8 -*-
"""指定抖音号：作品、作者资料、公开的喜欢 / 关注 / 粉丝。

独立入口，不影响 douyin.bat / douyin_live.bat。
登录态走 cookie + 官网页面拦截；抖音号解析和评论首页走 ies 公开接口。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from douyin_parse import (
    classify,
    die,
    fetch_comments,
    fetch_user_info,
    set_cookie_file,
)
from douyin_web import (
    cookie_help,
    default_cookie_path,
    fetch_followers,
    fetch_following,
    fetch_likes,
    fetch_user_posts,
)

HERE = Path(__file__).resolve().parent


def _safe_id(value: str) -> str:
    text = re.sub(r"[^\w.-]+", "_", str(value or "unknown")).strip(".")
    return (text or "unknown")[:80]


def _merge_author(base: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(base or {})
    if not extra:
        return out
    keep_unique = out.get("unique_id")
    for key, value in extra.items():
        if value in (None, "", [], {}):
            continue
        if key == "unique_id" and keep_unique:
            continue
        out[key] = value
    return out


def _author_zh(author: dict[str, Any]) -> dict[str, Any]:
    verify = author.get("custom_verify") or author.get("enterprise_verify_reason") or ""
    return {
        "昵称": author.get("nickname"),
        "抖音号": author.get("unique_id"),
        "sec_uid": author.get("sec_uid"),
        "uid": author.get("uid"),
        "签名": author.get("signature"),
        "头像": author.get("avatar"),
        "粉丝数": author.get("follower_count"),
        "关注数": author.get("following_count"),
        "作品数": author.get("aweme_count"),
        "获赞": author.get("total_favorited"),
        "认证": verify,
        "喜欢公开": author.get("show_favorite_list"),
        "主页": author.get("url"),
    }


def _user_zh(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "昵称": item.get("nickname"),
        "抖音号": item.get("unique_id"),
        "sec_uid": item.get("sec_uid"),
        "uid": item.get("uid"),
        "签名": item.get("signature"),
        "头像": item.get("avatar"),
        "粉丝数": item.get("follower_count"),
        "关注数": item.get("following_count"),
        "作品数": item.get("aweme_count"),
        "获赞": item.get("total_favorited"),
        "认证": item.get("custom_verify") or item.get("enterprise_verify_reason") or "",
        "主页": item.get("url"),
    }


def _comment_zh(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "用户": item.get("user"),
        "抖音号": item.get("unique_id"),
        "内容": item.get("text"),
        "点赞量": item.get("digg_count"),
        "回复数": item.get("reply_count"),
        "时间": item.get("create_time"),
        "ip": item.get("ip_label"),
    }


def _work_zh(item: dict[str, Any], comments: list[dict[str, Any]]) -> dict[str, Any]:
    best = item.get("best") or {}
    stats = item.get("statistics") or {}
    topics = item.get("hashtags") or item.get("topics") or item.get("tags") or []
    width, height = best.get("width"), best.get("height")
    clarity = f"{width}x{height}" if width and height else None
    return {
        "id": item.get("id"),
        "标题": item.get("title"),
        "话题": topics,
        "封面": item.get("cover"),
        "可下载": item.get("allow_download"),
        "最高清播放地址": best.get("url"),
        "清晰度": clarity,
        "档位": best.get("gear"),
        "时长": item.get("duration"),
        "点赞量": stats.get("digg_count"),
        "收藏量": stats.get("collect_count"),
        "评论量": stats.get("comment_count"),
        "评论": [_comment_zh(c) for c in comments],
        "分类": item.get("category"),
        "标签": item.get("label"),
        "合集名": item.get("mix"),
        "链接": item.get("url"),
        "发布时间": item.get("create_time"),
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {path}", flush=True)


def normalize_unique_id(raw: str) -> str:
    text = (raw or "").strip().lstrip("@")
    if not text:
        die("need a 抖音号")
    if re.fullmatch(r"https?://\S+", text) or "douyin.com/" in text.lower():
        info = classify(text)
        if info["kind"] in {"user", "like", "following", "followers"}:
            return info["id"]
        die("请输入抖音号或用户主页链接，不是作品/推荐链接")
    if re.fullmatch(r"\d{5,}", text) and len(text) >= 16:
        die("这像作品 id，请输入抖音号（例如 bbj0817_）")
    return text


def resolve_input(raw: str) -> dict[str, Any]:
    ident = normalize_unique_id(raw)
    if ident.startswith("MS4wLjAB"):
        return fetch_user_info(sec_uid=ident)
    return fetch_user_info(unique_id=ident)


def fetch_comments_many(
    video_ids: list[str],
    count: int,
    workers: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {vid: [] for vid in video_ids}
    if count <= 0 or not video_ids:
        return out
    total = len(video_ids)
    done = 0
    print(f"[comments] {total} videos, up to {count} each (first page)", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(fetch_comments, vid, count): vid for vid in video_ids}
        for fut in as_completed(futs):
            vid = futs[fut]
            try:
                out[vid] = fut.result() or []
            except Exception:
                out[vid] = []
            done += 1
            if done == 1 or done % 20 == 0 or done == total:
                got = sum(1 for rows in out.values() if rows)
                print(f"  comments {done}/{total}  with_text={got}", flush=True)
    return out


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch one Douyin user's posts / profile / public likes / following / followers by 抖音号."
    )
    parser.add_argument("unique_id", nargs="?", help="抖音号, e.g. bbj0817_")
    parser.add_argument("--count", type=int, default=0, help="cap each list; 0 = all (default)")
    parser.add_argument(
        "--comments",
        type=int,
        default=20,
        help="comments per video (unsigned first page, typically <=10). 0 = skip",
    )
    parser.add_argument("--headed", action="store_true", help="show browser")
    parser.add_argument("--cookies", help="cookie.txt path")
    parser.add_argument(
        "--download",
        action="store_true",
        help="download all videos without asking",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="save JSON only, skip the download prompt",
    )
    parser.add_argument("--no-likes", action="store_true")
    parser.add_argument("--no-following", action="store_true")
    parser.add_argument("--no-followers", action="store_true")
    parser.add_argument("--json", action="store_true", help="print author JSON at the end")
    return parser.parse_args(argv)


def _privacy_note(kind: str, items: list) -> str:
    if items:
        return str(len(items))
    return f"0（未公开或为空，{kind}）"


def _stdin_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def prompt_download_all(items: list[dict[str, Any]], args: argparse.Namespace) -> bool:
    downloadable = [it for it in items if (it.get("best") or {}).get("url")]
    if not downloadable:
        print("没有可下载的播放地址", flush=True)
        return False
    total = sum(int((it.get("best") or {}).get("size") or 0) for it in downloadable)
    blocked = sum(1 for it in downloadable if it.get("allow_download") is False)
    print(flush=True)
    print("========== 下载 ==========", flush=True)
    size_s = f"，约 {total / 1024 / 1024:.0f} MB" if total > 0 else ""
    print(f"共 {len(downloadable)} 个作品可下载{size_s}（最高清）", flush=True)
    if blocked:
        print(f"其中 {blocked} 个标记不可下载，仍尝试用播放地址拉取", flush=True)
    if args.download:
        return True
    if args.no_download:
        print("skip download (--no-download)", flush=True)
        return False
    if not _stdin_tty():
        print("skip download（非交互；加 --download 下载全部）", flush=True)
        return False
    try:
        ans = input("是否下载全部视频? [y/N]: ").strip().lower()
    except EOFError:
        ans = ""
    return ans in {"y", "yes", "是", "1"}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.download and args.no_download:
        die("use only one of --download / --no-download")
    raw = (args.unique_id or "").strip()
    if not raw:
        try:
            raw = input("抖音号: ").strip()
        except EOFError:
            raw = ""
    if not raw:
        die("need a 抖音号, e.g. bbj0817_")

    print(f"[0/4] resolve {raw}", flush=True)
    author = resolve_input(raw)
    unique = author.get("unique_id") or normalize_unique_id(raw)
    sec_uid = author.get("sec_uid") or ""
    print(f"抖音号: {unique}", flush=True)
    print(f"sec_uid: {sec_uid}", flush=True)
    print(
        f"作者: {author.get('nickname') or '-'}  "
        f"粉丝={author.get('follower_count')}  "
        f"关注={author.get('following_count')}  "
        f"作品={author.get('aweme_count')}",
        flush=True,
    )
    if not sec_uid:
        die("resolve succeeded but sec_uid is empty")

    cookie_path = Path(args.cookies).expanduser() if args.cookies else default_cookie_path()
    if not cookie_path:
        die(cookie_help())
    set_cookie_file(cookie_path)
    print(f"cookies: {cookie_path}", flush=True)

    folder_name = _safe_id(unique if unique and not str(unique).startswith("MS4wLjAB") else sec_uid)
    work = Path.cwd() / "users" / folder_name
    work.mkdir(parents=True, exist_ok=True)
    want = max(0, int(args.count or 0))
    headed = bool(args.headed)

    print("[1/4] 作品 (cookie + 主页拦截)", flush=True)
    posts = fetch_user_posts(cookie_path, sec_uid, want, headed=headed)
    author = _merge_author(author, posts.get("author"))
    items = posts.get("items") or []
    comments_map: dict[str, list[dict[str, Any]]] = {}
    if args.comments > 0:
        comments_map = fetch_comments_many(
            [str(it.get("id") or "") for it in items if it.get("id")],
            args.comments,
        )
    else:
        print("[comments] skip (--comments 0)", flush=True)

    works = [_work_zh(it, comments_map.get(str(it.get("id") or ""), [])) for it in items]
    likes_zh: list[dict[str, Any]] = []
    following_zh: list[dict[str, Any]] = []
    followers_zh: list[dict[str, Any]] = []

    if args.no_likes:
        print("[2/4] 公开喜欢 skip", flush=True)
    else:
        print("[2/4] 公开喜欢", flush=True)
        likes = fetch_likes(cookie_path, sec_uid, want, headed=headed)
        author = _merge_author(author, likes.get("author"))
        likes_zh = [_work_zh(it, []) for it in (likes.get("items") or [])]

    if args.no_following:
        print("[3/4] 公开关注 skip", flush=True)
    else:
        print("[3/4] 公开关注", flush=True)
        following = fetch_following(cookie_path, sec_uid, want, headed=headed)
        author = _merge_author(author, following.get("author"))
        following_zh = [_user_zh(it) for it in (following.get("items") or [])]

    if args.no_followers:
        print("[4/4] 公开粉丝 skip", flush=True)
    else:
        print("[4/4] 公开粉丝", flush=True)
        followers = fetch_followers(cookie_path, sec_uid, want, headed=headed)
        author = _merge_author(author, followers.get("author"))
        followers_zh = [_user_zh(it) for it in (followers.get("items") or [])]

    author_zh = _author_zh(author)
    bundle_works = {
        "kind": "user-works",
        "抖音号": unique,
        "sec_uid": sec_uid,
        "count": len(works),
        "items": works,
    }
    likes_note = None
    if not likes_zh and not args.no_likes:
        if author.get("show_favorite_list") is False:
            likes_note = "喜欢未公开（主页喜欢 Tab 带锁）"
        else:
            likes_note = "未公开或为空"
    following_note = None
    if not following_zh and not args.no_following:
        following_note = "网页未展开关注列表（未公开，或当前精选页点击数字无抽屉）"
    followers_note = None
    if not followers_zh and not args.no_followers:
        followers_note = "网页未展开粉丝列表（未公开，或当前精选页点击数字无抽屉）"
    bundle_likes = {
        "kind": "user-likes",
        "抖音号": unique,
        "sec_uid": sec_uid,
        "count": len(likes_zh),
        "说明": likes_note,
        "items": likes_zh,
    }
    bundle_following = {
        "kind": "user-following",
        "抖音号": unique,
        "sec_uid": sec_uid,
        "关注数": author.get("following_count"),
        "count": len(following_zh),
        "说明": following_note,
        "items": following_zh,
    }
    bundle_followers = {
        "kind": "user-followers",
        "抖音号": unique,
        "sec_uid": sec_uid,
        "粉丝数": author.get("follower_count"),
        "count": len(followers_zh),
        "说明": followers_note,
        "items": followers_zh,
    }

    _write_json(work / "author.json", author_zh)
    _write_json(work / "works.json", bundle_works)
    if not args.no_likes:
        _write_json(work / "likes.json", bundle_likes)
    if not args.no_following:
        _write_json(work / "following.json", bundle_following)
    if not args.no_followers:
        _write_json(work / "followers.json", bundle_followers)

    print(flush=True)
    print("========== 指定用户 ==========", flush=True)
    print(f"作者: {author_zh.get('昵称')}  @{author_zh.get('抖音号')}", flush=True)
    print(
        f"粉丝={author_zh.get('粉丝数')}  关注={author_zh.get('关注数')}  "
        f"作品={author_zh.get('作品数')}  获赞={author_zh.get('获赞')}",
        flush=True,
    )
    print(f"作品: {len(works)}", flush=True)
    for i, item in enumerate(works[:15], 1):
        dur = item.get("时长")
        dur_s = f"{dur:.1f}s" if isinstance(dur, (int, float)) else "-"
        print(
            f"  {i:3d}. {dur_s}  赞={item.get('点赞量')}  藏={item.get('收藏量')}  "
            f"评={item.get('评论量')}  {(item.get('标题') or '')[:40]}",
            flush=True,
        )
    if len(works) > 15:
        print(f"  ... {len(works) - 15} more", flush=True)
    print(f"公开喜欢: {_privacy_note('喜欢', likes_zh)}" + (f"  {likes_note}" if likes_note else ""), flush=True)
    print(
        f"公开关注: {_privacy_note('关注', following_zh)}"
        + (f"  关注数={author.get('following_count')}" if author.get("following_count") is not None else "")
        + (f"  {following_note}" if following_note else ""),
        flush=True,
    )
    print(
        f"公开粉丝: {_privacy_note('粉丝', followers_zh)}"
        + (f"  粉丝数={author.get('follower_count')}" if author.get("follower_count") is not None else "")
        + (f"  {followers_note}" if followers_note else ""),
        flush=True,
    )
    print(f"dir: {work}", flush=True)

    if prompt_download_all(items, args):
        from douyin_run import download_parallel

        print("[download] highest-quality mp4", flush=True)
        saved = download_parallel(items, work)
        print(f"downloaded: {len(saved)} / {len(items)}", flush=True)
    else:
        print("未下载视频（作品列表已保存）", flush=True)

    if args.json:
        print(json.dumps(author_zh, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
