# -*- coding: utf-8 -*-
"""按视频标签把推荐分成大类 + 子类，并过滤。"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

TAG_RE = re.compile(r"#([^\s#]+)")

CATEGORIES = (
    "影视解说",
    "动漫",
    "游戏",
    "科普",
    "教育",
    "财经",
    "vlog",
    "纪录片",
    "竖屏短视频",
    "广告",
    "其他",
)

# (子类, 大类, 优先匹配的视频标签, 标题补充词)
TAG_RULES: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("韩剧", "影视解说", ("韩剧解说", "热门韩剧", "韩剧"), ()),
    ("美剧", "影视解说", ("美剧推荐", "美剧"), ()),
    ("恐怖片", "影视解说", ("抖音午夜放映厅", "恐怖电影解说", "伪纪录恐怖片", "韩国恐怖片", "恐怖片", "恐怖电影"), ()),
    ("悬疑推理", "影视解说", ("犯罪悬疑", "悬疑反转", "悬疑推理", "悬疑", "推理"), ()),
    ("电视剧", "影视解说", ("电视剧重器", "电视剧", "一起追剧"), ()),
    ("动漫解说", "动漫", ("动漫解说", "我在抖音看动漫", "动漫编年史"), ()),
    ("漫画", "动漫", ("漫画解说", "有声漫画", "漫画推荐", "漫画"), ()),
    ("原创动画", "动漫", ("原创动画", "ai漫剧", "ai动画", "漫剧"), ()),
    ("国漫", "动漫", ("国漫", "一人之下"), ()),
    ("二次元", "动漫", ("二次元", "新番", "coser"), ()),
    ("动漫", "动漫", ("动漫",), ()),
    ("我的世界", "游戏", ("我的世界",), ()),
    ("黑神话", "游戏", ("黑神话",), ()),
    ("游戏解说", "游戏", ("游戏解说", "单机游戏", "恐怖游戏"), ("游戏解说",)),
    ("历史", "科普", ("清朝历史", "历史人物", "历史"), ()),
    ("助眠", "科普", ("助眠", "未解之谜"), ()),
    ("科普", "科普", ("科普", "涨知识"), ()),
    ("教育", "教育", ("高中数学", "高一数学", "解题技巧"), ("高中数学", "零基础")),
    ("财经", "财经", ("财经",), ()),
    ("纪录片", "纪录片", ("纪录片",), ()),
    ("vlog", "vlog", ("vlog日常", "vlog旅行记", "vlog"), ("vlog",)),
    ("穿搭", "竖屏短视频", ("穿搭", "御姐", "高颜值美女", "高颜值", "人像摄影"), ()),
    ("电影解说", "影视解说", ("电影解说", "电影推荐"), ("电影解说", "的电影", "电影《", "喜剧片")),
    ("影视解说", "影视解说", ("影视解说", "了不起的精讲团", "一口气看完系列"), ("精讲", "一口气看完")),
)

LABELS = tuple(dict.fromkeys(rule[0] for rule in TAG_RULES)) + (
    "竖屏短视频",
    "广告",
    "其他",
)

ALIASES = {
    "剧": "影视解说",
    "电影": "电影解说",
    "解说": "影视解说",
    "韩剧解说": "韩剧",
    "午夜": "恐怖片",
    "恐怖": "恐怖片",
    "悬疑": "悬疑推理",
    "推理": "悬疑推理",
    "二次元": "二次元",
    "短视频": "竖屏短视频",
    "竖屏": "竖屏",
    "横屏": "横屏",
    "portrait": "竖屏",
    "landscape": "横屏",
    "vertical": "竖屏",
    "horizontal": "横屏",
    "ads": "广告",
    "ad": "广告",
}


def _clean_tag(name: Any) -> str:
    text = str(name or "").strip().lstrip("#")
    if not text or len(text) > 40 or text.startswith("http"):
        return ""
    if text.lower() in {"douyin.com", "null", "none"}:
        return ""
    return text


def _append_tag(bucket: list[str], seen: set[str], name: Any) -> None:
    text = _clean_tag(name)
    if text and text not in seen:
        seen.add(text)
        bucket.append(text)


def extract_topic_fields(aweme: dict[str, Any], title: str) -> dict[str, list[str]]:
    """视频自带话题：挑战话题 cha_list、文案 #标签、平台 video_tag。"""
    topics: list[str] = []
    hashtags: list[str] = []
    video_tags: list[str] = []
    seen_topics: set[str] = set()
    seen_hash: set[str] = set()
    seen_video: set[str] = set()

    for extra in aweme.get("text_extra") or []:
        if not isinstance(extra, dict):
            continue
        if extra.get("type") in (0, "0"):
            continue
        _append_tag(
            hashtags,
            seen_hash,
            extra.get("hashtag_name") or extra.get("hashtagName"),
        )

    for key in ("cha_list", "challenge_list", "challenges"):
        for cha in aweme.get(key) or []:
            if isinstance(cha, dict):
                _append_tag(
                    topics,
                    seen_topics,
                    cha.get("cha_name") or cha.get("chaName") or cha.get("challenge_name"),
                )

    for key in ("video_tag", "video_text", "standard_tag", "tag_list", "aweme_tags"):
        for tag in aweme.get(key) or []:
            if isinstance(tag, dict):
                _append_tag(
                    video_tags,
                    seen_video,
                    tag.get("tag_name") or tag.get("name") or tag.get("title"),
                )
            elif isinstance(tag, str):
                _append_tag(video_tags, seen_video, tag)

    for hit in TAG_RE.findall(title or ""):
        _append_tag(hashtags, seen_hash, hit)

    tags: list[str] = []
    seen: set[str] = set()
    for name in topics + hashtags + video_tags:
        if name not in seen:
            seen.add(name)
            tags.append(name)
    return {
        "topics": topics,
        "hashtags": hashtags,
        "video_tags": video_tags,
        "tags": tags,
    }


def extract_hashtags(aweme: dict[str, Any], title: str) -> list[str]:
    return extract_topic_fields(aweme, title)["tags"]


def item_native_tags(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for key in ("topics", "hashtags", "video_tags", "tags"):
        for tag in item.get(key) or []:
            _append_tag(names, seen, tag)
    for hit in TAG_RE.findall(item.get("title") or ""):
        _append_tag(names, seen, hit)
    return names


def merge_title_tags(item: dict[str, Any]) -> list[str]:
    tags = item_native_tags(item)
    item["tags"] = tags
    if not item.get("hashtags"):
        item["hashtags"] = list(tags)
    return tags


def analyze_native_tags(items: list[dict[str, Any]]) -> dict[str, Any]:
    counter: Counter[str] = Counter()
    videos: dict[str, list[str]] = {}
    missing: list[str] = []
    for item in items:
        names = item_native_tags(item)
        aweme_id = str(item.get("id") or "")
        if not names:
            if aweme_id:
                missing.append(aweme_id)
            continue
        for name in names:
            counter[name] += 1
            videos.setdefault(name, []).append(aweme_id)
    return {
        "videos": len(items),
        "with_tags": len(items) - len(missing),
        "without_tags": missing,
        "unique": len(counter),
        "tags": [
            {"name": name, "count": n, "ids": videos[name]}
            for name, n in counter.most_common()
        ],
    }


def split_csv(text: str | None) -> list[str]:
    if not text:
        return []
    return [part.strip() for part in str(text).replace("，", ",").split(",") if part.strip()]


def resolve_name(name: str) -> str:
    raw = (name or "").strip()
    if raw in CATEGORIES or raw in LABELS or raw in {"横屏", "竖屏"}:
        return raw
    return ALIASES.get(raw) or ALIASES.get(raw.lower()) or raw


def item_orient(item: dict[str, Any]) -> str:
    best = item.get("best") or {}
    w = int(best.get("width") or 0)
    h = int(best.get("height") or 0)
    if h > w > 0:
        return "竖屏"
    if w >= h > 0:
        return "横屏"
    return ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _haystack(item: dict[str, Any]) -> str:
    parts = [item.get("title") or "", item.get("author") or ""]
    parts.extend(item_native_tags(item))
    return "\n".join(parts).lower()


def _tag_hit(needles: tuple[str, ...], tags: list[str]) -> bool:
    norms = [_norm(t) for t in tags]
    for needle in needles:
        n = _norm(needle)
        if not n:
            continue
        for tag in norms:
            if tag == n:
                return True
            if len(n) >= 2 and (tag.startswith(n) or tag.endswith(n)):
                return True
    return False


def _text_hit(needles: tuple[str, ...], text: str) -> bool:
    blob = text.lower()
    return any(word.lower() in blob for word in needles if word)


def _match_rule(item: dict[str, Any], tags: list[str], text: str) -> tuple[str, str] | None:
    for label, parent, tag_names, extra in TAG_RULES:
        if tag_names and _tag_hit(tag_names, tags):
            return label, parent
        if extra and _text_hit(extra, text):
            return label, parent
    return None


def classify_item(item: dict[str, Any]) -> dict[str, Any]:
    item["orient"] = item_orient(item)
    tags = merge_title_tags(item)
    duration = float(item.get("duration") or 0)
    text = _haystack(item)
    if item.get("is_ads"):
        item["category"] = "广告"
        item["label"] = "广告"
        return item
    if item.get("orient") == "竖屏" and duration and duration < 90:
        hit = _match_rule(item, tags, text)
        if hit and hit[1] == "竖屏短视频":
            item["category"] = "竖屏短视频"
            item["label"] = hit[0]
        else:
            item["category"] = "竖屏短视频"
            item["label"] = "竖屏短视频"
        return item
    hit = _match_rule(item, tags, text)
    if hit:
        item["label"], item["category"] = hit
        return item
    item["category"] = "其他"
    item["label"] = "其他"
    return item


def classify_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [classify_item(item) for item in items]


def category_counts(items: list[dict[str, Any]]) -> list[tuple[str, int, str | None]]:
    parents: Counter[str] = Counter()
    children: dict[str, Counter[str]] = {}
    for item in items:
        parent = item.get("category") or "其他"
        label = item.get("label") or parent
        parents[parent] += 1
        children.setdefault(parent, Counter())[label] += 1
    rows: list[tuple[str, int, str | None]] = []
    seen = set()
    for parent in CATEGORIES:
        if not parents.get(parent):
            continue
        seen.add(parent)
        rows.append((parent, parents[parent], None))
        child = children.get(parent) or Counter()
        for label, n in child.most_common():
            if label != parent or len(child) > 1:
                rows.append((label, n, parent))
    for parent, n in parents.items():
        if parent in seen:
            continue
        rows.append((parent, n, None))
    return rows


def tag_counts(items: list[dict[str, Any]], limit: int = 20) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for item in items:
        for tag in item_native_tags(item):
            counter[tag] += 1
    return counter.most_common(limit)


def _names_of(item: dict[str, Any]) -> set[str]:
    native = item_native_tags(item)
    names = {item.get("category") or "", item.get("label") or ""}
    names.update(native)
    names.update(resolve_name(t) for t in native)
    names.discard("")
    return names


def apply_filters(
    items: list[dict[str, Any]],
    *,
    categories: list[str] | None = None,
    exclude: list[str] | None = None,
    tags: list[str] | None = None,
    orient: str | None = None,
    min_duration: float | None = None,
    max_duration: float | None = None,
    keyword: str | None = None,
    author: str | None = None,
) -> list[dict[str, Any]]:
    want = {resolve_name(x) for x in (categories or [])}
    drop = {resolve_name(x) for x in (exclude or [])}
    need_tags = [x.lstrip("#") for x in (tags or []) if x]
    want_orient = resolve_name(orient) if orient else ""
    keys = [k.strip().lower() for k in split_csv(keyword) if k.strip()]
    author_key = (author or "").strip().lower()
    out: list[dict[str, Any]] = []
    for item in items:
        names = _names_of(item)
        if want and not (want & names):
            continue
        if drop and (drop & names):
            continue
        if need_tags and not _tag_hit(tuple(need_tags), item_native_tags(item)):
            continue
        if want_orient in {"横屏", "竖屏"} and item.get("orient") != want_orient:
            continue
        duration = float(item.get("duration") or 0)
        if min_duration is not None and duration < min_duration:
            continue
        if max_duration is not None and duration > max_duration:
            continue
        blob = _haystack(item)
        if keys and not any(k in blob for k in keys):
            continue
        if author_key and author_key not in str(item.get("author") or "").lower():
            continue
        out.append(item)
    return out
