"""
환율(USD/JPY/CNY→KRW) + 금시세(원/g) 수집
→ data/rates.json (최신) + data/rates_history.json (일별 누적, 무제한 보관)
GitHub Actions 매일 자동 실행

# TODO [오라클 이관]
# 오라클 클라우드 세팅 후 rates_history.json을 오라클로 옮기면
# GitHub 쪽 data/rates_history.json 삭제하여 용량 확보 가능.
# 이관 후 이 스크립트도 오라클 cron으로 전환.
"""
import requests
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
HISTORY_FILE = "data/rates_history.json"
MAX_HISTORY_DAYS = None  # 무제한 보관 (오라클 이관 예정)


def fetch_exchange_rates():
    url = "https://api.exchangerate-api.com/v4/latest/KRW"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        d = r.json()["rates"]
        return {
            "USD_KRW": round(1 / d["USD"], 2),
            "JPY100_KRW": round(100 / d["JPY"], 2),
            "CNY_KRW": round(1 / d["CNY"], 2),
        }
    except Exception as e:
        print(f"환율 API 실패: {e}")
        return None


def get_usd_krw_rate():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        r.raise_for_status()
        return r.json()["rates"]["KRW"]
    except:
        return None


def fetch_gold_price_krw():
    usd_krw = get_usd_krw_rate()
    if not usd_krw:
        print("  금시세: USD/KRW 환율 조회 실패")
        return None

    # 1순위: metals.live (무료, 키 불필요)
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                usd_oz = float(data[0].get("price", 0))
                if usd_oz > 500:
                    g = round(usd_oz * usd_krw / 31.1035, 0)
                    print(f"  금시세(metals.live): ${usd_oz}/oz -> {g:,.0f}원/g")
                    return g
    except Exception as e:
        print(f"  metals.live 실패: {e}")

    # 2순위: Yahoo Finance
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=1d",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        if r.status_code == 200:
            p = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
            if p > 500:
                g = round(p * usd_krw / 31.1035, 0)
                print(f"  금시세(Yahoo): ${p}/oz -> {g:,.0f}원/g")
                return g
    except Exception as e:
        print(f"  Yahoo 실패: {e}")

    print("  금시세: 모든 소스 실패")
    return None


def append_history(entry):
    """히스토리 파일에 오늘 데이터 추가 (같은 날짜 덮어쓰기, 무제한 보관)"""
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

    # 무제한 보관 — 삭제 로직 없음

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)

    print(f"  히스토리: {len(history)}일치 보관 중")


def main():
    now = datetime.now(KST)
    rates = fetch_exchange_rates()
    if rates is None:
        print("환율 수집 실패")
        return

    gold = fetch_gold_price_krw()

    result = {
        "updated": now.strftime("%Y-%m-%d %H:%M KST"),
        "source": "exchangerate-api.com",
        "rates": {"USD_KRW": rates["USD_KRW"], "JPY100_KRW": rates["JPY100_KRW"], "CNY_KRW": rates["CNY_KRW"]}
    }
    if gold:
        result["rates"]["GOLD_KRW_G"] = gold

    os.makedirs("data", exist_ok=True)
    with open("data/rates.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    hist_entry = {"date": now.strftime("%Y-%m-%d"), "USD_KRW": rates["USD_KRW"], "JPY100_KRW": rates["JPY100_KRW"], "CNY_KRW": rates["CNY_KRW"]}
    if gold:
        hist_entry["GOLD_KRW_G"] = gold
    append_history(hist_entry)

    print(f"✅ 저장 완료: {now.strftime('%Y-%m-%d %H:%M')}")
    for k, v in result["rates"].items():
        print(f"  {k}: {v:,.2f}")


if __name__ == "__main__":
    main()
