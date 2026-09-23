"""조간 발행 전체 흐름: 수집 → 묶기·교차검증 → 원문 확보 → 기사 작성·사실확인 → 배치 → 시장 데이터."""
from __future__ import annotations

import concurrent.futures as cf
import time
from datetime import datetime

from rapidfuzz import fuzz

from . import market
from .cluster import pick_stories, score
from .collect import collect
from .common import DATA, KST, llm_available, log, now_kst, write_json
from .sources import attach_sources
from .write import write_article


def _lexical_stories(items: list[dict], cfg: dict) -> list[dict]:
    """API 키가 없을 때(시험 운행용): 제목 유사도로 묶고 교차검증 규칙만 적용한다."""
    from .breaking import _keyword_section

    groups: list[list[dict]] = []
    for it in items:
        if len(it["title"]) < 15:          # 너무 짧은 제목은 오분류가 많아 제외
            continue
        for g in groups:
            if g[0]["lang"] == it["lang"] and max(fuzz.token_set_ratio(m["title"], it["title"]) for m in g[:5]) >= 58:
                g.append(it)
                break
        else:
            groups.append([it])
    stories = []
    for g in groups:
        outlets = sorted({m["outlet"] for m in g})
        official = any(m["official"] for m in g)
        sec = _keyword_section(g[0]["title"])
        if sec is None or (len(outlets) < cfg["edition"]["min_outlets"] and not official):
            continue
        stories.append({"topic": g[0]["title"], "section": sec, "importance": min(len(outlets), 10),
                        "items": g, "outlets": outlets, "official": official})
    return stories


def _headline_only(story: dict) -> dict:
    lead = sorted(story["items"], key=lambda x: (x["aggregated"], x["tier"]))[0]
    return {
        "headline": lead["title"], "dek": "", "key_points": [], "body": [], "tags": [],
        "section": story["section"], "importance": story["importance"],
        "outlets": story["outlets"], "official": story["official"], "draft": True,
        "sources": [{"n": n, "outlet": s["outlet"], "title": s["title"], "url": s["url"], "published": s["published"]}
                    for n, s in enumerate(story["items"][:6], 1)],
        "factcheck": None,
    }


def build(cfg: dict) -> dict:
    ec = cfg["edition"]
    started = time.time()
    items = collect(cfg, ec["lookback_hours"])
    use_llm = llm_available()

    if use_llm:
        stories = pick_stories(items, cfg, cfg["models"]["cluster"], max_stories=ec["candidates"] + 15)
    else:
        log.warning("ANTHROPIC_API_KEY 없음 → 시험 모드(헤드라인만, 기사 작성 안 함)")
        stories = _lexical_stories(items, cfg)
    stories.sort(key=score, reverse=True)
    verified_total = len(stories)
    stories = stories[: ec["candidates"]]

    articles, dropped = [], 0
    if use_llm:
        attach_sources(stories)

        def job(st):
            try:
                return write_article(st, cfg)
            except Exception as e:
                log.warning("기사 작성 실패 (%s): %s", st["topic"], e)
                return None

        with cf.ThreadPoolExecutor(max_workers=5) as ex:
            results = list(ex.map(job, stories))
        for st, a in zip(stories, results):
            if a:
                a["score"] = score(st)
                articles.append(a)
            else:
                dropped += 1
    else:
        articles = [dict(_headline_only(st), score=score(st)) for st in stories]

    articles = articles[: ec["articles"]]
    for i, a in enumerate(articles, 1):
        a["rank"] = i
        a["slug"] = f"{i:02d}"

    today = now_kst()
    edition = {
        "date": today.strftime("%Y-%m-%d"),
        "generated_at": today.isoformat(),
        "mode": "ai" if use_llm else "draft",
        "articles": articles,
        "market": market.snapshot(),
        "stats": {
            "collected": len(items),
            "outlets": len({i["outlet"] for i in items}),
            "verified_stories": verified_total,
            "dropped_by_factcheck": dropped,
            "seconds": round(time.time() - started),
        },
    }
    write_json(DATA / "editions" / f"{edition['date']}.json", edition)
    write_json(DATA / "latest.json", edition)
    log.info("조간 완성: 기사 %d건, 사실확인 탈락 %d건, %d초", len(articles), dropped, edition["stats"]["seconds"])

    hold = ec.get("hold_until")
    if hold:
        h, m = map(int, hold.split(":"))
        target = today.replace(hour=h, minute=m, second=0, microsecond=0)
        wait = (target - datetime.now(KST)).total_seconds()
        if 0 < wait < 3 * 3600:
            log.info("%s 공개 시각까지 %d초 대기", hold, wait)
            time.sleep(wait)
    return edition
