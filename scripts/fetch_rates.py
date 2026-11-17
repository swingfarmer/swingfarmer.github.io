"""
환율(USD/JPY/CNY→KRW) + 금시세(원/g) 수집 — yfinance 기반
==========================================================
→ data/rates.json (최신) + data/rates_history.json (일별 누적)
yfinance: 장중 실시간, 장외 최종 종가. exchangerate-api 대비 엔화 지연 해소.
오라클 cron 07:50 + 18:45.
"""
import json, os, time
from datetime import datetime, timezone, timedelta

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance 필요: pip install yfinance --break-system-packages")
    raise

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
RATES_FILE = os.path.join(ROOT_DIR, "data", "rates.json")
HISTORY_FILE = os.path.join(ROOT_DIR, "data", "rates_history.json")


def fetch_yf_price(ticker_str):
    """yfinance에서 현재가 조회."""
    try:
        tk = yf.Ticker(ticker_str)
        info = tk.info or {}
        price = info.get("regularMarketPrice") or info.get("previousClose")
        if price and price > 0:
            return round(price, 2)
    except Exception as e:
        print(f"  ⚠ {ticker_str} 실패: {e}")
    return None


def fetch_exchange_rates():
    """yfinance로 환율 3종 조회."""
    print("📊 환율 수집 (yfinance)...")

    usd = fetch_yf_price("USDKRW=X")
    time.sleep(0.5)

    # JPY: yfinance는 JPY→KRW 1엔 단위, ×100 필요
    jpy_raw = fetch_yf_price("JPYKRW=X")
    jpy100 = round(jpy_raw * 100, 2) if jpy_raw else None
    time.sleep(0.5)

    cny = fetch_yf_price("CNYKRW=X")

    print(f"  USD/KRW: {usd}")
    print(f"  JPY100/KRW: {jpy100} (원본 {jpy_raw})")
    print(f"  CNY/KRW: {cny}")

    if not usd:
        print("  ❌ USD/KRW 조회 실패")
        return None

    return {
        "USD_KRW": usd,
        "JPY100_KRW": jpy100 or 0,
        "CNY_KRW": cny or 0,
    }


def fetch_gold_price_krw(usd_krw):
    """금시세: yfinance GC=F (금 선물) × 환율."""
    print("📊 금시세 수집...")

    # 1순위: yfinance GC=F
    gold_usd = fetch_yf_price("GC=F")
    if gold_usd and gold_usd > 500:
        g = round(gold_usd * usd_krw / 31.1035, 0)
        print(f"  금(yfinance): ${gold_usd}/oz → {g:,.0f}원/g")
        return g

    # 2순위: metals.live (fallback)
    try:
        import urllib.request
        req = urllib.request.Request("https://api.metals.live/v1/spot/gold")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if isinstance(data, list) and len(data) > 0:
            usd_oz = float(data[0].get("price", 0))
            if usd_oz > 500:
                g = round(usd_oz * usd_krw / 31.1035, 0)
                print(f"  금(metals.live): ${usd_oz}/oz → {g:,.0f}원/g")
                return g
    except Exception as e:
        print(f"  metals.live 실패: {e}")

    print("  ❌ 금시세 수집 실패")
    return None


def append_history(entry):
    """히스토리 파일에 오늘 데이터 추가 (같은 날짜 덮어쓰기)."""
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
    rates = fetch_exchange_rates()
    if rates is None:
        print("❌ 환율 수집 실패")
        return

    gold = fetch_gold_price_krw(rates["USD_KRW"])

    result = {
        "updated": now.strftime("%Y-%m-%d %H:%M KST"),
        "source": "yfinance",
        "rates": {
            "USD_KRW": rates["USD_KRW"],
            "JPY100_KRW": rates["JPY100_KRW"],
            "CNY_KRW": rates["CNY_KRW"],
        }
    }
    if gold:
        result["rates"]["GOLD_KRW_G"] = gold

    os.makedirs(os.path.dirname(RATES_FILE), exist_ok=True)
    with open(RATES_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    hist_entry = {
        "date": now.strftime("%Y-%m-%d"),
        "USD_KRW": rates["USD_KRW"],
        "JPY100_KRW": rates["JPY100_KRW"],
        "CNY_KRW": rates["CNY_KRW"],
    }
    if gold:
        hist_entry["GOLD_KRW_G"] = gold
    append_history(hist_entry)

    print(f"\n✅ 저장 완료: {now.strftime('%Y-%m-%d %H:%M')}")
    for k, v in result["rates"].items():
        print(f"  {k}: {v:,.2f}")


if __name__ == "__main__":
    main()
