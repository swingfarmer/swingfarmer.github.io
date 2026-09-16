"""
환율(USD/JPY/CNY→KRW) + 금시세(원/g) 수집 → data/rates.json
GitHub Actions에서 매일 자동 실행
"""
import requests
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def fetch_exchange_rates():
    """exchangerate-api.com (무료, API키 불필요)"""
    url = "https://api.exchangerate-api.com/v4/latest/KRW"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        rates = data["rates"]
        return {
            "USD_KRW": round(1 / rates["USD"], 2),
            "JPY100_KRW": round(100 / rates["JPY"], 2),
            "CNY_KRW": round(1 / rates["CNY"], 2),
        }
    except Exception as e:
        print(f"환율 API 실패: {e}")
        return None


def get_usd_krw_rate():
    """환율 단독 조회 (금시세 환산용)"""
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        r.raise_for_status()
        return r.json()["rates"]["KRW"]
    except:
        return None


def fetch_gold_price_krw():
    """
    금시세 (원/g) — 3단계 폴백
    1) metals.live  무료 API (키 불필요)
    2) frankfurter.app → USD/XAU 역산
    3) 실패 시 None
    """
    usd_krw = get_usd_krw_rate()
    if not usd_krw:
        print("  금시세: USD/KRW 환율 조회 실패 → 스킵")
        return None

    # ── 방법 1: metals.live (무료, 키 불필요) ──
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        if r.status_code == 200:
            data = r.json()
            # [{timestamp, price}] 형태
            if isinstance(data, list) and len(data) > 0:
                usd_per_oz = float(data[0].get("price", 0))
                if usd_per_oz > 500:
                    krw_per_g = round(usd_per_oz * usd_krw / 31.1035, 0)
                    print(f"  금시세(metals.live): ${usd_per_oz}/oz → {krw_per_g:,.0f}원/g")
                    return krw_per_g
    except Exception as e:
        print(f"  metals.live 실패: {e}")

    # ── 방법 2: Yahoo Finance 스크래핑 (GC=F) ──
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=1d",
            headers=headers, timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            if price > 500:
                krw_per_g = round(price * usd_krw / 31.1035, 0)
                print(f"  금시세(Yahoo): ${price}/oz → {krw_per_g:,.0f}원/g")
                return krw_per_g
    except Exception as e:
        print(f"  Yahoo Finance 실패: {e}")

    print("  금시세: 모든 소스 실패")
    return None


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
        "rates": {
            "USD_KRW": rates["USD_KRW"],
            "JPY100_KRW": rates["JPY100_KRW"],
            "CNY_KRW": rates["CNY_KRW"],
        }
    }

    if gold:
        result["rates"]["GOLD_KRW_G"] = gold

    os.makedirs("data", exist_ok=True)
    with open("data/rates.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ 저장 완료: {now.strftime('%Y-%m-%d %H:%M')}")
    for k, v in result["rates"].items():
        print(f"  {k}: {v:,.2f}")


if __name__ == "__main__":
    main()
