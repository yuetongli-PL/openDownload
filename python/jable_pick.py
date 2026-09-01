# -*- coding: utf-8 -*-
"""選片：按主題 / 标签组抓取 jable.tv 公开列表。

每个标签列表四个排序：近期最佳 / 最近更新 / 最多觀看 / 最高收藏。
默认翻完全部分页；--pages N 只抓前 N 页。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from jable_hot import TERMS as HOT_TERMS
from jable_hot import crawl_list, fetch_catalog, list_url
from jable_http import warmup
from jable_util import (
    DEFAULT_OUT,
    configure_stdio,
    die,
    launched_bare,
    now_iso,
    print_intro,
    prompt_line,
    safe_filename,
    write_json,
)

PICK_TERMS: dict[str, str] = {
    "post_date_and_popularity": "近期最佳",
    "post_date": "最近更新",
    "video_viewed": "最多觀看",
    "most_favourited": "最高收藏",
}
PICK_TERM_ORDER = tuple(PICK_TERMS.keys())
PICK_TERM_ALIASES = {
    "all": "all",
    "全部": "all",
    "全": "all",
    "post_date_and_popularity": "post_date_and_popularity",
    "近期最佳": "post_date_and_popularity",
    "近期": "post_date_and_popularity",
    "最佳": "post_date_and_popularity",
    "post_date": "post_date",
    "最近更新": "post_date",
    "更新": "post_date",
    "新片": "post_date",
    "video_viewed": "video_viewed",
    "最多觀看": "video_viewed",
    "最多观看": "video_viewed",
    "觀看": "video_viewed",
    "观看": "video_viewed",
    "most_favourited": "most_favourited",
    "最高收藏": "most_favourited",
    "收藏": "most_favourited",
}

# 侧栏「選片」标签组（2026-08-22 首页实抓）
GROUPS: dict[str, list[tuple[str, str]]] = {
    "衣著": [
        ("黑絲", "black-pantyhose"),
        ("過膝襪", "knee-socks"),
        ("運動裝", "sportswear"),
        ("肉絲", "flesh-toned-pantyhose"),
        ("絲襪", "pantyhose"),
        ("眼鏡娘", "glasses"),
        ("獸耳", "kemonomimi"),
        ("漁網", "fishnets"),
        ("水着", "swimsuit"),
        ("校服", "school-uniform"),
        ("旗袍", "cheongsam"),
        ("婚紗", "wedding-dress"),
        ("女僕", "maid"),
        ("和服", "kimono"),
        ("吊帶襪", "stockings"),
        ("兔女郎", "bunny-girl"),
        ("Cosplay", "Cosplay"),
    ],
    "身材": [
        ("黑肉", "suntan"),
        ("長身", "tall"),
        ("軟體", "flexible-body"),
        ("貧乳", "small-tits"),
        ("美腿", "beautiful-leg"),
        ("美尻", "beautiful-butt"),
        ("紋身", "tattoo"),
        ("短髮", "short-hair"),
        ("白虎", "hairless-pussy"),
        ("熟女", "mature-woman"),
        ("巨乳", "big-tits"),
        ("少女", "girl"),
        ("嬌小", "dainty"),
    ],
    "交合": [
        ("顏射", "facial"),
        ("腳交", "footjob"),
        ("肛交", "anal-sex"),
        ("痙攣", "spasms"),
        ("潮吹", "squirting"),
        ("深喉", "deep-throat"),
        ("接吻", "kiss"),
        ("口爆", "cum-in-mouth"),
        ("口交", "blowjob"),
        ("乳交", "tit-wank"),
        ("中出", "creampie"),
    ],
    "玩法": [
        ("露出", "outdoor"),
        ("集團進犯", "gang-intrusion"),
        ("進犯", "intrusion"),
        ("調教", "tune"),
        ("綑綁", "bondage"),
        ("瞬間插入", "quickie"),
        ("痴漢", "chikan"),
        ("痴女", "chizyo"),
        ("男M", "masochism-guy"),
        ("泥醉", "crapulence"),
        ("泡姬", "soapland"),
        ("母乳", "breast-milk"),
        ("放尿", "piss"),
        ("按摩", "massage"),
        ("多P", "groupsex"),
        ("刑具", "grip"),
        ("凌辱", "insult"),
        ("一日十回", "10-times-a-day"),
        ("3P", "3p"),
    ],
    "劇情": [
        ("黑人", "black"),
        ("醜男", "ugly-man"),
        ("誘惑", "temptation"),
        ("親屬", "kinship"),
        ("童貞", "virginity"),
        ("時間停止", "time-stop"),
        ("復仇", "avenge"),
        ("年齡差", "age-difference"),
        ("巨漢", "giant"),
        ("媚藥", "love-potion"),
        ("夫目前犯", "sex-beside-husband"),
        ("出軌", "affair"),
        ("催眠", "hypnosis"),
        ("偷拍", "private-cam"),
        ("下雨天", "rainy-day"),
        ("NTR", "ntr"),
    ],
    "角色": [
        ("風俗娘", "club-hostess-and-sex-worker"),
        ("醫生", "doctor"),
        ("逃犯", "fugitive"),
        ("護士", "nurse"),
        ("老師", "teacher"),
        ("空姐", "flight-attendant"),
        ("球隊經理", "team-manager"),
        ("未亡人", "widow"),
        ("搜查官", "detective"),
        ("情侶", "couple"),
        ("家政婦", "housewife"),
        ("家庭教師", "private-teacher"),
        ("偶像", "idol"),
        ("人妻", "wife"),
        ("主播", "female-anchor"),
        ("OL", "ol"),
    ],
    "地點": [
        ("魔鏡號", "magic-mirror"),
        ("電車", "tram"),
        ("處女", "first-night"),
        ("監獄", "prison"),
        ("溫泉", "hot-spring"),
        ("洗浴場", "bathing-place"),
        ("泳池", "swimming-pool"),
        ("汽車", "car"),
        ("廁所", "toilet"),
        ("學校", "school"),
        ("圖書館", "library"),
        ("健身房", "gym-room"),
        ("便利店", "store"),
    ],
    "雜項": [
        ("錄像", "video-recording"),
        ("處女作/引退作", "debut-retires"),
        ("綜藝", "variety-show"),
        ("節日主題", "festival"),
        ("感謝祭", "thanksgiving"),
        ("4小時以上", "more-than-4-hours"),
    ],
}
GROUP_ALIASES = {
    "衣着": "衣著",
    "情节": "劇情",
    "剧情": "劇情",
    "地点": "地點",
    "杂项": "雜項",
    "主题": "按主題",
    "按主题": "按主題",
    "theme": "按主題",
    "categories": "按主題",
    "女優": "按女優",
    "按女优": "按女優",
    "models": "按女優",
    "新片": "新片優先",
    "latest": "新片優先",
    "latest-updates": "新片優先",
    "热度": "熱度優先",
    "熱度": "熱度優先",
    "hot": "熱度優先",
}
GROUP_ORDER = list(GROUPS.keys()) + ["按主題", "按女優", "新片優先", "熱度優先"]


def all_tags() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for group, tags in GROUPS.items():
        for name, slug in tags:
            rows.append({"group": group, "name": name, "slug": slug, "kind": "tag"})
    return rows


def print_catalog() -> None:
    print("選片标签组（侧栏）", flush=True)
    for group in GROUPS:
        tags = GROUPS[group]
        print(f"\n{group}  {len(tags)}", flush=True)
        for i, (name, slug) in enumerate(tags, start=1):
            print(f"  {i:2}  {name:10}  /tags/{slug}/", flush=True)
    print("\n其它入口", flush=True)
    print("  按主題      /categories/", flush=True)
    print("  按女優      /models/", flush=True)
    print("  新片優先    /latest-updates/", flush=True)
    print("  熱度優先    /hot/", flush=True)


def resolve_group(spec: str) -> str:
    spec = spec.strip()
    if not spec:
        return ""
    if spec in GROUPS or spec in GROUP_ORDER:
        return spec
    if spec in GROUP_ALIASES:
        return GROUP_ALIASES[spec]
    for group in GROUP_ORDER:
        if spec == group or spec.lower() == group.lower():
            return group
    die(f"未知大类：{spec}（用 --list 查看）")
    return ""


def resolve_tag_token(token: str, group: str | None) -> dict[str, str]:
    token = token.strip()
    if not token:
        die("空的子类名")
    pool = all_tags()
    if group and group in GROUPS:
        pool = [r for r in pool if r["group"] == group]
    exact = [
        r
        for r in pool
        if r["name"] == token or r["slug"].lower() == token.lower()
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        preview = ", ".join(f"{r['group']}/{r['name']}" for r in exact)
        die(f"子类不唯一 {token}：{preview}")
    soft = [r for r in pool if token in r["name"] or token.lower() in r["slug"].lower()]
    if len(soft) == 1:
        return soft[0]
    if soft:
        preview = ", ".join(f"{r['group']}/{r['name']}" for r in soft[:8])
        die(f"子类不唯一 {token}：{preview}")
    die(f"未知子类：{token}")
    return {}


def resolve_terms(spec: str, *, hot: bool = False) -> list[str]:
    spec = (spec or "all").strip()
    table = HOT_TERMS if hot else PICK_TERMS
    aliases = PICK_TERM_ALIASES
    if hot:
        from jable_hot import TERM_ALIASES

        aliases = TERM_ALIASES
    key = aliases.get(spec, aliases.get(spec.lower(), spec))
    if key == "all":
        return list(HOT_TERMS if hot else PICK_TERM_ORDER)
    if key in table:
        return [key]
    die("排序必须是 近期最佳/最近更新/最多觀看/最高收藏/全部（熱度優先则是 日/周/月/总）")
    return []


def pick_tags(group: str, tag_spec: str) -> list[dict[str, str]]:
    if group and group not in GROUPS and group not in ("按主題", "按女優", "新片優先", "熱度優先"):
        group = resolve_group(group)
    tokens = [p.strip() for p in tag_spec.split(",") if p.strip()]
    if group in GROUPS and not tokens:
        return [
            {"group": group, "name": name, "slug": slug, "kind": "tag"}
            for name, slug in GROUPS[group]
        ]
    if tokens:
        return [resolve_tag_token(tok, group if group in GROUPS else None) for tok in tokens]
    die("请用 --group 衣著 或 --tag 黑絲（或两者一起）")
    return []


def build_jobs(
    *,
    group: str,
    tags: list[dict[str, str]],
    terms: list[str],
    model: str,
    theme_cats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if group == "熱度優先":
        for term in terms:
            jobs.append(
                {
                    "path": "/hot/",
                    "term": term,
                    "label": f"熱度優先/{HOT_TERMS.get(term, term)}",
                    "subdir": Path("pick") / "hot" / term,
                    "extra": {"scope": "hot", "group": "熱度優先"},
                }
            )
        return jobs
    if group == "新片優先":
        for term in terms:
            jobs.append(
                {
                    "path": "/latest-updates/",
                    "term": term,
                    "label": f"新片優先/{PICK_TERMS.get(term, term)}",
                    "subdir": Path("pick") / "latest" / term,
                    "block_id": "list_videos_latest_videos_list",
                    "extra": {"scope": "latest", "group": "新片優先"},
                }
            )
        return jobs
    if group == "按女優":
        slug = model.strip()
        if not slug:
            die("按女優请加 --model 女优slug，例如 --model yua-mikami")
        for term in terms:
            jobs.append(
                {
                    "path": f"/models/{slug}/",
                    "term": term,
                    "label": f"女優/{slug}/{PICK_TERMS.get(term, term)}",
                    "subdir": Path("pick") / "models" / safe_filename(slug) / term,
                    "extra": {"scope": "models", "group": "按女優", "slug": slug},
                }
            )
        return jobs
    if group == "按主題":
        if not theme_cats:
            die("主题目录为空")
        wanted = {t["slug"].lower() for t in tags} if tags else set()
        for cat in theme_cats:
            if wanted and cat["slug"].lower() not in wanted and cat["name"] not in {t["name"] for t in tags}:
                continue
            for term in terms:
                jobs.append(
                    {
                        "path": f"/categories/{cat['slug']}/",
                        "term": term,
                        "label": f"{cat['name']}/{PICK_TERMS.get(term, term)}",
                        "subdir": Path("pick") / "categories" / cat["slug"] / term,
                        "extra": {
                            "scope": "categories",
                            "group": "按主題",
                            "slug": cat["slug"],
                            "category": cat["name"],
                        },
                    }
                )
        if not jobs:
            die("没有匹配的主题分类")
        return jobs
    for tag in tags:
        for term in terms:
            jobs.append(
                {
                    "path": f"/tags/{tag['slug']}/",
                    "term": term,
                    "label": f"{tag['group']}/{tag['name']}/{PICK_TERMS.get(term, term)}",
                    "subdir": Path("pick") / safe_filename(tag["group"]) / tag["slug"] / term,
                    "extra": {
                        "scope": "tag",
                        "group": tag["group"],
                        "slug": tag["slug"],
                        "category": tag["name"],
                    },
                }
            )
    return jobs


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="抓取 jable.tv 選片标签 / 主题 / 新片列表。")
    p.add_argument("--list", action="store_true", help="打印全部大类和子类")
    p.add_argument("--group", default="", help="大类：衣著/身材/交合/玩法/劇情/角色/地點/雜項/按主題/新片優先/熱度優先/按女優")
    p.add_argument("--tag", default="", help="子类中文名或 slug，逗号分隔；省略则抓该大类全部")
    p.add_argument("--term", default="", help="近期最佳/最近更新/最多觀看/最高收藏/全部")
    p.add_argument("--model", default="", help="按女優时的女优 slug")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--sleep", type=float, default=0.05)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--timeout", type=int, default=40)
    p.add_argument(
        "-p",
        "--pages",
        "--max-pages",
        dest="max_pages",
        type=int,
        default=0,
        help="每个列表前 N 页；默认 0=全部分页",
    )
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--format", default="json,jsonl")
    return p.parse_args(argv)


def parse_formats(raw: str) -> set[str]:
    wanted = {p.strip().lower() for p in (raw or "json,jsonl").split(",") if p.strip()}
    allowed = {"json", "jsonl", "csv"}
    bad = wanted - allowed
    if bad:
        die(f"未知输出格式：{', '.join(sorted(bad))}")
    wanted.add("jsonl")
    return wanted


def main(argv: list[str] | None = None) -> int:
    bare = launched_bare(argv)
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.list:
        print_catalog()
        return 0
    if bare:
        print_intro(
            "選片",
            "按大类+子类抓取标签列表。每个子类四个排序：近期最佳 / 最近更新 / 最多觀看 / 最高收藏。"
            "默认全部分页；指定页数则只抓前 N 页。",
        )
        print_catalog()
        print(flush=True)
    group = args.group.strip()
    tag_spec = args.tag.strip()
    if not group and not tag_spec and not args.model:
        if bare:
            group = prompt_line("请输入大类（如 衣著；回车=衣著）：") or "衣著"
            tag_spec = prompt_line("请输入子类，逗号分隔（回车=该大类全部）：")
        else:
            die("请指定 --group 或 --tag（--list 查看目录）")
    if group:
        group = resolve_group(group)
    term_spec = args.term.strip()
    if not term_spec:
        if bare:
            term_spec = prompt_line("请选择排序 [近期最佳/最近更新/最多觀看/最高收藏/全部]（回车=全部）：") or "all"
        else:
            term_spec = "all"
    if bare:
        line = prompt_line("每个列表抓几页？回车=全部，输入数字=只抓前 N 页：")
        if line:
            try:
                args.max_pages = int(line)
            except ValueError:
                die("页数必须是整数")
    hot = group == "熱度優先"
    if group == "新片優先" and (term_spec or "all") in ("all", "全部", ""):
        terms = ["post_date"]
    else:
        terms = resolve_terms(term_spec, hot=hot)
    tags: list[dict[str, str]] = []
    theme_cats: list[dict[str, Any]] = []
    if group in GROUPS or (tag_spec and group not in ("按主題", "按女優", "新片優先", "熱度優先")):
        tags = pick_tags(group, tag_spec)
        if not group:
            group = tags[0]["group"]
    formats = parse_formats(args.format)
    out_root = Path(args.out)

    warmup()
    if group == "按主題":
        theme_cats = fetch_catalog(out_root, False)
        if tag_spec:
            wanted = {p.strip() for p in tag_spec.split(",") if p.strip()}
            theme_cats = [
                c
                for c in theme_cats
                if c["name"] in wanted or c["slug"] in wanted or c["slug"].lower() in {w.lower() for w in wanted}
            ]
            if not theme_cats:
                die("没有匹配的主题分类")

    jobs = build_jobs(
        group=group,
        tags=tags,
        terms=terms,
        model=args.model,
        theme_cats=theme_cats,
    )
    if not jobs:
        die("没有可执行的任务")
    if args.max_pages > 0:
        print(f"每个列表前 {args.max_pages} 页  共 {len(jobs)} 个列表", flush=True)
    else:
        print(f"每个列表全部分页  共 {len(jobs)} 个列表", flush=True)
    if args.dry_run:
        for job in jobs:
            print(list_url(job["path"], job["term"], 1, async_mode=False))
        return 0

    stamp = date.today().isoformat()
    index: dict[str, Any] = {
        "fetched_at": now_iso(),
        "date": stamp,
        "group": group,
        "terms": [{"term": t, "label": (HOT_TERMS if hot else PICK_TERMS).get(t, t)} for t in terms],
        "jobs": [],
    }
    t0 = time.time()
    for i, job in enumerate(jobs, start=1):
        print(flush=True)
        print(f"[{i}/{len(jobs)}] {job['label']}  {job['path']}  {job['term']}", flush=True)
        dest = out_root / job["subdir"]
        payload = crawl_list(
            path=job["path"],
            term=job["term"],
            label=job["label"],
            out_dir=dest,
            sleep=args.sleep,
            workers=args.workers,
            timeout=args.timeout,
            max_pages=args.max_pages,
            force=args.force,
            formats=formats,
            extra_meta=job.get("extra"),
            block_id=job.get("block_id") or "list_videos_common_videos_list",
        )
        index["jobs"].append(
            {
                "label": job["label"],
                "path": job["path"],
                "term": job["term"],
                "count": payload.get("count"),
                "pages": payload.get("pages"),
                "total_hint": payload.get("total_hint"),
                "out": str(dest / "items.json"),
            }
        )
        write_json(out_root / "pick" / "index.json", index)
    index["elapsed_sec"] = round(time.time() - t0, 1)
    write_json(out_root / "pick" / "index.json", index)
    print(flush=True)
    print(f"完成  {len(index['jobs'])} 个列表  {out_root / 'pick'}", flush=True)
    return 0


if __name__ == "__main__":
    configure_stdio()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"错误：{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
