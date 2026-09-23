"""4단계: 근거 자료만으로 기사를 쓰고(작성), 문장 단위로 다시 대조한다(사실확인).
근거가 없는 문장은 지우고, 너무 많이 지워지거나 제목이 근거 없으면 기사를 싣지 않는다."""
from __future__ import annotations

import re

from .common import ask_json, log

WRITER_SYSTEM = """당신은 한국 경제신문의 기자입니다. 아래 [근거 자료]만 사용해 기사 1편을 한국어로 씁니다.

절대 규칙 (어기면 기사 폐기):
1. 근거 자료에 없는 사실, 수치, 날짜, 인용, 인물, 전망을 추가하지 않는다. 배경지식으로 보충하지 않는다.
2. 모든 수치는 근거 자료에 있는 그대로 쓴다. 외화 단위 환산(예: $2.5 billion → 25억달러)은 허용하되 반올림·추정 금지.
3. 자료끼리 내용이 다르면 한쪽을 고르지 말고 "A는 ~, B는 ~라고 보도했다"처럼 차이를 밝힌다.
4. 투자 권유, 매수·매도 추천, 가격 예측을 하지 않는다. 근거 자료 속 전문가 전망은 누가 말했는지 밝혀 인용만 한다.
5. 원문 문장을 그대로 베끼지 말고 새로 쓴다. 직접 인용은 발언자가 명확한 짧은 발언만.
6. 시점 표현은 자료에 나온 날짜를 기준으로 쓰고, '오늘/어제'처럼 모호한 표현은 피한다.

문체: 간결한 경제지 기사체(~했다, ~로 나타났다). 제목은 35자 이내, 부제는 60자 이내.
본문은 3~6개 문단, 각 문단은 1~3문장. 각 문단에 근거가 된 자료 번호를 cites에 적는다.
key_points: 독자가 꼭 알아야 할 사실 3가지(각 40자 이내, 근거 자료에 있는 사실만).

JSON으로만 답하세요:
{"headline":"...","dek":"...","key_points":["...","...","..."],
 "body":[{"sentences":["문장1","문장2"],"cites":[1,2]}],
 "tags":["키워드1","키워드2"]}"""

CHECK_SYSTEM = """당신은 신문사 교열·팩트체크 데스크입니다. [근거 자료]와 [기사]를 대조합니다.
기사의 제목, 부제, 핵심 요약, 본문 각 문장이 근거 자료로 뒷받침되는지 판정하세요.

- SUPPORTED: 근거 자료에 해당 내용이 있음 (외화 단위 환산·어순 변경·요약은 허용)
- UNSUPPORTED: 근거 자료에서 확인할 수 없는 사실·수치·인용·해석이 들어 있음
- CONTRADICTED: 근거 자료와 어긋남
수치, 날짜, 고유명사, 인용문은 특히 엄격하게 봅니다. 애매하면 UNSUPPORTED로 판정합니다.

문제가 있는 것만 JSON으로 답하세요 (문제 없으면 빈 배열):
{"issues":[{"where":"headline|dek|key_point|body","kp":0,"p":0,"s":0,"verdict":"UNSUPPORTED","reason":"..."}]}
(key_point는 kp 번호, body는 p=문단 번호, s=문장 번호. 모두 0부터 시작)"""


def _sources_block(sources: list[dict]) -> str:
    parts = []
    for n, s in enumerate(sources, 1):
        body = s.get("body") or s.get("summary") or "(본문 없음 — 제목만 참고)"
        parts.append(
            f"[자료 {n}] {s['outlet']} · {s['published'][:16]}Z\n제목: {s['title']}\n내용: {body}"
        )
    return "\n\n".join(parts)


def _article_block(a: dict) -> str:
    lines = [f"제목: {a['headline']}", f"부제: {a['dek']}"]
    for i, k in enumerate(a["key_points"]):
        lines.append(f"핵심[{i}]: {k}")
    for p, para in enumerate(a["body"]):
        for s, sent in enumerate(para["sentences"]):
            lines.append(f"본문[p={p},s={s}]: {sent}")
    return "\n".join(lines)


_NUM = re.compile(r"\d[\d,]*\.?\d*")


def _numbers_missing(a: dict, sources: list[dict]) -> list[str]:
    """기사 속 숫자 중 근거 자료 어디에도 없는 것 (단위 환산 때문에 참고용 경고로만 사용)."""
    src = " ".join((s.get("title", "") + " " + s.get("summary", "") + " " + s.get("body", "")) for s in sources)
    src_nums = {n.replace(",", "").rstrip(".") for n in _NUM.findall(src)}
    art = " ".join([a["headline"], a["dek"], *a["key_points"]] + [x for p in a["body"] for x in p["sentences"]])
    return sorted({n for n in (m.replace(",", "").rstrip(".") for m in _NUM.findall(art))
                   if len(n) > 1 and n not in src_nums})


def write_article(story: dict, cfg: dict) -> dict | None:
    sources = story["sources"]
    block = _sources_block(sources)
    a = ask_json(cfg["models"]["writer"], WRITER_SYSTEM,
                 f"[스토리] {story['topic']}\n\n[근거 자료]\n{block}", max_tokens=8000)
    for k in ("headline", "dek", "key_points", "body"):
        if k not in a:
            raise ValueError(f"기사 형식 오류: {k} 없음")

    # ── 사실확인 ──
    missing = _numbers_missing(a, sources)
    hint = f"\n\n[자동 경고] 근거 자료에서 그대로 찾을 수 없는 숫자: {', '.join(missing)} — 단위 환산인지 반드시 확인" if missing else ""
    chk = ask_json(cfg["models"]["factcheck"], CHECK_SYSTEM,
                   f"[근거 자료]\n{block}\n\n[기사]\n{_article_block(a)}{hint}", max_tokens=8000)
    issues = chk.get("issues", [])

    def _i(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return -1

    for i in issues:                      # 표기 흔들림 보정 ("body"/"본문", 문자열 숫자 등)
        w = str(i.get("where", "")).lower()
        i["where"] = ("headline" if "head" in w or "제목" in w else "dek" if "dek" in w or "부제" in w
                      else "key_point" if "key" in w or "핵심" in w else "body")
        i["p"], i["s"], i["kp"] = _i(i.get("p")), _i(i.get("s")), _i(i.get("kp"))

    if any(i.get("where") in ("headline", "dek") for i in issues):
        log.warning("제목/부제 근거 부족으로 폐기: %s", a["headline"])
        return None

    total = sum(len(p["sentences"]) for p in a["body"])
    drop_body = {(i.get("p"), i.get("s")) for i in issues if i.get("where") == "body"}
    drop_kp = {i.get("kp") for i in issues if i.get("where") == "key_point"}
    if total == 0 or len(drop_body) / total > 0.25:
        log.warning("근거 없는 문장 과다(%d/%d)로 폐기: %s", len(drop_body), total, a["headline"])
        return None

    body = []
    for p, para in enumerate(a["body"]):
        sents = [s for i, s in enumerate(para["sentences"]) if (p, i) not in drop_body]
        if sents:
            cites = [c for c in para.get("cites", []) if isinstance(c, int) and 1 <= c <= len(sources)]
            body.append({"text": " ".join(sents), "cites": cites})
    key_points = [k for i, k in enumerate(a["key_points"]) if i not in drop_kp]

    return {
        "headline": a["headline"].strip(),
        "dek": a["dek"].strip(),
        "key_points": key_points,
        "body": body,
        "tags": a.get("tags", [])[:5],
        "section": story["section"],
        "importance": story["importance"],
        "outlets": story["outlets"],
        "official": story["official"],
        "sources": [
            {"n": n, "outlet": s["outlet"], "title": s["title"], "url": s["url"], "published": s["published"]}
            for n, s in enumerate(sources, 1)
        ],
        "factcheck": {"removed_sentences": len(drop_body), "removed_points": len(drop_kp),
                      "total_sentences": total},
    }
