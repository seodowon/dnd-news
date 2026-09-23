"""2단계: 같은 사건을 다룬 기사들을 하나의 '스토리'로 묶고 중요도를 매긴 뒤,
서로 다른 언론사 N곳 이상이 보도한 스토리만 남긴다(교차검증)."""
from __future__ import annotations

from .common import ask_json, log

SYSTEM = """당신은 한국 경제신문의 편집국장입니다. 독자는 AI 산업, 투자, 돈의 흐름에 관심 있는 한국 투자자입니다.
주어진 기사 목록(국내외 언론사 헤드라인)만 보고 편집 회의를 합니다.

규칙:
- 같은 사건·발표를 다룬 기사들을 하나의 스토리로 묶으세요. 한국어·영어 기사가 같은 사건이면 함께 묶습니다.
- 목록에 없는 사건을 만들어내지 마세요. 오직 주어진 id만 사용합니다.
- 연예, 스포츠, 사건사고, 지역 행정 등 경제·투자·AI와 무관한 기사는 제외합니다.
  단, 시장에 영향을 주는 정치·외교·정책 뉴스와 정치인·기업가의 주요 발언은 포함합니다.
- 섹션은 다음 중 하나: ai(AI·테크·반도체), kr(국내 증시·국내 기업), global(해외 증시·해외 기업·글로벌 경제),
  money(금리·환율·유가·금·수급·ETF·자금 이동·통화정책), crypto(암호화폐), people(정치인·기업가의 발언과 행보)
- importance: 1~10. 시장 전체에 영향이 크고 여러 언론이 크게 다룰수록 높게.
- 중요도 높은 순으로 최대 {max_stories}개까지.

JSON 형식으로만 답하세요:
{{"stories":[{{"ids":["id1","id2"],"section":"money","importance":9,"topic":"한 줄 요약(한국어)"}}]}}"""


def pick_stories(items: list[dict], cfg: dict, model: str, max_stories: int) -> list[dict]:
    by_id = {it["id"]: it for it in items}
    lines = [
        f'{it["id"]}|{it["outlet"]}|{it["published"][5:16]}|{it["title"]}'
        + (f' — {it["summary"][:100]}' if it["summary"] else "")
        for it in items
    ]
    user = "기사 목록 (id|언론사|시각UTC|제목 — 요약):\n" + "\n".join(lines)
    res = ask_json(model, SYSTEM.format(max_stories=max_stories), user, max_tokens=16000)

    min_outlets = cfg["edition"]["min_outlets"]
    valid_sections = {s["id"] for s in cfg["sections"]}
    stories, used = [], set()
    for s in res.get("stories", []):
        ids = [i for i in s.get("ids", []) if i in by_id and i not in used]
        if not ids:
            continue
        members = [by_id[i] for i in ids]
        outlets = sorted({m["outlet"] for m in members})
        official = any(m["official"] for m in members)
        # ── 교차검증 규칙 ──
        # 서로 다른 언론사 min_outlets곳 이상이 보도했거나, 공식기관(연준·한은 등) 1차 자료가 있어야 통과
        if len(outlets) < min_outlets and not official:
            log.info("교차검증 미달로 제외: %s (%s)", s.get("topic"), ", ".join(outlets))
            continue
        used.update(ids)
        stories.append(
            {
                "topic": s.get("topic", ""),
                "section": s.get("section") if s.get("section") in valid_sections else "global",
                "importance": _int(s.get("importance"), 5),
                "items": members,
                "outlets": outlets,
                "official": official,
            }
        )
    log.info("스토리 %d건 선정 (교차검증 통과)", len(stories))
    return stories


def _int(v, default: int) -> int:
    try:
        return max(1, min(10, int(float(v))))
    except (TypeError, ValueError):
        return default


def score(story: dict) -> float:
    """최종 배치 순서용 점수: 편집 판단 + 보도한 언론사 수 + 신뢰 등급."""
    n = len(story["outlets"])
    best_tier = min(m["tier"] for m in story["items"])
    return story["importance"] * 10 + min(n, 8) * 3 + (3 - best_tier) * 2 + (5 if story["official"] else 0)
