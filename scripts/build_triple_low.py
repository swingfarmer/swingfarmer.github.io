"""
3저 호황 비교 데이터 빌드 (1회성)
=================================
1) data/macro/kospi_1980_1989_daily.json (pykrx로 생성된 일별) → 주별 리샘플링
2) yfinance ^KS11 2023~ 일별 → 주별 리샘플링
3) 합쳐서 data/macro/triple_low_compare.json 생성

사용법:
  python3 scripts/build_triple_low.py
"""
import json, os, time
from datetime import datetime, timezone, timedelta
import yfinance as yf

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data", "macro")

DAILY_FILE = os.path.join(DATA_DIR, "kospi_1980_1989_daily.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "triple_low_compare.json")


def daily_to_weekly(rows):
    """일별 [{date, close}] → 주별 (각 주 마지막 거래일 기준)"""
    from collections import OrderedDict
    weeks = OrderedDict()
    for r in rows:
        # ISO week: (year, week_number)
        dt = datetime.strptime(r["date"], "%Y-%m-%d")
        iso = dt.isocalendar()
        wk = f"{iso[0]:04d}-W{iso[1]:02d}"
        weeks[wk] = r  # 덮어쓰기 → 주의 마지막 거래일
    return list(weeks.values())


def main():
    # 1) 과거 1980~1989 일별 → 주별
    print("[1] 과거 데이터 (1980~1989 일별 → 주별)...")
    with open(DAILY_FILE) as f:
        daily_past = json.load(f)
    print(f"  일별: {len(daily_past)}건 ({daily_past[0]['date']}~{daily_past[-1]['date']})")

    weekly_past = daily_to_weekly(daily_past)
    print(f"  주별: {len(weekly_past)}건 ({weekly_past[0]['date']}~{weekly_past[-1]['date']})")

    # 2) 현재 2023~ 일별 (yfinance) → 주별
    print("\n[2] 현재 데이터 (2023~ yfinance → 주별)...")
    df = yf.download("^KS11", start="2023-01-01", progress=False)
    time.sleep(1)

    if hasattr(df.columns, 'levels'):
        close_col = ('Close', '^KS11') if ('Close', '^KS11') in df.columns else 'Close'
    else:
        close_col = 'Close'

    daily_curr = []
    for idx, row in df.iterrows():
        try:
            c = float(row[close_col])
        except (KeyError, TypeError):
            c = float(row.iloc[3])
        if c > 0:
            daily_curr.append({"date": idx.strftime("%Y-%m-%d"), "close": round(c, 2)})

    print(f"  일별: {len(daily_curr)}건 ({daily_curr[0]['date']}~{daily_curr[-1]['date']})")

    weekly_curr = daily_to_weekly(daily_curr)
    print(f"  주별: {len(weekly_curr)}건 ({weekly_curr[0]['date']}~{weekly_curr[-1]['date']})")

    # 3) JSON 생성
    data = {
        "past": weekly_past,
        "current": weekly_curr,

        "data_freq": "weekly"
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    size = os.path.getsize(OUTPUT_FILE)
    print(f"\n[3] 저장: {OUTPUT_FILE}")
    print(f"  past: {len(weekly_past)}건, current: {len(weekly_curr)}건")
    print(f"  크기: {size // 1024}KB")
    print("완료!")


if __name__ == "__main__":
    main()
