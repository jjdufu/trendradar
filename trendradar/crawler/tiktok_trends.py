# coding=utf-8
"""Fetch overseas TikTok trending hashtags without login.

Uses TikTok Creative Center's unsigned KnowledgeAPI (GetHashtagList).
Anonymous requests are capped at 3 hashtags per country; we query several
markets and dedupe. Soft-fails so a blocked Actions IP does not break the run.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

API_URL = "https://ads.tiktok.com/CreativeOne/KnowledgeAPI/GetHashtagList"
DEFAULT_COUNTRIES = ["US", "GB", "CA", "AU", "DE", "FR", "JP", "KR", "BR", "MX"]
DEFAULT_TIME_RANGE = 7

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Origin": "https://ads.tiktok.com",
    "Referer": "https://ads.tiktok.com/creative/creativeCenter/trends",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "agw-js-conv": "str",
}


def _post(payload: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    ctx = ssl.create_default_context()
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers=_HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_tiktok_hashtags(
    countries: Optional[Iterable[str]] = None,
    time_range: int = DEFAULT_TIME_RANGE,
    timeout: int = 20,
) -> List[Dict[str, Any]]:
    """Return deduped hashtag items with title, url, country, publish_cnt, rank."""
    countries = list(countries or DEFAULT_COUNTRIES)
    items: List[Dict[str, Any]] = []
    seen = set()
    for cc in countries:
        try:
            data = _post(
                {"timeRange": int(time_range), "countryCode": cc, "page": 1, "limit": 20},
                timeout=timeout,
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as exc:
            print(f"[TikTok] {cc} 抓取失败: {type(exc).__name__}: {exc}")
            continue
        status = (data.get("BaseResp") or {}).get("StatusCode")
        if status not in (0, None):
            print(f"[TikTok] {cc} 接口异常: {data.get('BaseResp')}")
            continue
        raw = data.get("items") or []
        print(f"[TikTok] {cc}: 获取 {len(raw)} 条标签")
        for it in raw:
            name = (it.get("hashtagName") or "").strip().lstrip("#")
            if not name:
                continue
            key = name.lower()
            creators = []
            for c in (it.get("topCreators") or [])[:3]:
                handle = c.get("handleName") or c.get("nickname")
                if handle:
                    creators.append(str(handle))
            rec = {
                "title": f"#{name}",
                "url": f"https://www.tiktok.com/tag/{name}",
                "country": cc,
                "rank": it.get("rankIndex") or "",
                "publish_cnt": it.get("publishCnt") or "",
                "hashtag_id": it.get("hashtagID") or "",
                "creators": creators,
            }
            if key in seen:
                # keep first (higher-priority country) but record other markets
                for existing in items:
                    if existing["title"].lstrip("#").lower() == key:
                        extra = existing.setdefault("also_in", [])
                        if cc not in extra:
                            extra.append(cc)
                        break
                continue
            seen.add(key)
            items.append(rec)
    return items


def as_standalone_feed(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    items = items[:12]
    if not items:
        return None
    feed_items = []
    for it in items:
        countries = [it.get("country")] + (it.get("also_in") or [])
        countries = [c for c in countries if c]
        meta = []
        if it.get("publish_cnt"):
            meta.append(f"近7日发布 {it['publish_cnt']} 条")
        if countries:
            meta.append("地区 " + "/".join(countries))
        if it.get("creators"):
            meta.append("代表账号 @" + " @".join(it["creators"][:2]))
        feed_items.append({
            "title": it["title"],
            "url": it["url"],
            "published_at": "",
            "author": "",
            "extra": {
                "info": " · ".join(meta),
                "hover": " · ".join(meta),
                "country": it.get("country"),
                "publish_cnt": it.get("publish_cnt"),
                "rank": it.get("rank"),
            },
        })
    return {
        "id": "tiktok-overseas",
        "name": "TikTok 海外热点",
        "items": feed_items,
    }


def fetch_from_config(raw_config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    cfg = (raw_config or {}).get("tiktok_trends") or {}
    if cfg.get("enabled") is False:
        return None
    countries = cfg.get("countries") or DEFAULT_COUNTRIES
    time_range = int(cfg.get("time_range") or DEFAULT_TIME_RANGE)
    items = fetch_tiktok_hashtags(countries=countries, time_range=time_range)
    feed = as_standalone_feed(items)
    if feed:
        print(f"[TikTok] 抓取完成: {len(feed['items'])} 个去重标签")
    else:
        print("[TikTok] 未获取到标签，跳过该栏目")
    return feed
