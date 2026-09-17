"""
미국 배당/주요 ETF 데이터 수집 → data/us_etf.json
yfinance 기반, GitHub Actions 매일 자동 실행
향후 확장: KIS API, 네이버 금융, DART 등 추가 예정
"""
import json
import os
import time
import traceback
from datetime import datetime, timezone, timedelta

# yfinance는 Actions에서 pip install
import yfinance as yf

KST = timezone(timedelta(hours=9))
OUTPUT = "data/us_etf.json"
DELAY = 1.5  # API 호출 간 대기(초)

# ── ETF 목록 (카테고리별) ──
ETFS = {
    # 배당 ETF
    "SCHD": {"name": "Schwab 미국 배당", "cat": "dividend", "desc": "미국 고배당+품질 스크리닝"},
    "VYM":  {"name": "Vanguard 고배당", "cat": "dividend", "desc": "미국 고배당 대형주 400+종목"},
    "DGRO": {"name": "iShares 배당성장", "cat": "dividend", "desc": "배당 성장률 기반 선별"},
    "HDV":  {"name": "iShares 고배당", "cat": "dividend", "desc": "고배당+재무건전성 필터"},

    # 커버드콜 ETF
    "JEPI": {"name": "JPM 커버드콜 S&P", "cat": "coveredcall", "desc": "S&P500 커버드콜, 월배당"},
    "JEPQ": {"name": "JPM 커버드콜 나스닥", "cat": "coveredcall", "desc": "나스닥 커버드콜, 월배당"},

    # 시장 벤치마크
    "VOO":  {"name": "S&P 500", "cat": "benchmark", "desc": "미국 대형주 500종목 추종"},
    "QQQ":  {"name": "Nasdaq 100", "cat": "benchmark", "desc": "나스닥 대형 기술주 100종목"},
    "VTI":  {"name": "미국 전체시장", "cat": "benchmark", "desc": "미국 주식 전체(3500+종목)"},

    # 채권 ETF
    "TLT":  {"name": "미국 장기국채 20Y+", "cat": "bond", "desc": "만기 20년+ 미국 국채"},
    "SHY":  {"name": "미국 단기국채 1-3Y", "cat": "bond", "desc": "만기 1-3년 미국 국채"},
    "BND":  {"name": "미국 채권 종합", "cat": "bond", "desc": "투자등급 채권 전체"},
}


def safe_get(info, key, default=None):
    """yfinance info에서 안전하게 값 추출"""
    try:
        v = info.get(key, default)
        if v is None:
            return default
        return v
    except:
        return default


def fetch_etf(ticker_str, meta):
    """단일 ETF 데이터 수집"""
    try:
        tk = yf.Ticker(ticker_str)
        info = tk.info or {}

        # 기본 정보
        price = safe_get(info, "regularMarketPrice") or safe_get(info, "previousClose", 0)
        prev_close = safe_get(info, "previousClose", 0)
        change = round(price - prev_close, 2) if price and prev_close else 0
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

        # 배당 정보
        div_yield = safe_get(info, "dividendYield")  # 소수점 (0.035 = 3.5%)
        div_rate = safe_get(info, "dividendRate", 0)  # 연간 배당금($)
        trailing_pe = safe_get(info, "trailingPE")

        # 52주 범위
        high_52w = safe_get(info, "fiftyTwoWeekHigh", 0)
        low_52w = safe_get(info, "fiftyTwoWeekLow", 0)

        # 운용자산 (B 단위)
        total_assets = safe_get(info, "totalAssets", 0)
        aum_b = round(total_assets / 1e9, 1) if total_assets else None

        # 비용비율
        expense = safe_get(info, "annualReportExpenseRatio")

        # ── 주간 가격 데이터 (5년) ──
        hist = tk.history(period="5y", interval="1wk")
        price_history = []
        if hist is not None and len(hist) > 0:
            for date, row in hist.iterrows():
                close = row.get("Close")
                if close and close > 0:
                    price_history.append({
                        "d": date.strftime("%Y-%m-%d"),
                        "c": round(float(close), 2)
                    })

        # ── 수익률 계산 (1Y/3Y/5Y) ──
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
            "divYield": round(div_yield * 100, 2) if div_yield else None,
            "divRate": round(div_rate, 2) if div_rate else None,
            "pe": round(trailing_pe, 1) if trailing_pe else None,
            "high52w": round(high_52w, 2),
            "low52w": round(low_52w, 2),
            "aumB": aum_b,
            "expense": round(expense * 100, 2) if expense else None,
            "returns": returns,
            "history": price_history,
        }
        print(f"  ✅ {ticker_str}: ${price:.2f}, 배당 {result['divYield'] or '-'}%, {len(price_history)}주 데이터")
        return result

    except Exception as e:
        print(f"  ❌ {ticker_str}: {e}")
        traceback.print_exc()
        return {
            "ticker": ticker_str,
            "name": meta["name"],
            "cat": meta["cat"],
            "desc": meta["desc"],
            "error": str(e)[:100],
        }


def main():
    now = datetime.now(KST)
    print(f"수집 시작: {now.strftime('%Y-%m-%d %H:%M KST')}")
    print(f"대상: {len(ETFS)}개 ETF\n")

    etfs = []
    ok = 0
    fail = 0

    for ticker, meta in ETFS.items():
        data = fetch_etf(ticker, meta)
        etfs.append(data)
        if "error" not in data:
            ok += 1
        else:
            fail += 1
        time.sleep(DELAY)

    result = {
        "updated": now.strftime("%Y-%m-%d %H:%M KST"),
        "count": len(etfs),
        "etfs": etfs,
    }

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f"\n✅ 저장: {OUTPUT} ({size_kb:.0f}KB)")
    print(f"   성공 {ok}, 실패 {fail}")


if __name__ == "__main__":
    main()
