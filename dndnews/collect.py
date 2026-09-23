"""1단계: 신뢰할 수 있는 언론사·공식기관 RSS에서 기사 목록을 모은다."""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import re
from calendar import timegm
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

from .common import KST, clean_text, log, now_utc

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DnDNewsBot/1.0; +https://github.com)"}


WIRES = {"연합뉴스", "뉴시스", "뉴스1", "Reuters", "AP", "Bloomberg"}


def _parse_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(timegm(t), tz=timezone.utc)
    raw = (entry.get("published") or entry.get("updated") or "").strip()
    if not raw:
        return None
    # 일부 국내 피드의 비표준 형식 보정: "Wed,23 Sep 2026 ..." / "2026-09-23 16:21:53"(KST)
    try:
        return parsedate_to_datetime(re.sub(r"^(\w{3}),(\S)", r"\1, \2", raw)).astimezone(timezone.utc)
    except Exception:
        pass
    m = re.match(r"(\d{4})[-.](\d{2})[-.](\d{2})[ T](\d{2}):(\d{2})", raw)
    if m:
        y, mo, d, h, mi = map(int, m.groups())
        return datetime(y, mo, d, h, mi, tzinfo=KST).astimezone(timezone.utc)
    return None


def make_canonicalizer(cfg: dict):
    """언론사 이름을 표기명으로 통일. 신뢰 목록에 없으면 None."""
    table = []
    for canon, aliases in (cfg.get("trusted_outlets") or {}).items():
        for a in [canon, *aliases]:
            table.append((a.lower(), canon))
    table.sort(key=lambda x: -len(x[0]))       # 긴 이름 먼저 비교

    def canon(name: str) -> str | None:
        n = name.lower().strip()
        for alias, c in table:
            if n == alias:
                return c
            if alias.isascii():            # 영문은 단어 경계 필요 ('ap'가 'apple'에 걸리지 않게)
                if re.match(re.escape(alias) + r"[\s\-,:|(]", n):
                    return c
            elif n.startswith(alias):      # 한글은 접두 일치 (예: '매일경제 마켓')
                return c
        return None

    return canon


def _google_split(entry, title: str) -> tuple[str, str]:
    """구글 뉴스는 '제목 - 언론사' 형식. 실제 언론사명을 분리한다."""
    src = (entry.get("source") or {}).get("title")
    if src and title.endswith(" - " + src):
        return title[: -len(src) - 3].strip(), src.strip()
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        return head.strip(), tail.strip()
    return title, src or "Google News"


def fetch_feed(feed: dict, since: datetime, canon, require_time: bool = False) -> list[dict]:
    try:
        r = requests.get(feed["url"], headers=HEADERS, timeout=20)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
    except Exception as e:
        log.warning("피드 실패 %s: %s", feed["url"], e)
        return []

    items = []
    for e in parsed.entries:
        title = clean_text(e.get("title"))
        if not title or NOISE.match(title):
            continue
        outlet = feed["outlet"]
        title = re.sub(r"\s*[|│]\s*$", "", title)
        if outlet != "@google":
            title = re.sub(r"\s+-\s+" + re.escape(outlet) + r"\s*$", "", title)
        aggregated = outlet == "@google"
        tier = feed.get("tier", 2)
        if aggregated:
            title, raw_outlet = _google_split(e, title)
            title = re.sub(r"\s+-\s+" + re.escape(raw_outlet.split()[0]) + r".*$", "", title) if raw_outlet else title
            outlet = canon(raw_outlet)
            if outlet is None:             # 신뢰 목록에 없는 매체는 사용하지 않음
                continue
            tier = 1 if outlet in WIRES else 2
        published = _parse_time(e)
        if published is None:
            if require_time:               # 속보는 시각이 정확해야 하므로 시각 없는 기사 제외
                continue
            published = now_utc()          # 조간용: 시각 없는 피드(일부 국내지)는 수집 시각으로
        if published < since:
            continue
        summary = "" if aggregated else clean_text(e.get("summary") or e.get("description"))
        link = e.get("link", "")
        items.append(
            {
                "id": hashlib.sha1((link or title).encode()).hexdigest()[:10],
                "title": title,
                "summary": summary[:600],
                "url": link,
                "outlet": outlet,
                "lang": feed.get("lang", "ko"),
                "tier": tier,
                "official": bool(feed.get("official")),
                "aggregated": aggregated,
                "published": published.isoformat(),
            }
        )
    return items


NOISE = re.compile(r"^\s*[\[(](표|포토|사진|부고|인사|게시판|날씨|오늘의 운세|알림|광고|AD)[\])]")


def _norm_title(t: str) -> str:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】", "", t)
    return re.sub(r"[^\w가-힣]", "", t).lower()


def collect(cfg: dict, hours: float, only_breaking: bool = False) -> list[dict]:
    since = now_utc() - timedelta(hours=hours)
    canon = make_canonicalizer(cfg)
    feeds = [f for f in cfg["feeds"] if f.get("breaking") or not only_breaking]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda f: fetch_feed(f, since, canon, require_time=only_breaking), feeds))

    # 중복 제거: 같은 URL, 또는 같은 언론사의 같은 제목
    seen_url, seen_title, out = set(), set(), []
    for batch in results:
        for it in batch:
            key_t = (it["outlet"], _norm_title(it["title"]))
            if it["url"] in seen_url or key_t in seen_title:
                continue
            seen_url.add(it["url"])
            seen_title.add(key_t)
            out.append(it)
    out.sort(key=lambda x: x["published"], reverse=True)
    log.info("수집 완료: 피드 %d개 → 기사 %d건 (언론사 %d곳)",
             len(feeds), len(out), len({i["outlet"] for i in out}))
    return out
