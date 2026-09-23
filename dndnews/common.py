"""공통 유틸: 설정 로딩, 시간, 로그, Claude API 호출."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "docs"          # GitHub Pages 가 서비스하는 폴더
KST = ZoneInfo("Asia/Seoul")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("dndnews")


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_kst() -> datetime:
    return datetime.now(KST)


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;|\xa0", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&quot;", '"', s)
    s = re.sub(r"&#39;|&apos;", "'", s)
    s = re.sub(r"&lt;", "<", s)
    s = re.sub(r"&gt;", ">", s)
    return re.sub(r"\s+", " ", s).strip()


def read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    tmp.replace(path)


# ─────────────────────────── Claude API ───────────────────────────

_client = None


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def ask_json(model: str, system: str, user: str, max_tokens: int = 4000, retries: int = 3):
    """Claude에게 JSON만 돌려달라고 요청하고 파싱해서 돌려준다."""
    last_err = None
    for attempt in range(retries):
        try:
            resp = _get_client().messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return parse_json_block(text)
        except Exception as e:  # 네트워크 오류, 과부하, JSON 파싱 실패 등
            last_err = e
            log.warning("Claude 호출 실패 (%s/%s): %s", attempt + 1, retries, e)
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"Claude 호출 최종 실패: {last_err}")


def parse_json_block(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError("JSON이 응답에 없음")
    return json.JSONDecoder().raw_decode(text[start:])[0]
