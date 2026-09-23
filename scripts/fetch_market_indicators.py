"""
주요 시장 지표 수집
==================
미국 지수(나스닥/S&P500/다우) + VIX + 미국 금리(2yr/10yr/30yr)
+ WTI 유가 + 코스피/코스닥 → data/market_indicators.json (최신)
+ data/market_history.json (일별 누적, 무제한 보관)

환율·금시세는 fetch_rates.py에서 수집 → data/rates.json 읽어서 통합.
yfinance 기반. 오라클 cron 아침 07:10 + 저녁 18:45.

환경변수: 없음 (yfinance는 키 불필요)
"""

import json
import os
import time
import traceback
from datetime import datetime, timezone, timedelta

import yfinance as yf

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT = os.path.join(ROOT_DIR, "data", "market_indicators.json")
HISTORY_FILE = os.path.join(ROOT_DIR, "data", "market_history.json")
RATES_FILE = os.path.join(ROOT_DIR, "data", "rates.json")
DELAY = 0.5  # yfinance rate limit 대비

# ── 수집 대상 ──
INDICATORS = {
    # 미국 지수
    "^GSPC":  {"name": "S&P 500",     "cat": "us_index", "unit": "pt"},
    "^IXIC":  {"name": "나스닥 종합",  "cat": "us_index", "unit": "pt"},
    "^DJI":   {"name": "다우 산업",    "cat": "us_index", "unit": "pt"},
    # 변동성
    "^VIX":   {"name": "VIX 공포지수", "cat": "volatility", "unit": ""},
    # 미국 금리
    "^IRX":   {"name": "미국 13주 T-Bill", "cat": "us_rate", "unit": "%"},
    "^FVX":   {"name": "미국 5년물",       "cat": "us_rate", "unit": "%"},
    "^TNX":   {"name": "미국 10년물",      "cat": "us_rate", "unit": "%"},
    "^TYX":   {"name": "미국 30년물",      "cat": "us_rate", "unit": "%"},
    # 원유
    "CL=F":   {"name": "WTI 원유",    "cat": "commodity", "unit": "$/bbl"},
    # 한국 지수
    "^KS11":  {"name": "코스피",       "cat": "kr_index", "unit": "pt"},
    "^KQ11":  {"name": "코스닥",       "cat": "kr_index", "unit": "pt"},
}


def fetch_indicator(ticker_str, meta):
    """yfinance로 단일 지표 수집."""
    try:
        tk = yf.Ticker(ticker_str)
        info = tk.info or {}

        price = info.get("regularMarketPrice") or info.get("previousClose")
        prev_close = info.get("previousClose")

        if price is None or price == 0:
            # info 실패 시 history fallback
            hist = tk.history(period="5d")
            if hist is not None and len(hist) > 0:
                price = round(float(hist["Close"].iloc[-1]), 4)
                if len(hist) > 1:
                    prev_close = round(float(hist["Close"].iloc[-2]), 4)

        if price is None or price == 0:
            print(f"  ❌ {ticker_str} ({meta['name']}): 가격 없음")
            return None

        price = round(float(price), 4)
        change = round(price - float(prev_close), 4) if prev_close else 0
        change_pct = round((change / float(prev_close)) * 100, 2) if prev_close and prev_close != 0 else 0

        result = {
            "ticker": ticker_str,
            "name": meta["name"],
            "cat": meta["cat"],
            "unit": meta["unit"],
            "price": price,
            "prev_close": round(float(prev_close), 4) if prev_close else None,
            "change": change,
            "change_pct": change_pct,
        }
        print(f"  ✅ {ticker_str} ({meta['name']}): {price} ({change_pct:+.2f}%)")
        return result

    except Exception as e:
        print(f"  ❌ {ticker_str} ({meta['name']}): {e}")
        traceback.print_exc()
        return None


def load_rates():
    """fetch_rates.py가 생성한 rates.json 읽기."""
    if not os.path.exists(RATES_FILE):
        print("  ⚠ rates.json 없음 — 환율·금시세 미포함")
        return None
    try:
        with open(RATES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        rates = data.get("rates", {})
        print(f"  ✅ rates.json 로드: USD {rates.get('USD_KRW')}, 금 {rates.get('GOLD_KRW_G')}")
        return {
            "updated": data.get("updated", ""),
            "USD_KRW": rates.get("USD_KRW"),
            "JPY100_KRW": rates.get("JPY100_KRW"),
            "CNY_KRW": rates.get("CNY_KRW"),
            "GOLD_KRW_G": rates.get("GOLD_KRW_G"),
        }
    except Exception as e:
        print(f"  ⚠ rates.json 읽기 실패: {e}")
        return None


def append_history(entry):
    """히스토리 파일에 오늘 데이터 추가 (같은 날짜면 덮어쓰기, 무제한 보관)."""
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = []

    today = entry["date"]
    history = [h for h in history if h.get("date") != today]
    history.append(entry)
    history.sort(key=lambda x: x["date"])

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)

    print(f"  히스토리: {len(history)}일치 보관 중")


def main():
    now = datetime.now(KST)
    print(f"📊 시장 지표 수집 시작: {now.strftime('%Y-%m-%d %H:%M KST')}")
    print(f"   대상: {len(INDICATORS)}개 지표 + 환율·금시세(rates.json)\n")

    # 1. yfinance 지표 수집
    indicators = []
    ok = fail = 0
    for ticker, meta in INDICATORS.items():
        data = fetch_indicator(ticker, meta)
        if data:
            indicators.append(data)
            ok += 1
        else:
            fail += 1
        time.sleep(DELAY)

    # 2. 환율·금시세 (rates.json에서 읽기)
    rates = load_rates()

    # 3. 최신 파일 저장
    result = {
        "updated": now.strftime("%Y-%m-%d %H:%M KST"),
        "indicators": indicators,
    }
    if rates:
        result["rates"] = rates

    os.makedirs(os.path.join(ROOT_DIR, "data"), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    # 4. 히스토리 누적 (플랫 구조 — 차트용)
    hist_entry = {"date": now.strftime("%Y-%m-%d")}
    for ind in indicators:
        # 키: 티커에서 특수문자 제거 (^GSPC → GSPC, CL=F → CLF)
        key = ind["ticker"].replace("^", "").replace("=", "")
        hist_entry[key] = ind["price"]
    if rates:
        for k in ["USD_KRW", "JPY100_KRW", "CNY_KRW", "GOLD_KRW_G"]:
            if rates.get(k):
                hist_entry[k] = rates[k]
    append_history(hist_entry)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f"\n✅ 저장: {OUTPUT} ({size_kb:.1f}KB)")
    print(f"   성공 {ok} / 실패 {fail}")


if __name__ == "__main__":
    main()
