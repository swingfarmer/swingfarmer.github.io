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

import urllib.request

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

    # 한국 개별종목 (포트폴리오 종목 수익률 비교용)
    "005930.KS": {"name": "삼성전자",     "cat": "kr_stock", "unit": "₩"},
    "000660.KS": {"name": "SK하이닉스",   "cat": "kr_stock", "unit": "₩"},
    "042660.KS": {"name": "한화오션",     "cat": "kr_stock", "unit": "₩"},
    "010140.KS": {"name": "삼성중공업",   "cat": "kr_stock", "unit": "₩"},
    "003490.KS": {"name": "대한항공",     "cat": "kr_stock", "unit": "₩"},
    "000720.KS": {"name": "현대건설",     "cat": "kr_stock", "unit": "₩"},
    "004020.KS": {"name": "현대제철",     "cat": "kr_stock", "unit": "₩"},
    "028670.KS": {"name": "팬오션",       "cat": "kr_stock", "unit": "₩"},
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


def get_kis_token():
    """한투 API 접근토큰 발급."""
    app_key = os.environ.get('KIS_APP_KEY', '')
    app_secret = os.environ.get('KIS_APP_SECRET', '')
    if not app_key or not app_secret:
        print("  ⚠ KIS_APP_KEY/KIS_APP_SECRET 없음 — 선물 미수집")
        return None
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    body = json.dumps({
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }).encode()
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"})
    try:
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read())
        return data.get("access_token")
    except Exception as e:
        print(f"  ❌ KIS 토큰 발급 실패: {e}")
        return None


def fetch_kospi200_futures():
    """한투 API로 코스피200 선물 현재가 조회 (야간 포함)."""
    token = get_kis_token()
    if not token:
        return None
    app_key = os.environ.get('KIS_APP_KEY', '')
    app_secret = os.environ.get('KIS_APP_SECRET', '')
    url = ("https://openapi.koreainvestment.com:9443"
           "/uapi/domestic-futureoption/v1/quotations/inquire-price"
           "?FID_COND_MRKT_DIV_CODE=F&FID_INPUT_ISCD=101S6000")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHMIF10000000",
        "custtype": "P",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read())
        out = data.get("output", {})
        price = float(out.get("futs_prpr", 0))        # 현재가
        prev  = float(out.get("futs_prdy_clpr", 0))   # 전일종가
        if price == 0:
            print("  ❌ 코스피200 선물: 가격 없음 (장 외 시간)")
            return None
        change = round(price - prev, 2)
        change_pct = round(change / prev * 100, 2) if prev else 0
        result = {
            "ticker": "KOSPI200F",
            "name": "코스피200 선물",
            "cat": "kr_futures",
            "unit": "pt",
            "price": price,
            "prev_close": prev,
            "change": change,
            "change_pct": change_pct,
        }
        print(f"  ✅ KOSPI200F (코스피200 선물): {price} ({change_pct:+.2f}%)")
        return result
    except Exception as e:
        print(f"  ❌ 코스피200 선물 조회 실패: {e}")
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

    # 2. 코스피200 선물 (한투 API — 야간 포함)
    fut = fetch_kospi200_futures()
    if fut:
        indicators.append(fut)
        ok += 1

    # 3. 환율·금시세 (rates.json에서 읽기)
    rates = load_rates()

    # 4. 최신 파일 저장
    result = {
        "updated": now.strftime("%Y-%m-%d %H:%M KST"),
        "indicators": indicators,
    }
    if rates:
        result["rates"] = rates

    os.makedirs(os.path.join(ROOT_DIR, "data"), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    # 5. 히스토리 누적 (플랫 구조 — 차트용)
    hist_entry = {"date": now.strftime("%Y-%m-%d")}
    for ind in indicators:
        # 키: 티커에서 특수문자 제거 (^GSPC → GSPC, CL=F → CLF, 005930.KS → 005930)
        key = ind["ticker"].replace("^", "").replace("=", "").replace(".KS", "")
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
