"""속보란: 20분마다 주요 언론사·공식기관 피드를 확인해 시간순 타임라인으로 쌓는다.
속보는 기사를 새로 쓰지 않고, 원 언론사 제목을 그대로(해외는 번역 + 원문 병기) 링크와 함께 싣는다."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from rapidfuzz import fuzz

from .collect import _norm_title, collect
from .common import DATA, ask_json, llm_available, log, now_utc, read_json, write_json

PATH = DATA / "breaking.json"
VALID = {"ai", "kr", "global", "money", "crypto", "people"}

KEYWORDS = {
    "ai": ["AI", "인공지능", "반도체", "엔비디아", "Nvidia", "OpenAI", "오픈AI", "HBM", "GPU", "칩", "chip",
           "데이터센터", "삼성전자", "SK하이닉스", "TSMC", "Anthropic", "앤트로픽", "Google", "구글", "Microsoft", "Meta"],
    "kr": ["코스피", "코스닥", "KOSPI", "KOSDAQ", "상장", "공시", "주가", "특징주", "시가총액", "거래소"],
    "global": ["S&P", "Nasdaq", "나스닥", "다우", "Dow", "Wall Street", "뉴욕증시", "월가", "stocks", "shares", "IPO", "earnings", "실적"],
    "money": ["금리", "환율", "달러", "원화", "국채", "연준", "Fed", "한은", "한국은행", "기준금리", "유가", "oil", "gold", "금값",
              "인플레", "inflation", "CPI", "yield", "Treasury", "ECB", "ETF", "자금", "순매수", "순매도", "관세", "tariff"],
    "crypto": ["비트코인", "Bitcoin", "이더리움", "Ethereum", "crypto", "암호화폐", "가상자산", "코인", "stablecoin", "스테이블코인", "Solana"],
}


def _people_tags(title: str, people: list[list[str]]) -> list[str]:
    return [names[0] for names in people if any(re.search(_kw(n), title, re.I) for n in names)]


def _kw(w: str) -> str:
    # 영문 키워드는 단어 경계로 (예: 'AI'가 'KAI' 안에서 잡히지 않도록)
    return rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])" if w.isascii() else re.escape(w)


def _keyword_section(title: str) -> str | None:
    for sec, words in KEYWORDS.items():
        if any(re.search(_kw(w), title, re.I) for w in words):
            return sec
    return None


CLASSIFY_SYSTEM = """당신은 경제신문 속보 데스크입니다. 헤드라인 목록을 보고 각 항목을 판단합니다.
- keep: AI·테크, 증시, 금리·환율·원자재, 암호화폐, 시장에 영향을 주는 정치·외교·정책, 주요 정치인·기업가 발언이면 true.
  연예, 스포츠, 사건사고, 날씨, 생활 기사는 false.
- section: ai | kr | global | money | crypto | people
- ko: 영어 헤드라인이면 뜻을 바꾸지 말고 한국어로 번역(추가 설명 금지). 한국어면 그대로.
JSON만: {"items":[{"id":"...","keep":true,"section":"money","ko":"..."}]}"""


def _classify(items: list[dict], model: str) -> dict:
    if not items:
        return {}
    if not llm_available():
        out = {}
        for it in items:
            sec = _keyword_section(it["title"])
            out[it["id"]] = {"keep": sec is not None, "section": sec or "global", "ko": it["title"]}
        return out
    result = {}
    for i in range(0, len(items), 60):
        chunk = items[i:i + 60]
        user = "\n".join(f'{it["id"]}|{it["lang"]}|{it["title"]}' for it in chunk)
        try:
            res = ask_json(model, CLASSIFY_SYSTEM, user, max_tokens=6000)
            for r in res.get("items", []):
                result[r["id"]] = r
        except Exception as e:
            log.warning("속보 분류 실패, 키워드 방식으로 대체: %s", e)
            for it in chunk:
                sec = _keyword_section(it["title"])
                result[it["id"]] = {"keep": sec is not None, "section": sec or "global", "ko": it["title"]}
    return result


def update(cfg: dict) -> list[dict]:
    bc = cfg["breaking"]
    feed = read_json(PATH, [])
    known_ids = {x["id"] for x in feed}
    known_titles = {_norm_title(x["title"]) for x in feed}

    fresh = [it for it in collect(cfg, bc["lookback_minutes"] / 60, only_breaking=True)
             if it["id"] not in known_ids and _norm_title(it["title"]) not in known_titles]
    verdicts = _classify(fresh, cfg["models"]["breaking"])

    added = 0
    for it in fresh:
        v = verdicts.get(it["id"], {})
        people = _people_tags(it["title"], cfg["people"])
        if not v.get("keep") and not people:
            continue
        ko = (v.get("ko") or it["title"]).strip()
        sec = v.get("section") if v.get("section") in VALID else "global"
        feed.append({
            "id": it["id"], "time": it["published"], "title": it["title"],
            "ko": ko if it["lang"] != "ko" else it["title"],
            "lang": it["lang"], "outlet": it["outlet"], "url": it["url"],
            "section": "people" if people and sec == "global" else sec,
            "people": people,
            "flash": bool(re.search(r"\[속보\]|\[1보\]|breaking", it["title"], re.I)),
            "official": it["official"],
        })
        added += 1

    # 오래된 항목 정리 + 여러 언론사가 동시에 다룬 소식에 '교차보도' 표시
    cutoff = now_utc() - timedelta(hours=bc["keep_hours"])
    feed = [x for x in feed if datetime.fromisoformat(x["time"]) >= cutoff]
    feed.sort(key=lambda x: x["time"], reverse=True)
    for x in feed:
        x["also"] = sorted({
            y["outlet"] for y in feed
            if y is not x and y["outlet"] != x["outlet"]
            and abs((datetime.fromisoformat(y["time"]) - datetime.fromisoformat(x["time"])).total_seconds()) < 6 * 3600
            and fuzz.token_set_ratio(y["ko"], x["ko"]) >= 72
        })[:4]
    write_json(PATH, feed)
    log.info("속보 %d건 추가, 총 %d건", added, len(feed))
    return feed
