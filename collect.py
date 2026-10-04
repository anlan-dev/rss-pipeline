# -*- coding: utf-8 -*-
"""RSS 采集管线：拉取 → 解析(RSS+Atom) → 标准化 → 去重 → 规则过滤 → 输出 JSON + Markdown 日报。

用法：
    python collect.py                  # 全量采集；读取 sources.json，缺失则回退 sources.example.json
    python collect.py --dry            # 只解析不落盘，用于连通性检查
    python collect.py --out-dir PATH   # 指定输出目录（默认 ./out）

依赖：仅 Python 标准库，无需第三方包。
"""
import argparse
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SOURCES_FILE = BASE_DIR / "sources.json"
SOURCES_EXAMPLE_FILE = BASE_DIR / "sources.example.json"
DEFAULT_OUT_DIR = BASE_DIR / "out"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RSSPipeline/1.0"

ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _text(elem, tag):
    node = elem.find(tag)
    return node.text.strip() if node is not None and node.text else ""


def _iso(dt_str):
    """把各种日期字符串尽量归一化为 ISO-8601（无时区则按 UTC）。"""
    if not dt_str:
        return ""
    try:
        return parsedate_to_datetime(dt_str).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    s = dt_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()
    except ValueError:
        return dt_str


def parse_feed(xml_text):
    """把 RSS 或 Atom XML 解析为原始条目列表。

    返回 [{title, link, guid, published, summary}]，published 为 ISO 字符串。
    """
    root = ET.fromstring(xml_text)
    items = []

    # Atom：feed/entry
    entries = root.findall(f"{ATOM_NS}entry")
    if entries:
        for e in entries:
            link = e.find(f"{ATOM_NS}link")
            href = link.get("href") if link is not None else ""
            items.append({
                "title": _text(e, f"{ATOM_NS}title"),
                "link": href,
                "guid": _text(e, f"{ATOM_NS}id"),
                "published": _iso(_text(e, f"{ATOM_NS}updated")),
                "summary": _text(e, f"{ATOM_NS}summary"),
            })
        return items

    # RSS：channel/item（含去命名空间兜底）
    channel = root.find("channel")
    container = channel if channel is not None else root
    for item in container.findall("item"):
        items.append({
            "title": _text(item, "title"),
            "link": _text(item, "link"),
            "guid": _text(item, "guid"),
            "published": _iso(_text(item, "pubDate")),
            "summary": _text(item, "description"),
        })
    return items


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _date_from_link(link):
    """部分 feed（如 RSSHub 的美团路由）不带日期字段，从链接路径兜底提取日期。"""
    m = re.search(r"/(\d{4})[-/](\d{2})[-/](\d{2})", link or "")
    if not m:
        return ""
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T00:00:00+00:00"


def normalize_entry(raw, feed):
    """把原始条目标准化为系统格式，补充来源元信息。"""
    title = _strip_html(raw.get("title", ""))
    link = raw.get("link", "")
    guid = raw.get("guid", "")
    entry_id = guid or link or title
    published = raw.get("published", "") or _date_from_link(link)
    return {
        "id": entry_id,
        "title": title,
        "link": link,
        "published": published,
        "summary": _strip_html(raw.get("summary", ""))[:500],
        "source_id": feed["id"],
        "source_name": feed["name"],
        "category": feed["category"],
        "tier": feed.get("tier", ""),
    }


def dedupe(entries, seen):
    """按 id 去重；seen 为跨会话已见过的 id 集合。返回 (新条目, 更新后的 seen)。"""
    kept = []
    for e in entries:
        if e["id"] and e["id"] in seen:
            continue
        if e["id"]:
            seen.add(e["id"])
        kept.append(e)
    return kept, seen


def apply_filter(entries, feed):
    """规则过滤：title_blacklist 命中则丢弃；whitelist 非空时仅保留命中。"""
    blacklist = feed.get("filters", {}).get("title_blacklist", [])
    whitelist = feed.get("filters", {}).get("title_whitelist", [])
    kept, dropped = [], []
    for e in entries:
        t = e.get("title", "")
        if blacklist and any(k in t for k in blacklist):
            e["filtered"] = True
            e["filter_reason"] = "blacklist"
            dropped.append(e)
            continue
        if whitelist and not any(k in t for k in whitelist):
            e["filtered"] = True
            e["filter_reason"] = "whitelist"
            dropped.append(e)
            continue
        kept.append(e)
    return kept, dropped


def _encode_url(url):
    """对 URL 中的非 ASCII 字符做百分号编码，保留已编码结构与保留字符。"""
    from urllib.parse import quote
    return quote(url, safe=":/?&=#%+")


def fetch(url, timeout=20, retries=1):
    """抓取 feed 内容；遇网络抖动（连接重置/超时）重试 retries 次。"""
    last_exc = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(2)
        try:
            req = urllib.request.Request(_encode_url(url), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            last_exc = exc
            continue
    raise last_exc


def build_digest(entries, stats, digest=None):
    """生成 Markdown 日报。digest 可选配置：{title, tags}。"""
    cfg = digest or {}
    title = cfg.get("title", "RSS 信息日报")
    tags = cfg.get("tags", ["rss", "digest"])
    today = datetime.now().strftime("%Y-%m-%d")

    lines = ["---", f'title: "{title} {today}"', f'date: "{today}"', "tags:"]
    lines.extend(f"  - {t}" for t in tags)
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> 采集时间：{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}")
    lines.append(f"> 统计：抓取 {stats.get('total', 0)} · 保留 {stats.get('kept', 0)} · 过滤 {stats.get('dropped', 0)} · 失败 {stats.get('failed', 0)} 源")
    lines.append("")

    by_cat = {}
    for e in entries:
        by_cat.setdefault(e.get("category", "未分类"), []).append(e)

    for cat, rows in sorted(by_cat.items()):
        lines.append(f"## {cat}")
        lines.append("")
        for e in rows:
            date = e.get("published", "")[:10]
            lines.append(f"- [{e['title']}]({e['link']}) — {e['source_name']} · {date}")
        lines.append("")
    return "\n".join(lines)


def load_sources():
    """读取源配置：优先 sources.json，缺失则回退 sources.example.json。"""
    if SOURCES_FILE.exists():
        return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    if SOURCES_EXAMPLE_FILE.exists():
        print(f"[WARN] 未找到 sources.json，回退使用 sources.example.json（"
              f"复制示例配置：cp sources.example.json sources.json）", file=sys.stderr)
        return json.loads(SOURCES_EXAMPLE_FILE.read_text(encoding="utf-8"))
    raise SystemExit("未找到 sources.json 或 sources.example.json")


def load_state(state_file):
    if state_file.exists():
        return set(json.loads(state_file.read_text(encoding="utf-8")))
    return set()


def save_state(seen, state_file):
    state_file.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")


def run(dry=False, out_dir=None):
    out_dir = Path(out_dir) if out_dir else DEFAULT_OUT_DIR
    state_file = out_dir / "state.json"
    latest_file = out_dir / "latest.json"

    config = load_sources()
    feeds = [f for f in config.get("feeds", []) if f.get("enabled", True)]

    seen = load_state(state_file)
    all_kept, all_dropped = [], []
    stats = {"total": 0, "kept": 0, "dropped": 0, "failed": 0}
    errors = []

    for feed in feeds:
        try:
            xml_text = fetch(feed["url"])
        except Exception as exc:  # 单源失败不阻塞整体
            stats["failed"] += 1
            errors.append({"source": feed["id"], "error": str(exc)})
            print(f"[FAIL] {feed['id']}: {exc}", file=sys.stderr)
            continue
        try:
            raw = parse_feed(xml_text.decode("utf-8", errors="replace"))
        except Exception as exc:
            stats["failed"] += 1
            errors.append({"source": feed["id"], "error": f"parse: {exc}"})
            print(f"[FAIL] {feed['id']}: parse {exc}", file=sys.stderr)
            continue
        entries = [normalize_entry(r, feed) for r in raw]
        stats["total"] += len(entries)
        entries, seen = dedupe(entries, seen)
        kept, dropped = apply_filter(entries, feed)
        all_kept.extend(kept)
        all_dropped.extend(dropped)
        print(f"[OK] {feed['id']}: {len(raw)} raw / {len(kept)} kept / {len(dropped)} dropped")

    stats["kept"] = len(all_kept)
    stats["dropped"] = len(all_dropped)

    result = {
        "collected_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "stats": stats,
        "errors": errors,
        "items": all_kept,
    }

    if not dry:
        out_dir.mkdir(parents=True, exist_ok=True)
        latest_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        save_state(seen, state_file)
        digest = build_digest(all_kept, stats, config.get("digest"))
        digest_file = out_dir / f"{datetime.now():%Y-%m-%d}-rss-digest.md"
        digest_file.write_text(digest, encoding="utf-8")
        print(f"\n[WROTE] {latest_file}")
        print(f"[WROTE] {digest_file}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RSS 采集管线")
    parser.add_argument("--dry", action="store_true", help="只解析不落盘")
    parser.add_argument("--out-dir", default=None, help="输出目录（默认 ./out）")
    args = parser.parse_args()
    run(dry=args.dry, out_dir=args.out_dir)
