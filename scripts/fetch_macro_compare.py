"""
매크로 비교 차트 데이터 수집
============================
1) 반도체 랠리: 나스닥100(^NDX) vs 필라델피아 반도체(^SOX)
2) 3저 호황: 1983~1989 코스피 vs 2023~ 코스피 (경과 거래일 기준)
3) 3저 지표: 환율(KRW=X) / 금리(^TNX) / 유가(CL=F)

출력: data/macro/semiconductor.json, triple_low_compare.json, triple_low_indicator.json

사용법:
  python3 scripts/fetch_macro_compare.py              # 오늘 데이터 추가
  python3 scripts/fetch_macro_compare.py --backfill    # 전체 백필 (최초 1회)

환경변수: 없음 (yfinance)
크론: 매일 18:50 (auto_push 전)
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import yfinance as yf

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data", "macro")
DELAY = 1.0

os.makedirs(DATA_DIR, exist_ok=True)

# ── 파일 경로 ──
SEMI_FILE = os.path.join(DATA_DIR, "semiconductor.json")
TRIPLE_CMP_FILE = os.path.join(DATA_DIR, "triple_low_compare.json")
TRIPLE_IND_FILE = os.path.join(DATA_DIR, "triple_low_indicator.json")


def fetch_ticker(ticker, start, end=None, period=None):
    """yfinance로 종가 시계열 가져오기. [{date, close}]"""
    try:
        if period:
            df = yf.download(ticker, period=period, progress=False)
        else:
            df = yf.download(ticker, start=start, end=end, progress=False)
        time.sleep(DELAY)
        if df.empty:
            print(f"  ⚠ {ticker}: 데이터 없음")
            return []
        # MultiIndex 처리 (yfinance 0.2.x)
        if hasattr(df.columns, 'levels'):
            close_col = ('Close', ticker) if ('Close', ticker) in df.columns else 'Close'
        else:
            close_col = 'Close'
        result = []
        for idx, row in df.iterrows():
            try:
                c = float(row[close_col])
            except (KeyError, TypeError):
                c = float(row.iloc[3])  # fallback: 4th column = Close
            if c > 0:
                result.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "close": round(c, 2)
                })
        print(f"  ✓ {ticker}: {len(result)}건 ({result[0]['date']}~{result[-1]['date']})")
        return result
    except Exception as e:
        print(f"  ✗ {ticker}: {e}")
        return []


def load_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    print(f"  💾 {os.path.basename(path)} 저장 ({os.path.getsize(path)//1024}KB)")


def merge_daily(existing, new_data, key="date"):
    """기존 데이터에 새 데이터 병합 (날짜 기준 중복 제거, 최신 우선)"""
    if not existing:
        return new_data
    date_map = {r[key]: r for r in existing}
    for r in new_data:
        date_map[r[key]] = r
    merged = sorted(date_map.values(), key=lambda x: x[key])
    return merged


# ──────────────────────────────────────
# 1) 반도체 랠리
# ──────────────────────────────────────
def fetch_semiconductor(backfill=False):
    print("\n[1/3] 반도체 랠리 (나스닥100 vs 필라델피아 반도체)")
    if backfill:
        start = "1996-01-01"
    else:
        start = (datetime.now(KST) - timedelta(days=10)).strftime("%Y-%m-%d")

    ndx = fetch_ticker("^NDX", start=start)
    sox = fetch_ticker("^SOX", start=start)

    if not ndx and not sox:
        print("  ⚠ 데이터 없음, 스킵")
        return

    # 날짜 기준 merge
    date_map = {}
    for r in ndx:
        date_map[r["date"]] = {"date": r["date"], "ndx": r["close"]}
    for r in sox:
        if r["date"] in date_map:
            date_map[r["date"]]["sox"] = r["close"]
        else:
            date_map[r["date"]] = {"date": r["date"], "sox": r["close"]}

    new_data = sorted(date_map.values(), key=lambda x: x["date"])

    existing = load_json(SEMI_FILE)
    if existing and not backfill:
        merged = merge_daily(existing, new_data)
    else:
        merged = new_data

    save_json(SEMI_FILE, merged)


# ──────────────────────────────────────
# 2) 3저 호황 비교
# ──────────────────────────────────────
def fetch_triple_low_compare(backfill=False):
    print("\n[2/3] 3저 호황 vs 현재 코스피")

    if backfill:
        # 과거: 1983~1989 코스피
        print("  과거 3저 호황 기간 (1983~1989)...")
        past = fetch_ticker("^KS11", start="1983-01-01", end="1990-01-01")

        # 현재: 2023~현재 코스피
        print("  현재 코스피 (2023~)...")
        current = fetch_ticker("^KS11", start="2023-01-01")

        data = {
            "past": past,
            "current": current,
            "past_label": "3저 호황 (1983~1989)",
            "current_label": "현재 코스피 (2023~)",
            "past_start": "1983-06-01",
            "current_start": "2023-01-01"
        }
        save_json(TRIPLE_CMP_FILE, data)
    else:
        # 일별 업데이트: current만 추가
        existing = load_json(TRIPLE_CMP_FILE)
        if not existing:
            print("  ⚠ 기존 데이터 없음. --backfill 먼저 실행하세요.")
            return

        start = (datetime.now(KST) - timedelta(days=10)).strftime("%Y-%m-%d")
        current_new = fetch_ticker("^KS11", start=start)
        if current_new:
            existing["current"] = merge_daily(existing.get("current", []), current_new)
            save_json(TRIPLE_CMP_FILE, existing)


# ──────────────────────────────────────
# 3) 3저 지표 (환율/금리/유가)
# ──────────────────────────────────────
def fetch_triple_low_indicator(backfill=False):
    print("\n[3/3] 3저 지표 (환율/금리/유가)")
    if backfill:
        start = "2020-01-01"
    else:
        start = (datetime.now(KST) - timedelta(days=10)).strftime("%Y-%m-%d")

    krw = fetch_ticker("KRW=X", start=start)
    tnx = fetch_ticker("^TNX", start=start)
    clf = fetch_ticker("CL=F", start=start)

    # 각각 별도 키로 저장
    new_data = {}
    date_set = set()
    for r in krw:
        date_set.add(r["date"])
        new_data.setdefault(r["date"], {})["krw"] = r["close"]
    for r in tnx:
        date_set.add(r["date"])
        new_data.setdefault(r["date"], {})["tnx"] = r["close"]
    for r in clf:
        date_set.add(r["date"])
        new_data.setdefault(r["date"], {})["clf"] = r["close"]

    records = []
    for d in sorted(date_set):
        row = {"date": d}
        row.update(new_data.get(d, {}))
        records.append(row)

    existing = load_json(TRIPLE_IND_FILE)
    if existing and not backfill:
        merged = merge_daily(existing, records)
    else:
        merged = records

    save_json(TRIPLE_IND_FILE, merged)


# ──────────────────────────────────────
if __name__ == "__main__":
    backfill = "--backfill" in sys.argv
    print(f"{'='*40}")
    print(f"매크로 비교 데이터 수집 {'(백필)' if backfill else '(일별)'}")
    print(f"{'='*40}")

    fetch_semiconductor(backfill)
    fetch_triple_low_compare(backfill)
    fetch_triple_low_indicator(backfill)

    print(f"\n{'='*40}")
    print("완료!")
