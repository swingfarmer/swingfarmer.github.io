#!/usr/bin/env python3
"""
fetch_putcall.py — CBOE Put/Call Ratio 수집
CBOE 공식 데이터 → data/dashboard/putcall.json

수집 항목:
  - CBOE Total Put/Call Ratio (equity + index)
  - CBOE Equity Only Put/Call Ratio
  - 5일 / 21일 이동평균 자동 계산

데이터 소스:
  - CBOE 공식 CSV 다운로드 (Historical Volume)
  - Fallback: yfinance에서 VIX 기반 추정 (정확도 낮음)

crontab: 평일 07:15 (미장 마감 후, 한국시간 기준)
  15 7 * * 2-6 cd /home/opc/swingfarmer.github.io && . ~/.env_secrets && python3 scripts/fetch_putcall.py >> logs/putcall.log 2>&1

(월~금 미국장 마감 후 = 한국시간 화~토 아침)
"""

import os, sys, json, datetime, pathlib, io

try:
    import requests
except ImportError:
    print("[ERROR] requests 필요: pip install requests")
    sys.exit(1)

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
DATA_DIR = REPO_DIR / "data" / "dashboard"
OUTPUT_FILE = DATA_DIR / "putcall.json"

TODAY_DASH = datetime.date.today().strftime("%Y-%m-%d")


def fetch_cboe_putcall():
    """
    CBOE 공식 Put/Call Ratio 다운로드
    https://www.cboe.com/us/options/market_statistics/historical_data/
    
    총 P/C (equity + index): totalpc.csv
    Equity only P/C: equitypc.csv
    """
    results = []

    # Total P/C Ratio
    urls = {
        "total": "https://cdn.cboe.com/api/global/us_options/market_statistics/daily/totalpc.csv",
        "equity": "https://cdn.cboe.com/api/global/us_options/market_statistics/daily/equitypc.csv",
        "index": "https://cdn.cboe.com/api/global/us_options/market_statistics/daily/indexpc.csv",
    }

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    total_pcr = None
    equity_pcr = None

    for kind, url in urls.items():
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code != 200:
                print(f"[WARN] CBOE {kind} CSV 다운로드 실패: {r.status_code}")
                continue

            # CSV 파싱 (간단 처리)
            lines = r.text.strip().split("\n")
            if len(lines) < 2:
                continue

            # 헤더 확인
            header = lines[0].lower().replace(" ", "")
            # 보통: TRADE_DATE,CALL,PUT,TOTAL,P/C RATIO
            for line in reversed(lines[1:]):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 5:
                    continue
                try:
                    date_str = parts[0]  # MM/DD/YYYY 또는 YYYY-MM-DD
                    pcr = float(parts[4]) if parts[4] else None
                    call_vol = int(parts[1]) if parts[1] else 0
                    put_vol = int(parts[2]) if parts[2] else 0

                    if kind == "total":
                        total_pcr = pcr
                    elif kind == "equity":
                        equity_pcr = pcr

                    # 최신 행만 가져옴
                    print(f"[CBOE {kind}] {date_str}: P/C = {pcr}, Call={call_vol:,}, Put={put_vol:,}")
                    break
                except (ValueError, IndexError):
                    continue

        except Exception as e:
            print(f"[ERROR] CBOE {kind}: {e}")

    return total_pcr, equity_pcr


def fetch_cboe_history():
    """최근 250일치 Total P/C Ratio 히스토리"""
    url = "https://cdn.cboe.com/api/global/us_options/market_statistics/daily/totalpc.csv"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            return []

        lines = r.text.strip().split("\n")
        history = []

        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                date_raw = parts[0]
                # MM/DD/YYYY → YYYY-MM-DD
                if "/" in date_raw:
                    m, d, y = date_raw.split("/")
                    date_str = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                else:
                    date_str = date_raw

                pcr = float(parts[4]) if parts[4] else None
                call_vol = int(parts[1]) if parts[1] else 0
                put_vol = int(parts[2]) if parts[2] else 0

                if pcr is not None:
                    history.append({
                        "date": date_str,
                        "pcr": pcr,
                        "call_vol": call_vol,
                        "put_vol": put_vol,
                    })
            except (ValueError, IndexError):
                continue

        # 날짜순 정렬
        history.sort(key=lambda x: x["date"])
        print(f"[CBOE] 총 {len(history)}일 히스토리 로드")
        return history[-250:]  # 최근 250일

    except Exception as e:
        print(f"[ERROR] CBOE 히스토리: {e}")
        return []


def calc_moving_averages(history):
    """5일, 21일 이동평균 계산"""
    for i, entry in enumerate(history):
        pcr = entry.get("pcr")
        if pcr is None:
            continue

        # 5일 MA
        if i >= 4:
            vals = [history[j]["pcr"] for j in range(i-4, i+1) if history[j].get("pcr") is not None]
            entry["ma5"] = round(sum(vals) / len(vals), 4) if vals else None
        else:
            entry["ma5"] = None

        # 21일 MA
        if i >= 20:
            vals = [history[j]["pcr"] for j in range(i-20, i+1) if history[j].get("pcr") is not None]
            entry["ma21"] = round(sum(vals) / len(vals), 4) if vals else None
        else:
            entry["ma21"] = None

    return history


def save_data(history):
    """저장"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    latest = history[-1] if history else {}
    output = {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "latest": latest,
        "history": history,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] 저장: {OUTPUT_FILE} ({len(history)}일)")


def main():
    print(f"=== fetch_putcall.py — {TODAY_DASH} ===")

    # CBOE에서 전체 히스토리 가져오기
    history = fetch_cboe_history()

    if not history:
        print("[ERROR] CBOE 데이터 로드 실패")
        sys.exit(1)

    # 이동평균 계산
    history = calc_moving_averages(history)

    # 저장
    save_data(history)


if __name__ == "__main__":
    main()
