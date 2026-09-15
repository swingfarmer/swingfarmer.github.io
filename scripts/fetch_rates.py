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

def fetch_gold_price_krw():
    """금시세 (USD/oz → 원/g 변환)"""
    # 방법1: 무료 API
    try:
        url = "https://api.metalpriceapi.com/v1/latest?api_key=demo&base=XAU&currencies=KRW"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("success"):
                krw_per_oz = data["rates"]["KRW"]
                krw_per_g = round(krw_per_oz / 31.1035, 0)
                return krw_per_g
    except:
        pass

    # 방법2: 대체 계산 (금 USD/oz × 환율 ÷ 31.1035g)
    try:
        # 금 국제시세
        gold_url = "https://api.exchangerate-api.com/v4/latest/XAU"
        r = requests.get(gold_url, timeout=10)
        if r.status_code == 200:
            usd_per_oz = 1 / r.json()["rates"]["USD"]
            # 환율
            fx = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
            krw_per_usd = fx["rates"]["KRW"]
            krw_per_g = round(usd_per_oz * krw_per_usd / 31.1035, 0)
            return krw_per_g
    except:
        pass

    print("금시세 API 실패 - 기본값 사용")
    return None

def main():
    now = datetime.now(KST)
    
    rates = fetch_exchange_rates()
    gold = fetch_gold_price_krw()
    
    if rates is None:
        print("환율 수집 실패")
        return
    
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
