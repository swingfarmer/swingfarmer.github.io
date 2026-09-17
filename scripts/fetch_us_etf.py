"""
미국 배당/주요 ETF 데이터 수집 → data/us_etf.json
yfinance 기반, GitHub Actions 매일 자동 실행
"""
import json
import os
import time
import traceback
from datetime import datetime, timezone, timedelta

import yfinance as yf

KST = timezone(timedelta(hours=9))
OUTPUT = "data/us_etf.json"
DELAY = 1.5

ETFS = {
    "SCHD": {"name": "Schwab 미국 배당", "cat": "dividend", "desc": "미국 고배당+품질 스크리닝"},
    "VYM":  {"name": "Vanguard 고배당", "cat": "dividend", "desc": "미국 고배당 대형주 400+종목"},
    "DGRO": {"name": "iShares 배당성장", "cat": "dividend", "desc": "배당 성장률 기반 선별"},
    "HDV":  {"name": "iShares 고배당", "cat": "dividend", "desc": "고배당+재무건전성 필터"},
    "JEPI": {"name": "JPM 커버드콜 S&P", "cat": "coveredcall", "desc": "S&P500 커버드콜, 월배당"},
    "JEPQ": {"name": "JPM 커버드콜 나스닥", "cat": "coveredcall", "desc": "나스닥 커버드콜, 월배당"},
    "VOO":  {"name": "S&P 500", "cat": "benchmark", "desc": "미국 대형주 500종목 추종"},
    "QQQ":  {"name": "Nasdaq 100", "cat": "benchmark", "desc": "나스닥 대형 기술주 100종목"},
    "VTI":  {"name": "미국 전체시장", "cat": "benchmark", "desc": "미국 주식 전체(3500+종목)"},
    "TLT":  {"name": "미국 장기국채 20Y+", "cat": "bond", "desc": "만기 20년+ 미국 국채"},
    "SHY":  {"name": "미국 단기국채 1-3Y", "cat": "bond", "desc": "만기 1-3년 미국 국채"},
    "BND":  {"name": "미국 채권 종합", "cat": "bond", "desc": "투자등급 채권 전체"},
}


def safe_get(info, key, default=None):
    try:
        v = info.get(key, default)
        return default if v is None else v
    except:
        return default


def normalize_yield(raw_value):
    """
    yfinance dividendYield 정규화.
    버전에 따라 소수점(0.035) 또는 퍼센트(3.5)로 반환됨.
    → 항상 퍼센트(3.5) 형태로 통일.
    """
    if raw_value is None:
        return None
    v = float(raw_value)
    if v <= 0:
        return None
    # 0.5 이하면 소수점 형태 (0.035 = 3.5%) → ×100
    # 0.5 초과면 이미 퍼센트 형태 (3.5 = 3.5%)
    if v < 0.5:
        return round(v * 100, 2)
    else:
        return round(v, 2)


def normalize_ratio(raw_value):
    """비용비율 정규화 (같은 이슈 — 0.0003 vs 0.03 vs 3.0)"""
    if raw_value is None:
        return None
    v = float(raw_value)
    if v <= 0:
        return None
    if v < 0.01:
        return round(v * 100, 2)  # 0.0003 → 0.03%
    elif v < 1:
        return round(v, 2)        # 0.03 → 0.03% (이미 퍼센트)
    else:
        return round(v, 2)        # 3.0 → 3.0% (이미 퍼센트)


def fetch_etf(ticker_str, meta):
    try:
        tk = yf.Ticker(ticker_str)
        info = tk.info or {}

        price = safe_get(info, "regularMarketPrice") or safe_get(info, "previousClose", 0)
        prev_close = safe_get(info, "previousClose", 0)
        change = round(price - prev_close, 2) if price and prev_close else 0
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

        # 배당 — 정규화 적용
        div_yield = normalize_yield(safe_get(info, "dividendYield"))
        div_rate = safe_get(info, "dividendRate", 0)

        # 배당률 교차검증: dividendRate / price로 직접 계산
        if div_yield and price and div_rate:
            calc_yield = round((div_rate / price) * 100, 2)
            # 차이가 2배 이상이면 직접 계산값 사용
            if div_yield > calc_yield * 2 or div_yield < calc_yield * 0.5:
                print(f"    ⚠ {ticker_str} 배당률 보정: API {div_yield}% → 계산값 {calc_yield}%")
                div_yield = calc_yield

        trailing_pe = safe_get(info, "trailingPE")
        high_52w = safe_get(info, "fiftyTwoWeekHigh", 0)
        low_52w = safe_get(info, "fiftyTwoWeekLow", 0)

        total_assets = safe_get(info, "totalAssets", 0)
        aum_b = round(total_assets / 1e9, 1) if total_assets else None

        expense = normalize_ratio(safe_get(info, "annualReportExpenseRatio"))

        # 주간 가격 5년치
        hist = tk.history(period="5y", interval="1wk")
        price_history = []
        if hist is not None and len(hist) > 0:
            for date, row in hist.iterrows():
                close = row.get("Close")
                if close and close > 0:
                    price_history.append({"d": date.strftime("%Y-%m-%d"), "c": round(float(close), 2)})

        # 수익률 계산
        returns = {}
        if len(price_history) > 0:
            current = price_history[-1]["c"]
            for label, weeks in [("1Y", 52), ("3Y", 156), ("5Y", 260)]:
                if len(price_history) >= weeks:
                    past = price_history[-weeks]["c"]
                    if past > 0:
                        returns[label] = round(((current - past) / past) * 100, 1)

        result = {
            "ticker": ticker_str,
            "name": meta["name"],
            "cat": meta["cat"],
            "desc": meta["desc"],
            "price": round(price, 2) if price else 0,
            "change": change,
            "changePct": change_pct,
            "divYield": div_yield,
            "divRate": round(div_rate, 2) if div_rate else None,
            "pe": round(trailing_pe, 1) if trailing_pe else None,
            "high52w": round(high_52w, 2),
            "low52w": round(low_52w, 2),
            "aumB": aum_b,
            "expense": expense,
            "returns": returns,
            "history": price_history,
        }
        print(f"  ✅ {ticker_str}: ${price:.2f}, 배당 {div_yield or '-'}%, {len(price_history)}주")
        return result

    except Exception as e:
        print(f"  ❌ {ticker_str}: {e}")
        traceback.print_exc()
        return {"ticker": ticker_str, "name": meta["name"], "cat": meta["cat"], "desc": meta["desc"], "error": str(e)[:100]}


def main():
    now = datetime.now(KST)
    print(f"수집 시작: {now.strftime('%Y-%m-%d %H:%M KST')}")
    print(f"대상: {len(ETFS)}개 ETF\n")

    etfs = []
    ok = fail = 0
    for ticker, meta in ETFS.items():
        data = fetch_etf(ticker, meta)
        etfs.append(data)
        if "error" not in data:
            ok += 1
        else:
            fail += 1
        time.sleep(DELAY)

    result = {"updated": now.strftime("%Y-%m-%d %H:%M KST"), "count": len(etfs), "etfs": etfs}

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f"\n✅ 저장: {OUTPUT} ({size_kb:.0f}KB), 성공 {ok}, 실패 {fail}")


if __name__ == "__main__":
    main()
