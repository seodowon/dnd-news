"""5단계: 모던 경제지 디자인으로 정적 웹사이트(docs/)를 만든다."""
from __future__ import annotations

import shutil
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .common import DATA, KST, ROOT, SITE, log, read_json, write_json

WEEKDAYS = "월화수목금토일"


def _env(cfg: dict) -> Environment:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))

    def num(v, digits=2):
        if v is None:
            return "—"
        if abs(v) >= 1000:
            return f"{v:,.{0 if abs(v) >= 100000 else digits}f}"
        return f"{v:,.{digits}f}"

    def signed(v, digits=2, suffix=""):
        if v is None:
            return "—"
        return f"{'+' if v > 0 else ''}{v:,.{digits}f}{suffix}"

    def updown(v):
        if v is None or abs(v) < 1e-9:
            return "flat"
        return "up" if v > 0 else "down"

    def kst(iso, fmt="%H:%M"):
        try:
            return datetime.fromisoformat(iso).astimezone(KST).strftime(fmt)
        except Exception:
            return ""

    def korean_date(d):
        dt = datetime.strptime(d, "%Y-%m-%d")
        return f"{dt.year}년 {dt.month}월 {dt.day}일 {WEEKDAYS[dt.weekday()]}요일"

    def eok(v):
        """원 → 억원"""
        if v is None:
            return "—"
        return f"{'+' if v > 0 else ''}{v / 1e8:,.0f}억"

    env.filters.update(num=num, signed=signed, updown=updown, kst=kst, korean_date=korean_date, eok=eok)
    env.globals.update(site=cfg["site"], sections=cfg["sections"],
                       section_name={s["id"]: s["name"] for s in cfg["sections"]})
    return env


def _write(path, html):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _archive_dates() -> list[str]:
    return sorted((p.stem for p in (DATA / "editions").glob("*.json")), reverse=True)


def render_breaking(cfg: dict, feed: list[dict]) -> None:
    env = _env(cfg)
    write_json(SITE / "data" / "breaking.json", feed[:400])
    _write(SITE / "breaking.html", env.get_template("breaking.html").render(root="", feed=feed[:150], page="breaking"))
    log.info("속보 페이지 갱신")


def render_edition(cfg: dict, edition: dict, as_index: bool = True) -> None:
    env = _env(cfg)
    feed = read_json(DATA / "breaking.json", [])
    arts = edition["articles"]
    by_sec = {s["id"]: [a for a in arts if a["section"] == s["id"]] for s in cfg["sections"]}
    date = edition["date"]

    ctx = dict(ed=edition, arts=arts, by_sec=by_sec, flash=feed[:8])
    # 날짜별 보관 페이지 (depth 1)
    _write(SITE / date / "index.html", env.get_template("edition.html").render(root="../", base="", page="edition", **ctx))
    for a in arts:
        _write(SITE / date / f"{a['slug']}.html",
               env.get_template("article.html").render(root="../", ed=edition, a=a, page="article",
                                                       related=[x for x in by_sec[a["section"]] if x is not a][:4]))
    for s in cfg["sections"]:
        _write(SITE / date / f"section-{s['id']}.html",
               env.get_template("section.html").render(root="../", ed=edition, sec=s, items=by_sec[s["id"]], page="section"))
    # 1면 (최신호)
    if as_index:
        _write(SITE / "index.html", env.get_template("edition.html").render(root="", base=f"{date}/", page="home", **ctx))

    _write(SITE / "archive.html", env.get_template("archive.html").render(root="", dates=_archive_dates(), page="archive"))
    _write(SITE / "about.html", env.get_template("about.html").render(root="", cfg=cfg, page="about"))
    shutil.copy(ROOT / "static" / "style.css", SITE / "style.css")
    shutil.copy(ROOT / "static" / "app.js", SITE / "app.js")
    cname = cfg["site"]["url"].split("//")[-1].strip("/")
    if cname and "example.com" not in cname:
        (SITE / "CNAME").write_text(cname + "\n")
    (SITE / ".nojekyll").write_text("")
    render_breaking(cfg, feed)
    log.info("사이트 생성 완료: %s", SITE)
