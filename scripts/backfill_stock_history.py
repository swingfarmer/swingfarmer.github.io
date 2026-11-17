#!/usr/bin/env python3
"""
종목 수익률 비교용 백필 — yfinance → market_history.json
========================================================
포트폴리오 '종목 수익률 비교' 차트에 필요한 개별 종목 종가를
market_history.json에 백필.

사용법 (VM에서):
  python3 scripts/backfill_stock_history.py

기본: 2025-01-01 ~ 오늘. 이미 있는 날짜는 종목 키만 병합 (기존 데이터 유지).
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

# 백필 대상 종목
STOCKS = {
    "005930.KS": "005930",   # 삼성전자
    "000660.KS": "000660",   # SK하이닉스
    "042660.KS": "042660",   # 한화오션
    "010140.KS": "010140",   # 삼성중공업
    "003490.KS": "003490",   # 대한항공
    "000720.KS": "000720",   # 현대건설
    "004020.KS": "004020",   # 현대제철
    "028670.KS": "028670",   # 팬오션
}

START_DATE = "2025-01-01"


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

    # 2. yfinance로 종목별 종가 다운로드
    end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    total_added = 0

    for ticker, key in STOCKS.items():
        print(f"\n📈 {ticker} ({key}) 다운로드 중...", end="", flush=True)
        try:
            df = yf.download(ticker, start=START_DATE, end=end_date,
                             progress=False, auto_adjust=True)
            if df is None or len(df) == 0:
                print(f" ✗ 데이터 없음")
                continue

            count = 0
            for idx_val, row in df.iterrows():
                dt = idx_val.strftime("%Y-%m-%d")
                close = round(float(row["Close"]), 0)  # 원 단위 정수
                if close <= 0:
                    continue

                if dt in date_map:
                    # 기존 엔트리에 종목 키 추가
                    entry = history[date_map[dt]]
                    if key not in entry:
                        entry[key] = int(close)
                        count += 1
                else:
                    # 새 날짜 엔트리 생성
                    new_entry = {"date": dt, key: int(close)}
                    history.append(new_entry)
                    date_map[dt] = len(history) - 1
                    count += 1

            print(f" ✓ {len(df)}거래일 ({count}건 추가/병합)")
            total_added += count

        except Exception as e:
            print(f" ✗ 에러: {e}")

        time.sleep(0.5)

    # 3. 정렬 후 저장
    history.sort(key=lambda x: x["date"])
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)

    print(f"\n{'='*50}")
    print(f"✅ 완료: {total_added}건 추가/병합")
    print(f"   히스토리: {len(history)}일치 보관 중")
    size_kb = os.path.getsize(HISTORY_FILE) / 1024
    print(f"   파일 크기: {size_kb:.1f}KB")


if __name__ == "__main__":
    main()
