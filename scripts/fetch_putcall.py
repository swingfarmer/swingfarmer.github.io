#!/usr/bin/env python3
"""
fetch_putcall.py — Put/Call Ratio 수집 (yfinance SPY 옵션체인)
SPY 전체 만기 옵션 거래량에서 P/C ratio 계산
→ data/dashboard/putcall.json

crontab: 평일 07:15 (미장 마감 후, 한국시간 기준)
  15 7 * * 2-6 cd /home/opc/swingfarmer.github.io && . /home/opc/.env_secrets && python3 scripts/fetch_putcall.py >> logs/putcall.log 2>&1
"""

import json, datetime, pathlib, sys

try:
    import yfinance as yf
except ImportError:
    print("[ERROR] yfinance 필요: pip install yfinance")
    sys.exit(1)

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
DATA_DIR = REPO_DIR / "data" / "dashboard"
OUTPUT_FILE = DATA_DIR / "putcall.json"
TODAY_DASH = datetime.date.today().strftime("%Y-%m-%d")


def fetch_spy_putcall():
    """SPY 옵션체인에서 전체 만기 P/C ratio 계산"""
    try:
        spy = yf.Ticker("SPY")
        expirations = spy.options
        if not expirations:
            print("[ERROR] SPY 옵션 만기 없음")
            return None, None, None

        total_call_vol = 0
        total_put_vol = 0

        # 가까운 만기 4개만 (유동성 집중)
        for exp in expirations[:4]:
            try:
                chain = spy.option_chain(exp)
                cv = chain.calls["volume"].sum()
                pv = chain.puts["volume"].sum()
                if cv > 0 or pv > 0:
                    total_call_vol += int(cv) if cv == cv else 0  # NaN 체크
                    total_put_vol += int(pv) if pv == pv else 0
            except Exception as e:
                print(f"[WARN] 만기 {exp} 스킵: {e}")
                continue

        if total_call_vol == 0:
            print("[ERROR] 콜 거래량 0")
            return None, None, None

        pcr = round(total_put_vol / total_call_vol, 4)
        print(f"[SPY] Put={total_put_vol:,} Call={total_call_vol:,} P/C={pcr}")
        return pcr, total_call_vol, total_put_vol

    except Exception as e:
        print(f"[ERROR] SPY 옵션체인: {e}")
        return None, None, None


def load_history():
    """기존 히스토리 로드"""
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("history", [])
    return []


def calc_moving_averages(history):
    """5일, 21일 이동평균"""
    for i, entry in enumerate(history):
        pcr = entry.get("pcr")
        if pcr is None:
            continue

        if i >= 4:
            vals = [history[j]["pcr"] for j in range(i-4, i+1) if history[j].get("pcr") is not None]
            entry["ma5"] = round(sum(vals) / len(vals), 4) if vals else None
        else:
            entry["ma5"] = None

        if i >= 20:
            vals = [history[j]["pcr"] for j in range(i-20, i+1) if history[j].get("pcr") is not None]
            entry["ma21"] = round(sum(vals) / len(vals), 4) if vals else None
        else:
            entry["ma21"] = None

    return history


def save_data(history):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    latest = history[-1] if history else {}
    output = {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "yfinance SPY options (nearest 4 expiries)",
        "latest": latest,
        "history": history,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] 저장: {OUTPUT_FILE} ({len(history)}일)")


def main():
    print(f"=== fetch_putcall.py — {TODAY_DASH} ===")

    pcr, call_vol, put_vol = fetch_spy_putcall()
    if pcr is None:
        print("[ERROR] P/C ratio 수집 실패")
        sys.exit(1)

    history = load_history()

    # 오늘 중복 방지
    history = [h for h in history if h.get("date") != TODAY_DASH]
    history.append({
        "date": TODAY_DASH,
        "pcr": pcr,
        "call_vol": call_vol,
        "put_vol": put_vol,
    })
    history = history[-250:]

    history = calc_moving_averages(history)
    save_data(history)


if __name__ == "__main__":
    main()
