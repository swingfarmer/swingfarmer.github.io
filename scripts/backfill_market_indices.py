#!/usr/bin/env python3
"""
시장 지수 백필 — yfinance → market_history.json
================================================
S&P500, 나스닥, 다우, VIX, 금리, WTI, 코스닥을
market_history.json의 기존 엔트리에 병합.

사용법 (VM에서):
  cd ~/swingfarmer.github.io
  python3 scripts/backfill_market_indices.py

기본: 2025-01-01 ~ 오늘. 이미 있는 날짜는 키만 병합 (기존 데이터 유지).
"""

import json
import os
import time
from datetime import datetime, timedelta

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance 필요: pip install yfinance --break-system-packages")
    raise SystemExit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
HISTORY_FILE = os.path.join(ROOT_DIR, "data", "market_history.json")

START_DATE = "2025-01-01"

# 백필 대상: yfinance 티커 → market_history.json 키
# fetch_market_indicators.py의 키 변환 규칙: ^ 제거, = 제거, .KS 제거
TARGETS = {
    "^GSPC":  {"key": "GSPC",  "name": "S&P 500",         "decimals": 2},
    "^IXIC":  {"key": "IXIC",  "name": "나스닥 종합",      "decimals": 2},
    "^DJI":   {"key": "DJI",   "name": "다우 산업",        "decimals": 2},
    "^VIX":   {"key": "VIX",   "name": "VIX",             "decimals": 2},
    "^IRX":   {"key": "IRX",   "name": "미국 13주 T-Bill", "decimals": 3},
    "^FVX":   {"key": "FVX",   "name": "미국 5년물",       "decimals": 3},
    "^TNX":   {"key": "TNX",   "name": "미국 10년물",      "decimals": 3},
    "^TYX":   {"key": "TYX",   "name": "미국 30년물",      "decimals": 3},
    "CL=F":   {"key": "CLF",   "name": "WTI 원유",        "decimals": 2},
    "^KQ11":  {"key": "KQ11",  "name": "코스닥",           "decimals": 2},
}


def main():
    # 1. 기존 히스토리 로드
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    print(f"📂 기존 히스토리: {len(history)}일치")

    # date → entry 인덱스 맵
    date_map = {}
    for i, h in enumerate(history):
        date_map[h["date"]] = i

    # 이미 있는 키 확인
    first_with = {}
    for h in history:
        for k in h:
            if k != "date" and k not in first_with:
                first_with[k] = h["date"]
    print("\n현재 키별 시작일:")
    for k in sorted(first_with.keys()):
        print(f"  {k}: {first_with[k]}")

    # 2. yfinance로 지수별 종가 다운로드
    end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    total_added = 0

    for ticker, meta in TARGETS.items():
        key = meta["key"]
        dec = meta["decimals"]
        print(f"\n📈 {ticker} → {key} ({meta['name']}) 다운로드 중...", end="", flush=True)

        try:
            df = yf.download(ticker, start=START_DATE, end=end_date,
                             progress=False, auto_adjust=True)
            if df is None or len(df) == 0:
                print(f" ✗ 데이터 없음")
                continue

            count = 0
            skipped = 0
            for idx_val, row in df.iterrows():
                dt = idx_val.strftime("%Y-%m-%d")
                close = round(float(row["Close"]), dec)
                if close <= 0:
                    continue

                if dt in date_map:
                    entry = history[date_map[dt]]
                    if key not in entry:
                        entry[key] = close
                        count += 1
                    else:
                        skipped += 1
                else:
                    # 새 날짜 (보통 미국 장만 열린 날) — 엔트리 생성
                    new_entry = {"date": dt, key: close}
                    history.append(new_entry)
                    date_map[dt] = len(history) - 1
                    count += 1

            print(f" ✓ {len(df)}거래일 (추가 {count}, 기존 {skipped})")
            total_added += count

        except Exception as e:
            print(f" ✗ 에러: {e}")

        time.sleep(1)  # rate limit 대비

    # 3. 정렬 후 저장
    history.sort(key=lambda x: x["date"])
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)

    print(f"\n{'='*50}")
    print(f"✅ 완료: {total_added}건 추가/병합")
    print(f"   히스토리: {len(history)}일치 보관 중")
    size_kb = os.path.getsize(HISTORY_FILE) / 1024
    print(f"   파일 크기: {size_kb:.1f}KB")

    # 백필 후 키별 시작일 재확인
    first_with2 = {}
    for h in history:
        for k in h:
            if k != "date" and k not in first_with2:
                first_with2[k] = h["date"]
    print("\n백필 후 키별 시작일:")
    for k in sorted(first_with2.keys()):
        marker = " ← NEW" if k not in first_with or first_with2[k] != first_with[k] else ""
        print(f"  {k}: {first_with2[k]}{marker}")


if __name__ == "__main__":
    main()
