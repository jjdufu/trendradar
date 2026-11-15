# coding=utf-8
"""Fluid/hybrid email HTML: dense, single column, 100% width, max-width 680px.

Inline CSS plus a small @media block for clients that support it (QQ Mail).
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_DIGEST_SECTIONS: Sequence[Tuple[str, str]] = (
    ("core_trends", "国内热点"),
    ("sentiment_controversy", "国际热点"),
    ("signals", "科技"),
    ("rss_insights", "梗与抽象段子"),
    ("outlook_strategy", "AI 圈动态"),
)

_MAX_MORE_PER_SOURCE = 3

# Common source labels -> possible standalone name fragments for URL lookup
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

        quoted = re.match(r"^[「\"“](.+?)[」\"”][:：]?\s*(.*)$", chunk, re.S)
        at_handle = re.match(
            r"^(@[\w]+(?:\s*[/、,]\s*@[\w]+)*)[:：]?\s*[「\"“]?(.+?)[」\"”]?\s*(.*)$",
            chunk,
            re.S,
        )
        if quoted:
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


def _source_url_map(standalone_data: Optional[Dict]) -> Dict[str, str]:
    """Map source display names / aliases -> a representative URL."""
    mapping: Dict[str, str] = {}
    if not standalone_data:
        return mapping
    for key in ("platforms", "rss_feeds"):
        for src in standalone_data.get(key) or []:
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
    # @handles: match "X @handle"
    if label.startswith("@"):
        handle = label.lstrip("@").lower()
        for name, url in url_map.items():
            if handle in name.lower().replace("@", ""):
                return url
    return ""


def _more_sources(standalone_data: Optional[Dict], limit: int = _MAX_MORE_PER_SOURCE) -> List[Dict[str, Any]]:
    if not standalone_data:
        return []
    groups: List[Dict[str, Any]] = []
    for key in ("platforms", "rss_feeds"):
        for src in standalone_data.get(key) or []:
            name = src.get("name") or src.get("id") or "来源"
            items = []
            for it in (src.get("items") or [])[:limit]:
                title = (it.get("title") or "").strip()
                url = (it.get("url") or "").strip()
                if title:
                    items.append({"title": title, "url": url})
            if items:
                groups.append({"name": name, "items": items})
    return groups


def _fmt_time(when: Optional[datetime]) -> str:
    when = when or datetime.now()
    return f"{when.year}年{when.month}月{when.day}日 {when.strftime('%H:%M')}"


def _source_tags_html(labels: List[str], url_map: Dict[str, str]) -> str:
    if not labels:
        return ""
    bits = []
    for lab in labels:
        url = _lookup_source_url(lab, url_map)
        style = "font-size:12px;line-height:1.5;color:#6b7280;text-decoration:none;"
        if url:
            bits.append(f'<a href="{_esc(url)}" style="{style}">{_esc(lab)}</a>')
        else:
            bits.append(f'<span style="{style}">{_esc(lab)}</span>')
    return " " + " ".join(bits)


def _item_html(title: str, body: str, sources: List[str], url_map: Dict[str, str]) -> str:
    tags = _source_tags_html(sources, url_map)
    body_html = f" {_esc(body)}" if body else ""
    return (
        f'<p style="margin:0 0 7px 0;padding:0;font-size:15px;line-height:1.5;color:#1f2937;">'
        f"<strong style=\"font-weight:600;color:#111827;\">{_esc(title)}</strong>"
        f"{body_html}{tags}</p>"
    )


def render_email_html(
    *,
    report_type: str = "当前榜单",
    generated_at: Optional[datetime] = None,
    ai_analysis: Any = None,
    standalone_data: Optional[Dict] = None,
) -> str:
    when_str = _fmt_time(generated_at)
    url_map = _source_url_map(standalone_data)

    sections: List[str] = []
    has_digest = bool(ai_analysis and getattr(ai_analysis, "success", False))
    if has_digest:
        for attr, title in _DIGEST_SECTIONS:
            raw = getattr(ai_analysis, attr, "") or ""
            items = _parse_digest_items(raw)
            if not items:
                if raw.strip() and "暂无" in raw:
                    sections.append(_section(title, '<p style="margin:0 0 7px 0;font-size:15px;line-height:1.5;color:#6b7280;">本轮暂无突出条目</p>'))
                continue
            inner = "".join(_item_html(h, b, s, url_map) for h, b, s in items)
            sections.append(_section(title, inner))

    if not sections:
        note = "本期速览未生成，下列为精简原文。"
        if ai_analysis and getattr(ai_analysis, "error", None) and not getattr(ai_analysis, "skipped", False):
            note = "本期速览生成失败，下列为精简原文。"
        sections.append(f'<p style="margin:0 0 10px 0;font-size:15px;line-height:1.5;color:#4b5563;">{_esc(note)}</p>')

    more_html = _render_more(_more_sources(standalone_data))

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>TrendRadar 本期速览 · {_esc(report_type)}</title>
  <style type="text/css">
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
    body {{ margin: 0 !important; padding: 0 !important; width: 100% !important; }}
    @media only screen and (max-width: 680px) {{
      .email-container {{ width: 100% !important; max-width: 100% !important; }}
      .email-pad {{ padding-left: 12px !important; padding-right: 12px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;width:100%;background-color:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Hiragino Sans GB','Noto Sans SC','Microsoft YaHei',sans-serif;font-size:15px;line-height:1.5;color:#1f2937;">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="width:100%;border-collapse:collapse;background-color:#f3f4f6;">
    <tr>
      <td align="center" style="padding:8px;width:100%;">
        <!--[if mso]>
        <table role="presentation" width="680" cellspacing="0" cellpadding="0"><tr><td>
        <![endif]-->
        <table role="presentation" class="email-container" cellspacing="0" cellpadding="0" border="0" width="100%" style="width:100%;max-width:680px;margin:0 auto;border-collapse:collapse;background-color:#ffffff;">
          <tr>
            <td class="email-pad" style="padding:12px 16px 8px 16px;border-bottom:1px solid #e5e7eb;">
              <p style="margin:0;font-size:15px;line-height:1.4;font-weight:700;color:#111827;">本期速览 <span style="font-weight:400;font-size:12px;color:#6b7280;">{_esc(report_type)} · {_esc(when_str)}</span></p>
            </td>
          </tr>
          <tr>
            <td class="email-pad" style="padding:10px 16px 4px 16px;">
              {''.join(sections)}
            </td>
          </tr>
          {more_html}
        </table>
        <!--[if mso]></td></tr></table><![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _section(title: str, inner: str) -> str:
    return (
        f'<div style="margin:0 0 10px 0;padding:0;">'
        f'<p style="margin:0 0 4px 0;padding:0;font-size:12px;line-height:1.4;font-weight:700;color:#374151;">{_esc(title)}</p>'
        f"{inner}</div>"
    )


def _render_more(groups: Iterable[Dict[str, Any]]) -> str:
    groups = list(groups)
    if not groups:
        return ""
    blocks: List[str] = []
    for g in groups:
        links = []
        for it in g["items"]:
            title = _esc(it["title"])
            url = it.get("url") or ""
            if url:
                links.append(
                    f'<a href="{_esc(url)}" style="color:#2563eb;text-decoration:none;">{title}</a>'
                )
            else:
                links.append(f'<span style="color:#374151;">{title}</span>')
        blocks.append(
            f'<p style="margin:0 0 5px 0;font-size:13px;line-height:1.45;color:#1f2937;">'
            f'<span style="font-weight:600;color:#4b5563;">{_esc(g["name"])}</span> '
            f'{" · ".join(links)}</p>'
        )
    inner = "".join(blocks)
    return f"""
          <tr>
            <td class="email-pad" style="padding:8px 16px 12px 16px;border-top:1px solid #e5e7eb;">
              <p style="margin:0 0 6px 0;font-size:12px;line-height:1.4;font-weight:700;color:#6b7280;">更多原文（每源前 {_MAX_MORE_PER_SOURCE} 条）</p>
              {inner}
            </td>
          </tr>
"""


def write_email_html(dest: Path, **kwargs: Any) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_email_html(**kwargs), encoding="utf-8")
    return dest
