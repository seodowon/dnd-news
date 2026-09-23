"""3단계: 스토리마다 원문 본문을 가져와 기사 작성·사실확인의 근거 자료로 쓴다."""
from __future__ import annotations

import concurrent.futures as cf

import requests
import trafilatura

from .collect import HEADERS
from .common import log

MAX_SOURCES = 6
MAX_CHARS = 3500


def _fetch_body(url: str) -> str:
    if not url or "news.google.com" in url:
        return ""          # 구글 뉴스 링크는 리다이렉트 페이지라 본문 대신 제목만 근거로 사용
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return ""
        text = trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
        return text[:MAX_CHARS]
    except Exception as e:
        log.debug("본문 실패 %s: %s", url, e)
        return ""


def attach_sources(stories: list[dict]) -> None:
    jobs = []
    for st in stories:
        # 신뢰 등급 높은 순, 본문을 받을 수 있는 원 언론사 우선, 언론사당 1건
        picked, seen = [], set()
        for m in sorted(st["items"], key=lambda x: (x["aggregated"], x["tier"])):
            if m["outlet"] in seen:
                continue
            seen.add(m["outlet"])
            picked.append(m)
            if len(picked) >= MAX_SOURCES:
                break
        st["sources"] = [dict(m) for m in picked]
        jobs.extend(st["sources"])

    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        bodies = list(ex.map(lambda s: _fetch_body(s["url"]), jobs))
    for s, b in zip(jobs, bodies):
        s["body"] = b
    ok = sum(1 for b in bodies if b)
    log.info("원문 확보 %d/%d건", ok, len(jobs))
