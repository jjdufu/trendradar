# coding=utf-8
"""Tabbed, dense, responsive email HTML (100% width, max-width 680px).

Anchor-link pills jump to sections (works in QQ Mail). Optional :has/:target
switching is progressive enhancement for WebKit clients.
"""

from __future__ import annotations

import html
import re
import ssl
import urllib.request
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif"
C_BG, C_CARD, C_TEXT, C_BODY, C_MUTED = "#f3f4f6", "#ffffff", "#1a1a1a", "#333333", "#888888"
C_LINE, C_TAB_BG, C_TAB_BD, C_ACCENT, C_LINK = "#e8e8e8", "#e8e8e8", "#cfcfcf", "#c62828", "#111111"

_TABS: Sequence[Sequence[Tuple[str, str]]] = (
    (
        ("github", "GitHub 每日热门项目"),
        ("x", "X 平台热点"),
        ("memes", "抽象段子"),
        ("tiktok", "TikTok 热点"),
        ("baidu", "百度热点"),
    ),
    (
        ("domestic", "国内热点"),
        ("international", "国际热点"),
        ("politics", "时政"),
        ("ai", "AI 圈动态"),
        ("tech", "科技"),
    ),
)

_SOURCE_ALIASES = {
    "微博": ("微博", "weibo"),
    "知乎": ("知乎", "zhihu"),
    "头条": ("今日头条", "toutiao", "头条"),
    "百度": ("百度热搜", "baidu", "百度"),
    "抖音": ("抖音", "douyin"),
    "贴吧": ("贴吧", "tieba"),
    "澎湃": ("澎湃新闻", "thepaper", "澎湃"),
    "财联社": ("财联社", "cls"),
    "凤凰": ("凤凰网", "ifeng", "凤凰"),
    "B站": ("bilibili", "B站", "B 站"),
    "HN": ("Hacker News", "hacker-news"),
    "Hacker News": ("Hacker News",),
    "GitHub": ("GitHub",),
    "V2EX": ("V2EX",),
    "IT之家": ("IT之家",),
    "Solidot": ("Solidot",),
    "少数派": ("少数派",),
    "掘金": ("稀土掘金", "掘金"),
    "Reddit": ("Reddit",),
    "Product Hunt": ("Product Hunt",),
    "TikTok": ("TikTok", "tiktok"),
    "华尔街见闻": ("华尔街见闻", "wallstreetcn"),
    "参考消息": ("参考消息", "cankaoxiaoxi"),
    "联合早报": ("联合早报", "zaobao"),
}

_X_HOT_FEED_IDS = {
    "x-picturesfolder", "x-humansnocontext", "x-nocontextmemes", "x-historyinmemes",
    "x-wholesomememe", "x-vidsthatgohard", "x-9gag", "x-nocontextbrits",
    "x-dexerto", "x-babylonbee", "x-aiyutoushushu", "x-xiaosangawa", "x-popcrave",
}


def _esc(text: Any) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _trim_body(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    parts = re.split(r"(?<=[。！？!?])\s*", text)
    parts = [p.strip() for p in parts if p.strip()]
    return parts[0] if parts else text


def _parse_digest_items(text: str) -> List[Tuple[str, str, List[str]]]:
    """Return (headline, body, source_labels) from a section string."""
    if not text:
        return []
    raw = text.strip()
    raw = re.sub(r"^【[^】]+】\s*", "", raw)
    if re.fullmatch(r"本轮暂无突出条目。?", raw):
        return []

    chunks = re.split(r"(?m)^\s*\d+[\.、]\s*", raw)
    chunks = [c.strip() for c in chunks if c.strip()]
    if not chunks:
        chunks = [raw]

    items: List[Tuple[str, str, List[str]]] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        sources: List[str] = []
        src_match = re.search(r"[（(]([^）)]{1,40})[）)]\s*$", chunk)
        if src_match:
            sources = [s.strip() for s in re.split(r"[、,/，|]", src_match.group(1)) if s.strip()]
            chunk = chunk[: src_match.start()].rstrip()

        gh = re.match(r"^([\w.-]+/[\w.-]+)[:：]\s*(.*)$", chunk, re.S)
        tk = re.match(r"^(#[\w\u00c0-\u024f\u3400-\u9fff]+)[:：]\s*(.*)$", chunk, re.S)
        quoted = re.match(r"^[「\"“](.+?)[」\"”][:：]?\s*(.*)$", chunk, re.S)
        at_handle = re.match(
            r"^(@[\w]+(?:\s*[/、,]\s*@[\w]+)*)[:：]?\s*[「\"“]?(.+?)[」\"”]?\s*(.*)$",
            chunk,
            re.S,
        )
        if gh:
            title, body = gh.group(1).strip(), gh.group(2).strip()
        elif tk:
            title, body = tk.group(1).strip(), tk.group(2).strip()
        elif quoted:
            title, body = quoted.group(1).strip(), quoted.group(2).strip()
        elif at_handle:
            who = at_handle.group(1).strip()
            mid = at_handle.group(2).strip()
            rest = at_handle.group(3).strip()
            if len(mid) <= 40:
                title, body = f"{who} {mid}".strip(), rest
            else:
                title, body = who, (mid + " " + rest).strip()
        else:
            lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
            title = lines[0] if lines else chunk
            body = " ".join(lines[1:]) if len(lines) > 1 else ""
            if not body and "。" in title:
                a, b = title.split("。", 1)
                if 2 <= len(a) <= 40:
                    title, body = a, b
        title = re.sub(r"\s+", " ", title).strip(" ：:。")
        body = _trim_body(body)
        if title:
            items.append((title, body, sources))
    return items


def _iter_feeds(standalone_data: Optional[Dict]) -> Iterable[Dict[str, Any]]:
    if not standalone_data:
        return []
    for key in ("platforms", "rss_feeds"):
        for src in standalone_data.get(key) or []:
            yield src


def _source_url_map(standalone_data: Optional[Dict]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for src in _iter_feeds(standalone_data):
        name = (src.get("name") or src.get("id") or "").strip()
        url = ""
        for it in src.get("items") or []:
            if it.get("url"):
                url = it["url"]
                break
        if name and url:
            mapping[name] = url
    return mapping


def _lookup_source_url(label: str, url_map: Dict[str, str]) -> str:
    if label in url_map:
        return url_map[label]
    aliases = _SOURCE_ALIASES.get(label, (label,))
    for name, url in url_map.items():
        lname = name.lower()
        for alias in aliases:
            if alias.lower() in lname or lname in alias.lower():
                return url
        if label.lower() in lname:
            return url
    if label.startswith("@") or label.startswith("#"):
        key = label.lstrip("@#").lower()
        for name, url in url_map.items():
            if key in name.lower().replace("@", "").replace("#", ""):
                return url
    return ""


def _find_item_url(standalone_data: Optional[Dict], title: str) -> str:
    if not standalone_data or not title:
        return ""
    needle = re.sub(r"\s+", " ", title).strip().lower()
    repo = ""
    m = re.search(r"([\w.-]+/[\w.-]+)", title)
    if m:
        repo = m.group(1).lower()
    hashtag = title[1:].lower() if title.startswith("#") else ""
    for src in _iter_feeds(standalone_data):
        for it in src.get("items") or []:
            raw = (it.get("title") or "").strip()
            url = (it.get("url") or "").strip()
            if not url:
                continue
            low = re.sub(r"\s+", " ", raw).lower()
            if needle and (needle == low or needle in low or low in needle):
                return url
            compact = low.replace(" ", "")
            if repo and repo in compact:
                return url
            if repo and repo in url.lower():
                return url
            if hashtag and hashtag == raw.lstrip("#").lower():
                return url
    return ""


def _fmt_time(when: Optional[datetime]) -> str:
    when = when or datetime.now()
    return f"{when.year}年{when.month}月{when.day}日 {when.strftime('%H:%M')}"


@lru_cache(maxsize=1)
def _github_stars_today_map() -> Dict[str, str]:
    """Scrape GitHub trending for 'N stars today'. Soft-fail to empty dict."""
    url = "https://github.com/trending?since=daily"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html",
    }
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
            html_text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        print("[email] GitHub trending stars scrape failed")
        return {}
    mapping: Dict[str, str] = {}
    parts = re.split(r'<h2[^>]*>\s*<a[^>]+href="(/[^"/]+/[^"/]+)"', html_text)
    i = 1
    while i + 1 < len(parts):
        path = parts[i].strip("/")
        rest = parts[i + 1]
        st = re.search(r"([\d,]+)\s+stars?\s+today", rest, re.I)
        if path and st:
            mapping[path.lower()] = st.group(1)
        i += 2
    return mapping


def _normalize_repo(title: str, url: str = "") -> str:
    text = f"{title} {url}"
    m = re.search(r"github\.com/([\w.-]+/[\w.-]+)", text, re.I)
    if m:
        return m.group(1)
    compact = title.replace(" ", "")
    m = re.search(r"\b([\w.-]+)/([\w.-]+)\b", compact)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return ""


def _stars_label(item: Dict[str, Any], repo: str, today_map: Dict[str, str]) -> str:
    """Prefer '★+408 今日' with nowrap at render time. Never shorten 今日 to 今."""
    key = (repo or "").lower()
    raw = today_map.get(key) or item.get("stars_today") or ""
    if raw:
        return "★+" + str(raw) + " 今日"
    extra = item.get("extra") or {}
    info = str(extra.get("info") or "")
    m = re.search(r"([\d,]+)", info)
    if m:
        return "★" + m.group(1)
    return ""


def _item_row(title: str, url: str, line: str, meta: str = "") -> str:
    title = (title or "").strip() or (line or "")[:18]
    line = (line or "").strip()
    if line and (line == title or title.startswith(line) or line.startswith(title)):
        line = ""
    meta_html = ""
    if meta:
        meta_html = (
            '<span style="font-size:12px;line-height:1.4;color:' + C_MUTED +
            ';font-weight:400;white-space:nowrap;display:inline-block;">' + _esc(meta) + "</span>"
        )
    if url:
        title_html = (
            '<a href="' + _esc(url) + '" target="_blank" style="font-size:16px;line-height:1.35;'
            "font-weight:700;color:" + C_LINK + ';text-decoration:none;">' + _esc(title) + "</a>"
        )
    else:
        title_html = (
            '<span style="font-size:16px;line-height:1.35;font-weight:700;color:' +
            C_LINK + ';">' + _esc(title) + "</span>"
        )
    body = ""
    if line:
        body = (
            '<div style="font-size:15px;line-height:1.5;color:' + C_BODY +
            ';font-weight:400;padding-top:1px;">' + _esc(line) + "</div>"
        )
    mid = title_html + (("&nbsp;&nbsp;" + meta_html) if meta_html else "")
    return (
        '<tr><td style="padding:7px 0 8px;border-bottom:1px solid ' + C_LINE +
        ";font-family:" + FONT + ';">'
        '<div style="font-size:16px;line-height:1.35;">' + mid + "</div>" + body + "</td></tr>"
    )


def _section(sid: str, title: str, rows_html: str, empty_note: str = "") -> str:
    inner = rows_html or (
        '<tr><td style="padding:7px 0;font-family:' + FONT + ";font-size:15px;color:" +
        C_MUTED + ';">' + _esc(empty_note or "本轮暂无突出条目") + "</td></tr>"
    )
    return (
        '<table role="presentation" class="panel" id="' + _esc(sid) +
        '" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;margin:0 0 14px;">'
        "<tr><td style=\"padding:12px 0 4px;border-top:2px solid #222;font-family:" + FONT +
        ';font-size:13px;line-height:1.3;font-weight:700;color:' + C_TEXT +
        ';letter-spacing:0.02em;">'
        '<a name="' + _esc(sid) + '" style="color:' + C_TEXT +
        ';text-decoration:none;">' + _esc(title) + "</a>"
        "</td></tr>" + inner + "</table>"
    )


def _pill(sid: str, label: str) -> str:
    return (
        '<a href="#' + _esc(sid) + '" style="display:inline-block;text-decoration:none;font-family:' +
        FONT + ";font-size:12px;line-height:1.2;font-weight:600;color:" + C_TEXT +
        ";background:" + C_TAB_BG + ";border:1px solid " + C_TAB_BD +
        ';border-radius:999px;padding:5px 10px;margin:0 4px 6px 0;white-space:nowrap;">' +
        _esc(label) + "</a>"
    )


def _find_feed(standalone_data: Optional[Dict], *needles: str) -> Optional[Dict[str, Any]]:
    keys = [n.lower() for n in needles]
    for src in _iter_feeds(standalone_data):
        blob = f"{src.get('id','')} {src.get('name','')}".lower()
        if any(k in blob for k in keys):
            return src
    return None


def _rows_from_digest(
    items: List[Tuple[str, str, List[str]]],
    standalone_data: Optional[Dict],
    url_map: Dict[str, str],
) -> str:
    rows = []
    for title, body, sources in items:
        url = _find_item_url(standalone_data, title) or (
            _lookup_source_url(sources[0], url_map) if sources else ""
        )
        meta = " / ".join(sources) if sources else ""
        rows.append(_item_row(title, url, body, meta))
    return "".join(rows)


def _github_rows(ai_items: List[Tuple[str, str, List[str]]], standalone_data: Optional[Dict]) -> str:
    today_map = _github_stars_today_map()
    feed = _find_feed(standalone_data, "github-trending-today", "github trending", "github")
    line_by_repo: Dict[str, str] = {}
    for title, body, _src in ai_items:
        repo = _normalize_repo(title)
        if repo:
            line_by_repo[repo.lower()] = body or ""
    rows = []
    source_items = (feed.get("items") if feed else []) or []
    if source_items:
        for it in source_items:
            title = (it.get("title") or "").strip()
            url = (it.get("url") or "").strip()
            repo = _normalize_repo(title, url)
            key = repo.lower() if repo else title.lower()
            line = line_by_repo.get(key, "")
            if not line:
                line = ((it.get("extra") or {}).get("hover") or "").strip()
            meta = _stars_label(it, repo, today_map)
            display = repo or re.sub(r"\s+", "", title)
            rows.append(_item_row(display, url, line, meta))
    else:
        for title, body, _src in ai_items:
            repo = _normalize_repo(title) or title
            url = _find_item_url(standalone_data, title)
            if not url and "/" in repo:
                url = "https://github.com/" + repo
            meta = _stars_label({}, repo, today_map)
            rows.append(_item_row(repo, url, body, meta))
    return "".join(rows)


def _tiktok_rows(ai_items: List[Tuple[str, str, List[str]]], standalone_data: Optional[Dict]) -> str:
    feed = _find_feed(standalone_data, "tiktok-overseas", "tiktok 海外", "tiktok")
    line_by_tag: Dict[str, str] = {}
    for title, body, _src in ai_items:
        line_by_tag[title.lstrip("#").lower()] = body or title
    rows = []
    source_items = (feed.get("items") if feed else []) or []
    if source_items:
        for it in source_items:
            title = (it.get("title") or "").strip()
            url = (it.get("url") or "").strip()
            tag = title.lstrip("#").lower()
            line = line_by_tag.get(tag, "")
            extra = it.get("extra") or {}
            meta = str(extra.get("info") or "")
            if " · " in meta:
                meta = meta.split(" · ")[0]
            display = title if title.startswith("#") else ("#" + title)
            rows.append(_item_row(display, url, line, meta))
    else:
        for title, body, sources in ai_items:
            url = _find_item_url(standalone_data, title)
            rows.append(_item_row(title, url, body, " / ".join(sources)))
    return "".join(rows)


def _x_rows(ai_items: List[Tuple[str, str, List[str]]], standalone_data: Optional[Dict]) -> str:
    if ai_items:
        return _rows_from_digest(ai_items, standalone_data, _source_url_map(standalone_data))
    rows = []
    for src in _iter_feeds(standalone_data):
        fid = str(src.get("id") or "")
        if fid not in _X_HOT_FEED_IDS:
            continue
        items = src.get("items") or []
        if not items:
            continue
        it = items[0]
        handle = (src.get("name") or fid).replace("X ", "")
        rows.append(_item_row(handle, it.get("url") or "", it.get("title") or "", ""))
    return "".join(rows)


def render_email_html(
    *,
    report_type: str = "当前榜单",
    generated_at: Optional[datetime] = None,
    ai_analysis: Any = None,
    standalone_data: Optional[Dict] = None,
) -> str:
    when_str = _fmt_time(generated_at)
    url_map = _source_url_map(standalone_data)
    has_digest = bool(ai_analysis and getattr(ai_analysis, "success", False))

    def field(*names: str) -> str:
        if not has_digest:
            return ""
        for name in names:
            val = getattr(ai_analysis, name, "") or ""
            if val:
                return val
        return ""

    tab_rows = []
    for row in _TABS:
        pills = "".join(_pill(sid, lab) for sid, lab in row)
        tab_rows.append(
            '<tr><td style="padding:0;font-family:' + FONT +
            ';font-size:0;line-height:0;">' + pills + "</td></tr>"
        )
    tabs_html = (
        '<table role="presentation" class="tabs" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;margin:0 0 8px;">' + "".join(tab_rows) + "</table>"
    )

    sixty_items = _parse_digest_items(field("sixty"))
    sixty_rows = []
    for i, (title, body, sources) in enumerate(sixty_items, 1):
        if body and body not in title and len(title) <= 40:
            text = title + ("。" if not title.endswith(("。", "！", "？", ".", "!", "?")) else "") + body
        else:
            text = title
        url = _find_item_url(standalone_data, title) or (
            _lookup_source_url(sources[0], url_map) if sources else ""
        )
        body_html = _esc(text)
        if url:
            body_html = (
                '<a href="' + _esc(url) + '" target="_blank" style="color:' +
                C_BODY + ';text-decoration:none;">' + body_html + "</a>"
            )
        meta = ""
        if sources:
            meta = (
                '<span style="font-size:12px;color:' + C_MUTED +
                ';padding-left:6px;font-weight:400;">' + _esc(" / ".join(sources)) + "</span>"
            )
        sixty_rows.append(
            '<tr><td valign="top" width="32" style="padding:3px 8px 3px 0;font-family:' + FONT +
            ";font-size:15px;line-height:1.5;font-weight:700;color:" + C_ACCENT +
            ';width:32px;">' + str(i) + ".</td>"
            '<td valign="top" style="padding:3px 0;font-family:' + FONT +
            ";font-size:15px;line-height:1.5;color:" + C_BODY +
            ';font-weight:400;">' + body_html + meta + "</td></tr>"
        )
    if not sixty_rows:
        note = "本期速览未生成。" if not has_digest else "本轮暂无 60 秒摘要。"
        sixty_rows.append(
            '<tr><td colspan="2" style="padding:3px 0;font-family:' + FONT +
            ";font-size:15px;color:" + C_MUTED + ';">' + _esc(note) + "</td></tr>"
        )

    sixty_html = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;margin:0 0 6px;">'
        "<tr><td style=\"padding:0 0 8px;font-family:" + FONT + ';">'
        '<div style="font-size:18px;line-height:1.3;font-weight:800;color:' + C_TEXT +
        ';">每天60秒读懂世界</div>'
        '<div style="font-size:12px;line-height:1.4;color:' + C_MUTED +
        ';padding-top:2px;">' + _esc(report_type) + " · " + _esc(when_str) + "</div>"
        "</td></tr></table>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;margin:0 0 16px;">' + "".join(sixty_rows) + "</table>"
    )

    sections_html = "".join([
        _section("github", "GitHub 每日热门项目", _github_rows(_parse_digest_items(field("github")), standalone_data)),
        _section("x", "X 平台热点", _x_rows(_parse_digest_items(field("x_hot", "x")), standalone_data)),
        _section("memes", "抽象段子", _rows_from_digest(_parse_digest_items(field("rss_insights")), standalone_data, url_map)),
        _section("tiktok", "TikTok 热点", _tiktok_rows(_parse_digest_items(field("tiktok")), standalone_data)),
        _section("baidu", "百度热点", _rows_from_digest(_parse_digest_items(field("baidu")), standalone_data, url_map)),
        _section("domestic", "国内热点", _rows_from_digest(_parse_digest_items(field("core_trends")), standalone_data, url_map)),
        _section("international", "国际热点", _rows_from_digest(_parse_digest_items(field("sentiment_controversy")), standalone_data, url_map)),
        _section("politics", "时政", _rows_from_digest(_parse_digest_items(field("politics")), standalone_data, url_map)),
        _section("ai", "AI 圈动态", _rows_from_digest(_parse_digest_items(field("outlook_strategy")), standalone_data, url_map)),
        _section("tech", "科技", _rows_from_digest(_parse_digest_items(field("signals")), standalone_data, url_map)),
    ])

    style = (
        "<style type=\"text/css\">"
        "html,body { margin:0 !important; padding:0 !important; width:100% !important; background:" + C_BG + " !important; }"
        "a { color:" + C_LINK + "; }"
        ".email-container { width:100% !important; max-width:680px !important; }"
        "body:has(.panel:target) .panel { display:none !important; }"
        ".panel:target { display:block !important; }"
        "@media only screen and (max-width:680px) {"
        ".email-container { width:100% !important; max-width:100% !important; }"
        ".inner { padding:10px 12px !important; }"
        ".tabs a { font-size:11px !important; padding:5px 6px !important; }"
        "}"
        "</style>"
    )

    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, maximum-scale=1\">\n"
        "<meta http-equiv=\"X-UA-Compatible\" content=\"IE=edge\">\n"
        "<meta name=\"color-scheme\" content=\"light\">\n"
        "<title>每天60秒读懂世界 · " + _esc(report_type) + "</title>\n"
        + style + "\n</head>\n"
        "<body style=\"margin:0;padding:0;background:" + C_BG + ";width:100%;font-family:" + FONT +
        ";font-size:15px;line-height:1.5;color:" + C_TEXT + ';">\n'
        '<div style="display:none;max-height:0;overflow:hidden;font-size:1px;line-height:1px;color:' +
        C_BG + ';">每天60秒读懂世界 · ' + _esc(when_str) + "</div>\n"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;background:' + C_BG + ';width:100%;"><tr>'
        '<td align="center" style="padding:8px 8px 16px;">\n'
        "<!--[if mso]><table role=\"presentation\" width=\"680\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\"><tr><td><![endif]-->\n"
        '<table role="presentation" class="email-container" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;width:100%;max-width:680px;background:' + C_CARD +
        ';margin:0 auto;"><tr>'
        '<td class="inner" style="padding:12px 16px 16px;font-family:' + FONT + ';">\n'
        + tabs_html + "\n" + sixty_html + '\n<div id="panels">\n' + sections_html + "\n</div>\n"
        "</td></tr></table>\n"
        "<!--[if mso]></td></tr></table><![endif]-->\n"
        "</td></tr></table>\n</body>\n</html>\n"
    )


def write_email_html(dest: Path, **kwargs: Any) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_email_html(**kwargs), encoding="utf-8")
    return dest
