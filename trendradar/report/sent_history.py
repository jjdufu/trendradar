# coding=utf-8
"""Cross-run sent-history for the email digest.

Persists normalized URL + title hash (+ GitHub repo key) and a timestamp.
Encrypted with XAI_CACHE_PASSPHRASE (openssl aes-256-cbc + pbkdf2), same
scheme as the xAI refresh-token cache. Cache miss or decrypt failure means
send normally.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ENC_PATH = Path(".sent-history/history.enc")
RETENTION_DAYS = 3
MAX_TITLES_FOR_AI = 150
_DROP_QUERY = {
    "fbclid", "gclid", "spm", "from", "ref", "ref_src", "ref_url",
    "igshid", "si", "source", "utm_source", "utm_medium", "utm_campaign",
    "utm_term", "utm_content", "utm_id",
}

_loaded: Optional[List[Dict[str, Any]]] = None
_index: Optional["HistoryIndex"] = None


class HistoryIndex:
    def __init__(self) -> None:
        self.urls: set[str] = set()
        self.title_hashes: set[str] = set()
        self.repos: set[str] = set()
        self.titles: List[str] = []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except Exception:
        return url.lower().rstrip("/")
    scheme = (parts.scheme or "https").lower()
    netloc = (parts.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path or ""
    host = netloc.split(":")[0]
    if host == "github.com" or host.endswith(".github.com"):
        segs = [s for s in path.split("/") if s]
        path = f"/{segs[0]}/{segs[1]}" if len(segs) >= 2 else path.rstrip("/")
        return urlunsplit((scheme, netloc, path, "", ""))
    path = path.rstrip("/")
    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in _DROP_QUERY:
            continue
        kept.append((key, value))
    query = urlencode(kept)
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_title(title: str) -> str:
    text = (title or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip("「」『』“”\"'")


def title_hash(title: str) -> str:
    text = normalize_title(title)
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def repo_key(title: str = "", url: str = "") -> str:
    blob = f"{url or ''} {title or ''}"
    match = re.search(r"github\.com/([\w.-]+)/([\w.-]+)", blob, re.I)
    if match:
        return f"{match.group(1)}/{match.group(2)}".lower()
    compact = (title or "").replace(" ", "")
    match = re.search(r"^#?([\w.-]+)/([\w.-]+)$", compact)
    if match:
        return f"{match.group(1)}/{match.group(2)}".lower()
    return ""


def _passphrase() -> str:
    return (
        os.environ.get("XAI_CACHE_PASSPHRASE")
        or os.environ.get("SENT_HISTORY_PASSPHRASE")
        or ""
    )


def _openssl(data: bytes, *, decrypt: bool) -> bytes:
    passphrase = _passphrase()
    if not passphrase:
        raise RuntimeError("missing XAI_CACHE_PASSPHRASE")
    cmd = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-a", "-A", "-pass", "env:PASS"]
    if decrypt:
        cmd.insert(2, "-d")  # openssl enc -d ...
    else:
        cmd.append("-salt")
    env = os.environ.copy()
    env["PASS"] = passphrase
    result = subprocess.run(cmd, input=data, capture_output=True, env=env)
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", "replace").strip()
        # Never include the passphrase. OpenSSL errors are usually generic.
        raise RuntimeError(err or f"openssl exited {result.returncode}")
    return result.stdout


def _prune(items: Sequence[Dict[str, Any]], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or _now()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    kept: List[Dict[str, Any]] = []
    for item in items:
        ts = _parse_ts(item.get("ts"))
        if ts is None or ts >= cutoff:
            kept.append(item)
    return kept


def _build_index(items: Sequence[Dict[str, Any]]) -> HistoryIndex:
    index = HistoryIndex()
    # Newest first so AI sees recent titles first.
    ordered = sorted(
        items,
        key=lambda it: _parse_ts(it.get("ts")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    for item in ordered:
        url_key = item.get("url_key") or normalize_url(str(item.get("url") or ""))
        if url_key:
            index.urls.add(url_key)
        th = item.get("title_hash") or title_hash(str(item.get("title") or ""))
        if th:
            index.title_hashes.add(th)
        rk = item.get("repo") or repo_key(str(item.get("title") or ""), str(item.get("url") or ""))
        if rk:
            index.repos.add(rk)
        title = str(item.get("title") or "").strip()
        if title:
            index.titles.append(title)
    return index


def is_sent(title: str = "", url: str = "", index: Optional[HistoryIndex] = None) -> bool:
    index = index if index is not None else _index
    if index is None:
        return False
    url_key = normalize_url(url)
    if url_key and url_key in index.urls:
        return True
    th = title_hash(title)
    if th and th in index.title_hashes:
        return True
    rk = repo_key(title, url)
    if rk and rk in index.repos:
        return True
    return False


def load_history(path: Path = ENC_PATH) -> List[Dict[str, Any]]:
    """Load, decrypt, and prune history. Cache miss → empty list."""
    global _loaded, _index
    items: List[Dict[str, Any]] = []
    if path.exists():
        try:
            raw = _openssl(path.read_bytes(), decrypt=True)
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                items = list(data.get("items") or [])
            elif isinstance(data, list):
                items = list(data)
        except Exception as exc:
            print(f"[去重] 历史缓存解密/解析失败，按全新发送（{type(exc).__name__}）")
            items = []
    else:
        print("[去重] 缓存未命中，按全新发送")
    items = _prune(items)
    _loaded = items
    _index = _build_index(items)
    if items:
        print(f"[去重] 已加载近 {RETENTION_DAYS} 日发送历史 {len(items)} 条")
    return items


def titles_for_ai(limit: int = MAX_TITLES_FOR_AI) -> List[str]:
    if _index is None:
        load_history()
    assert _index is not None
    seen = set()
    out: List[str] = []
    for title in _index.titles:
        key = normalize_title(title)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(title if len(title) <= 80 else (title[:79] + "…"))
        if len(out) >= limit:
            break
    return out


def format_sent_titles_prompt(titles: Optional[Sequence[str]] = None) -> str:
    titles = list(titles if titles is not None else titles_for_ai())
    if not titles:
        return "（无，按全新稿处理）"
    return "\n".join(f"- {t}" for t in titles)


def _bucket_for(item: Dict[str, Any], feed_id: str = "", feed_name: str = "") -> str:
    blob = f"{feed_id} {feed_name} {item.get('url') or ''} {item.get('title') or ''}".lower()
    if "github" in blob or repo_key(item.get("title") or "", item.get("url") or ""):
        return "GitHub"
    if "tiktok" in blob:
        return "TikTok"
    if feed_id.startswith("x-") or re.search(r"\bx\b|twitter", blob):
        return "X"
    return "其他"


def _filter_item_list(
    items: Optional[Sequence[Dict[str, Any]]],
    index: HistoryIndex,
    feed_id: str = "",
    feed_name: str = "",
    counters: Optional[Dict[str, List[int]]] = None,
) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for item in items or []:
        title = str(item.get("title") or "")
        url = str(item.get("url") or item.get("mobileUrl") or "")
        bucket = _bucket_for(item, feed_id, feed_name)
        if counters is not None:
            counters.setdefault(bucket, [0, 0])
            counters[bucket][0] += 1  # input
        if is_sent(title, url, index):
            if counters is not None:
                counters[bucket][1] += 1  # dropped
            continue
        kept.append(item)
    return kept


def _filter_stats(stats: Optional[List[Dict[str, Any]]], index: HistoryIndex, counters: Dict[str, List[int]]) -> List[Dict[str, Any]]:
    if not stats:
        return stats or []
    out: List[Dict[str, Any]] = []
    for group in stats:
        group = deepcopy(group)
        titles = group.get("titles")
        if isinstance(titles, dict):
            new_map: Dict[str, List[Dict[str, Any]]] = {}
            total = 0
            for source_id, rows in titles.items():
                kept = _filter_item_list(rows, index, feed_id=str(source_id), counters=counters)
                new_map[source_id] = kept
                total += len(kept)
            group["titles"] = new_map
            group["count"] = total
            if total:
                out.append(group)
        elif isinstance(titles, list):
            kept = _filter_item_list(titles, index, feed_name=str(group.get("word") or ""), counters=counters)
            group["titles"] = kept
            group["count"] = len(kept)
            if kept:
                out.append(group)
        else:
            out.append(group)
    return out


def _filter_standalone(data: Optional[Dict[str, Any]], index: HistoryIndex, counters: Dict[str, List[int]]) -> Optional[Dict[str, Any]]:
    if not data:
        return data
    data = deepcopy(data)
    for key in ("platforms", "rss_feeds"):
        feeds = data.get(key) or []
        new_feeds = []
        for feed in feeds:
            fid = str(feed.get("id") or "")
            name = str(feed.get("name") or "")
            feed["items"] = _filter_item_list(feed.get("items") or [], index, fid, name, counters)
            new_feeds.append(feed)
        data[key] = new_feeds
    return data


def _filter_rss(items: Optional[List[Dict[str, Any]]], index: HistoryIndex, counters: Dict[str, List[int]]) -> Optional[List[Dict[str, Any]]]:
    if not items:
        return items
    # Two shapes: flat list of articles, or grouped {titles: [...]}
    if items and "titles" in items[0] and "title" not in items[0]:
        out = []
        for group in items:
            group = deepcopy(group)
            group["titles"] = _filter_item_list(
                group.get("titles") or [],
                index,
                feed_id=str(group.get("feed_id") or ""),
                feed_name=str(group.get("feed_name") or group.get("name") or ""),
                counters=counters,
            )
            group["count"] = len(group["titles"])
            if group["titles"]:
                out.append(group)
        return out
    return _filter_item_list(items, index, counters=counters)


def apply_cross_run_dedupe(
    stats: Optional[List[Dict[str, Any]]] = None,
    standalone_data: Optional[Dict[str, Any]] = None,
    rss_items: Optional[List[Dict[str, Any]]] = None,
    rss_new_items: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Optional[List], Optional[Dict], Optional[List], Optional[List]]:
    history = load_history()
    if _index is None:
        return stats, standalone_data, rss_items, rss_new_items
    index = _index
    if not history:
        return stats, standalone_data, rss_items, rss_new_items

    counters: Dict[str, List[int]] = {}
    stats = _filter_stats(stats, index, counters)
    standalone_data = _filter_standalone(standalone_data, index, counters)
    rss_items = _filter_rss(rss_items, index, counters)
    rss_new_items = _filter_rss(rss_new_items, index, counters)

    total_in = sum(v[0] for v in counters.values())
    total_drop = sum(v[1] for v in counters.values())
    remain = total_in - total_drop
    parts = []
    for name in ("GitHub", "X", "TikTok", "其他"):
        if name in counters:
            inn, drop = counters[name]
            parts.append(f"{name} {inn - drop}/{inn}")
    extra = "，".join(parts)
    print(
        f"[去重] 剔除 {total_drop} 条已发送（精确 URL/标题/仓库匹配），"
        f"剩余 {remain} 条" + (f"（{extra}）" if extra else "")
    )
    return stats, standalone_data, rss_items, rss_new_items


def make_record(title: str, url: str = "", ts: Optional[datetime] = None) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        "title": (title or "").strip(),
        "url": (url or "").strip(),
        "url_key": normalize_url(url),
        "title_hash": title_hash(title),
        "ts": (ts or _now()).isoformat(),
    }
    rk = repo_key(title, url)
    if rk:
        rec["repo"] = rk
    return rec


def record_sent(entries: Iterable[Dict[str, Any]], path: Path = ENC_PATH) -> int:
    """Append items that were actually emailed and write the encrypted cache."""
    global _loaded, _index
    if _loaded is None:
        load_history(path)
    existing = list(_loaded or [])
    index = _build_index(existing)
    now = _now()
    added = 0
    for entry in entries:
        title = str(entry.get("title") or "")
        url = str(entry.get("url") or "")
        if not title and not url:
            continue
        if is_sent(title, url, index):
            continue
        rec = make_record(title, url, now)
        existing.append(rec)
        # Keep index current so duplicates within this batch collapse.
        if rec["url_key"]:
            index.urls.add(rec["url_key"])
        if rec["title_hash"]:
            index.title_hashes.add(rec["title_hash"])
        if rec.get("repo"):
            index.repos.add(rec["repo"])
        added += 1
    existing = _prune(existing, now)
    _loaded = existing
    _index = _build_index(existing)
    _write_encrypted(existing, path)
    print(f"[去重] 邮件发送成功，追加 {added} 条并写入加密缓存（共 {len(existing)} 条）")
    return added


def _write_encrypted(items: Sequence[Dict[str, Any]], path: Path) -> None:
    payload = json.dumps({"items": list(items)}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        blob = _openssl(payload, decrypt=False)
    except Exception as exc:
        print(f"[去重] 加密发送历史失败，未写入缓存（{type(exc).__name__}）")
        return
    tmp.write_bytes(blob)
    tmp.replace(path)
