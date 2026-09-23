"""조간 발행 전체 흐름: 수집 → 묶기·교차검증 → 원문 확보 → 기사 작성·사실확인 → 배치 → 시장 데이터."""
from __future__ import annotations

import concurrent.futures as cf
import re
import time
from datetime import datetime

from . import market
from .cluster import pick_stories, score
from .collect import collect
from .common import DATA, KST, llm_available, log, now_kst, write_json
from .sources import attach_sources
from .write import write_article


_NUMTOK = re.compile(r"\d[\d,.]*\d|\d")
_STOP = {"속보", "종합", "단독", "특징주", "표", "마감", "오늘", "the", "a", "to", "of", "in", "and", "for", "on", "as", "is", "with"}


def _sig(title: str) -> tuple[set, set, set]:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", title).lower()
    words = {w for w in re.findall(r"[가-힣a-z0-9]+", t) if w not in _STOP and len(w) > 1}
    compact = re.sub(r"[^가-힣a-z0-9]", "", t)
    grams = {compact[i:i + 2] for i in range(len(compact) - 1)}
    nums = {n.replace(",", "") for n in _NUMTOK.findall(t) if len(n.replace(",", "").replace(".", "")) >= 3}
    return words, grams, nums


def _jac(a, b) -> float:
    return len(a[1] & b[1]) / max(1, len(a[1] | b[1]))


def _similar(a, b) -> bool:
    wa, ga, na = a
    wb, gb, nb = b
    if not ga or not gb:
        return False
    jac = len(ga & gb) / len(ga | gb)
    common_words = len(wa & wb)
    if na & nb and common_words >= 2 and jac >= 0.2:   # 같은 수치(예: 7,080)와 단어 둘 이상 공유
        return True
    return jac >= 0.42 or (jac >= 0.30 and common_words >= 3)


def _lexical_stories(items: list[dict], cfg: dict) -> list[dict]:
    """AI 없이(무료 모드) 같은 사건을 다룬 기사를 제목 유사도로 묶고 교차검증 규칙을 적용한다."""
    from .breaking import _keyword_section, _people_tags

    groups: list[dict] = []
    for it in items:
        if len(it["title"]) < 15:          # 너무 짧은 제목은 오분류가 많아 제외
            continue
        sig = _sig(it["title"])
        for g in groups:
            if (g["lang"] == it["lang"] and any(_similar(sig, s) for s in g["sigs"][:8])
                    and _jac(sig, g["sigs"][0]) >= 0.15):     # 대표 제목과도 최소한 닮아야 함(연쇄 오묶임 방지)
                g["items"].append(it)
                g["sigs"].append(sig)
                break
        else:
            groups.append({"lang": it["lang"], "items": [it], "sigs": [sig]})

    stories = []
    for g in groups:
        members = g["items"]
        outlets = sorted({m["outlet"] for m in members})
        official = any(m["official"] for m in members)
        if len(outlets) < cfg["edition"]["min_outlets"] and not official:
            continue
        # 섹션: 묶음 속 제목들 중 가장 많이 걸린 키워드 섹션
        votes: dict[str, int] = {}
        for m in members:
            sec = _keyword_section(m["title"])
            if sec:
                votes[sec] = votes.get(sec, 0) + 1
            if _people_tags(m["title"], cfg["people"]):
                votes["people"] = votes.get("people", 0) + 1
        if not votes:
            continue                         # 경제·투자·AI와 무관한 기사
        sec = max(votes, key=votes.get)
        stories.append({"topic": members[0]["title"], "section": sec,
                        # 한국 독자용 신문이므로 국내 보도 스토리에 가점
                        # (해외 보도는 매체 수가 많게 잡혀서 가중치를 낮춤)
                        "importance": min(round(len(outlets) * (1.0 if g["lang"] == "ko" else 0.6))
                                          + (2 if official else 0) + (2 if g["lang"] == "ko" else 0), 10),
                        "items": members, "outlets": outlets, "official": official})
    return stories


def _int_nums(sig) -> set:
    return {n.split(".")[0] for n in sig[2] if len(n.split(".")[0]) >= 3}


def _same_event(sa: list, sb: list) -> bool:
    """이미 실린 스토리와 같은 사건인지(중복 게재 방지용, 느슨한 기준)."""
    for a in sa[:6]:
        for b in sb[:6]:
            common = len(a[0] & b[0])
            if (_int_nums(a) & _int_nums(b) and common >= 1) or (_jac(a, b) >= 0.3 and common >= 2):
                return True
    return False


def _dedupe(stories: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for st in stories:
        sigs = [_sig(m["title"]) for m in st["items"]]
        if any(k["lang"] == st["items"][0]["lang"] and _same_event(k["sigs"], sigs) for k in kept):
            continue
        kept.append({"story": st, "sigs": sigs, "lang": st["items"][0]["lang"]})
    return [k["story"] for k in kept]


def _headline_only(story: dict) -> dict:
    # 대표 제목: 신뢰 등급이 높고, 원 언론사 피드에서 온 기사, 머리말([속보] 등)이 없는 쪽
    # 대표 제목: 묶음 속 다른 제목들과 가장 많이 닮은 제목(중심), 동률이면 신뢰 등급 순
    sigs = [_sig(m["title"]) for m in story["items"]]
    def centrality(i):
        return sum(_jac(sigs[i], sigs[j]) for j in range(len(sigs)) if j != i)
    order = sorted(range(len(sigs)), key=lambda i: (-round(centrality(i), 1), story["items"][i]["tier"],
                                                      story["items"][i]["title"].startswith("[")))
    lead = story["items"][order[0]]
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
        log.info("무료 모드: AI 기사 작성 없이 교차확인된 헤드라인으로 신문을 만듭니다")
        stories = _lexical_stories(items, cfg)
    stories.sort(key=score, reverse=True)
    verified_total = len(stories)
    if not use_llm:
        stories = _dedupe(stories)
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

    # 해외 보도 비중 제한 (한국 독자용 신문) — 1면 머리기사는 국내 보도로
    max_foreign = ec.get("max_foreign", 6)
    picked, foreign = [], 0
    for a in articles:
        is_foreign = all(ord(ch) < 0x1100 for ch in a["headline"])
        if is_foreign:
            if foreign >= max_foreign or not picked:
                continue
            foreign += 1
        picked.append(a)
    articles = picked[: ec["articles"]]
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
