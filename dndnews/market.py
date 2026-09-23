"""시장 데이터·돈의 흐름. 숫자는 전부 데이터 API에서 직접 가져오고 AI는 관여하지 않는다.
가져오지 못한 값은 비워 두며(—로 표시), 절대 추정하지 않는다."""
from __future__ import annotations

import os
import requests

from .common import log, now_kst

YF = {
    "지수": [
        ("^KS11", "코스피"), ("^KQ11", "코스닥"), ("^GSPC", "S&P 500"), ("^IXIC", "나스닥"),
        ("^DJI", "다우"), ("^SOX", "필라델피아 반도체"), ("^N225", "닛케이 225"), ("000001.SS", "상하이종합"),
    ],
    "환율·금리": [
        ("KRW=X", "원/달러"), ("JPYKRW=X", "원/100엔"), ("EURKRW=X", "원/유로"),
        ("DX-Y.NYB", "달러인덱스"), ("^TNX", "미 국채 10년(%)"), ("^VIX", "VIX 변동성"),
    ],
    "원자재": [
        ("CL=F", "WTI 원유"), ("BZ=F", "브렌트유"), ("GC=F", "금"), ("SI=F", "은"), ("HG=F", "구리"),
    ],
}
SCALE = {"JPYKRW=X": 100}


def _yf_quotes() -> dict:
    import yfinance as yf

    tickers = [t for group in YF.values() for t, _ in group]
    out = {}
    try:
        df = yf.download(tickers, period="10d", interval="1d", progress=False, auto_adjust=False, threads=True)
        close = df["Close"]
    except Exception as e:
        log.warning("yfinance 실패: %s", e)
        return out
    for t in tickers:
        if t not in close:
            continue
        s = close[t].dropna()
        if len(s) < 2:
            continue
        k = SCALE.get(t, 1)
        last, prev = float(s.iloc[-1]) * k, float(s.iloc[-2]) * k
        out[t] = {"value": last, "change": last - prev, "pct": (last / prev - 1) * 100,
                  "date": s.index[-1].strftime("%Y-%m-%d")}
    return out


def _crypto() -> list[dict]:
    rows = []
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum,solana,ripple", "vs_currencies": "usd,krw",
                    "include_24hr_change": "true", "include_last_updated_at": "true"},
            timeout=15,
        ).json()
        names = {"bitcoin": "비트코인", "ethereum": "이더리움", "solana": "솔라나", "ripple": "리플"}
        for cid, name in names.items():
            if cid in r:
                d = r[cid]
                rows.append({"name": name, "id": cid, "usd": d.get("usd"), "krw": d.get("krw"),
                             "pct": d.get("usd_24h_change")})
    except Exception as e:
        log.warning("CoinGecko 실패: %s", e)
    return rows


def _kimchi_premium(btc_usd: float | None, usdkrw: float | None) -> float | None:
    """업비트 원화 비트코인 가격 ÷ (해외 달러 가격 × 환율) − 1"""
    if not btc_usd or not usdkrw:
        return None
    try:
        r = requests.get("https://api.upbit.com/v1/ticker", params={"markets": "KRW-BTC"}, timeout=10).json()
        upbit = float(r[0]["trade_price"])
        return (upbit / (btc_usd * usdkrw) - 1) * 100
    except Exception as e:
        log.warning("업비트 실패: %s", e)
        return None


def _krx_flows() -> dict | None:
    """외국인·기관·개인 순매수 (KRX 정보데이터시스템, 로그인 필요: KRX_ID / KRX_PW)."""
    if not (os.getenv("KRX_ID") and os.getenv("KRX_PW")):
        log.info("KRX 계정이 없어 수급 데이터를 건너뜀")
        return None
    try:
        from pykrx import stock

        today = now_kst()
        end = today.strftime("%Y%m%d")
        day = stock.get_nearest_business_day_in_a_week(end, prev=True)
        result = {"date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "markets": {}, "top_foreign": {}}
        for mkt in ("KOSPI", "KOSDAQ"):
            df = stock.get_market_trading_value_by_investor(day, day, mkt)
            col = "순매수"
            result["markets"][mkt] = {
                who: int(df.loc[who, col]) for who in ("외국인", "기관합계", "개인") if who in df.index
            }
            net = stock.get_market_net_purchases_of_equities(day, day, mkt, "외국인")
            net = net.sort_values("순매수거래대금", ascending=False)
            result["top_foreign"][mkt] = {
                "buy": [{"name": r["종목명"], "value": int(r["순매수거래대금"])} for _, r in net.head(5).iterrows()],
                "sell": [{"name": r["종목명"], "value": int(r["순매수거래대금"])} for _, r in net.tail(5).iloc[::-1].iterrows()],
            }
        return result
    except Exception as e:
        log.warning("KRX 수급 실패: %s", e)
        return None


def snapshot() -> dict:
    q = _yf_quotes()
    groups = {}
    for gname, lst in YF.items():
        groups[gname] = [{"ticker": t, "name": n, **q[t]} if t in q else {"ticker": t, "name": n}
                         for t, n in lst]
    crypto = _crypto()
    btc = next((c for c in crypto if c["id"] == "bitcoin"), None)
    usdkrw = q.get("KRW=X", {}).get("value")
    snap = {
        "fetched_at": now_kst().isoformat(),
        "groups": groups,
        "crypto": crypto,
        "kimchi_premium": _kimchi_premium(btc and btc["usd"], usdkrw),
        "flows": _krx_flows(),
    }
    got = sum(1 for g in groups.values() for r in g if "value" in r)
    log.info("시장 데이터 %d/%d개 확보, 암호화폐 %d개", got, sum(len(v) for v in YF.values()), len(crypto))
    return snap
