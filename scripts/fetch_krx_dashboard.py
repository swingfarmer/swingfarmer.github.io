#!/usr/bin/env python3
"""
KRX 투자자 지표 대시보드 데이터 수집
=====================================
1) 외국인/기관 순매수 Top 20
2) 거래대금 상위 20종목
3) 업종별 등락률 (KRX 업종지수)
4) 시가총액 상위 30 (전일대비 등락)

출력: data/krx/investor_top.json, volume_top.json, sector_change.json, marketcap_top.json

사용법:
  python3 scripts/fetch_krx_dashboard.py              # 오늘
  python3 scripts/fetch_krx_dashboard.py --date 20261027  # 특정일

크론: 평일 20:50
50 20 * * 1-5 . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/fetch_krx_dashboard.py >> ~/logs/fetch_krx_dashboard.log 2>&1
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data", "krx")
os.makedirs(DATA_DIR, exist_ok=True)

TODAY = datetime.now().strftime("%Y%m%d")


def save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    size = os.path.getsize(path)
    print(f"  💾 {filename} 저장 ({size // 1024}KB)")


def get_date(args_date=None):
    """날짜 결정. 주말이면 금요일로."""
    if args_date:
        return args_date
    dt = datetime.now()
    # 주말 → 금요일
    wd = dt.weekday()
    if wd == 5:  # 토
        dt -= timedelta(days=1)
    elif wd == 6:  # 일
        dt -= timedelta(days=2)
    return dt.strftime("%Y%m%d")


# ══════════════════════════════════════
# 1) 외국인/기관 순매수 Top 20
# ══════════════════════════════════════
def fetch_investor_top(date):
    """외국인/기관 순매수 Top 20 (코스피+코스닥)"""
    print("\n[1/4] 외국인/기관 순매수 Top 20")
    try:
        from pykrx import stock
        import pandas as pd

        # 코스피/코스닥 전종목 투자자별 순매수
        df_kospi = stock.get_market_net_purchases_of_equities_by_ticker(date, date, "KOSPI")
        df_kosdaq = stock.get_market_net_purchases_of_equities_by_ticker(date, date, "KOSDAQ")

        if df_kospi.empty and df_kosdaq.empty:
            print("  ⚠ 데이터 없음 (휴장일?)")
            return

        # 컬럼 확인 (버전에 따라 다를 수 있음)
        combined = pd.concat([df_kospi, df_kosdaq])
        print(f"  컬럼: {list(combined.columns)}")

        # 외국인/기관 컬럼명 탐색
        foreign_col = None
        inst_col = None
        for c in combined.columns:
            if '외국인' in str(c): foreign_col = c
            if '기관' in str(c) and '합계' in str(c): inst_col = c
        if not foreign_col:
            foreign_col = combined.columns[0] if len(combined.columns) > 0 else None
        if not inst_col:
            inst_col = combined.columns[1] if len(combined.columns) > 1 else None

        print(f"  외국인 컬럼: {foreign_col}, 기관 컬럼: {inst_col}")

        result = {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "foreign": [], "institution": []}

        for label, col in [("foreign", foreign_col), ("institution", inst_col)]:
            if col is None:
                continue
            top = combined.nlargest(20, col)
            for ticker, row in top.iterrows():
                name = stock.get_market_ticker_name(ticker)
                result[label].append({
                    "ticker": ticker,
                    "name": name,
                    "net_buy": int(row[col]),
                })

        save_json("investor_top.json", result)
        print(f"  ✓ 외국인 {len(result['foreign'])}건, 기관 {len(result['institution'])}건")

    except Exception as e:
        print(f"  ✗ 외국인/기관: {e}")
        import traceback; traceback.print_exc()


# ══════════════════════════════════════
# 2) 거래대금 상위 20
# ══════════════════════════════════════
def fetch_volume_top(date):
    """거래대금 상위 20 (코스피+코스닥)"""
    print("\n[2/4] 거래대금 상위 20")
    try:
        from pykrx import stock
        import pandas as pd

        df_kospi = stock.get_market_ohlcv(date, market="KOSPI")
        df_kosdaq = stock.get_market_ohlcv(date, market="KOSDAQ")

        if df_kospi.empty and df_kosdaq.empty:
            print("  ⚠ 데이터 없음")
            return

        combined = pd.concat([df_kospi, df_kosdaq])
        # 거래대금 컬럼
        vol_col = "거래대금" if "거래대금" in combined.columns else combined.columns[-1]
        top = combined.nlargest(20, vol_col)

        items = []
        for ticker, row in top.iterrows():
            name = stock.get_market_ticker_name(ticker)
            close = int(row["종가"]) if "종가" in row else 0
            chg = float(row["등락률"]) if "등락률" in row else 0.0
            vol = int(row[vol_col])
            items.append({
                "ticker": ticker,
                "name": name,
                "close": close,
                "change_pct": round(chg, 2),
                "trading_value": vol
            })

        result = {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "items": items}
        save_json("volume_top.json", result)
        print(f"  ✓ {len(items)}건")

    except Exception as e:
        print(f"  ✗ 거래대금: {e}")
        import traceback; traceback.print_exc()


# ══════════════════════════════════════
# 3) 업종별 등락률
# ══════════════════════════════════════
def fetch_sector_change(date):
    """KRX 업종지수 등락률"""
    print("\n[3/4] 업종별 등락률")
    try:
        from pykrx import stock

        # KOSPI 업종지수
        tickers = stock.get_index_ticker_list(date, market="KOSPI")
        items = []
        for ticker in tickers:
            name = stock.get_index_ticker_name(ticker)
            # 단일일 OHLCV
            df = stock.get_index_ohlcv(date, date, ticker)
            if df.empty:
                continue
            row = df.iloc[-1]
            close = float(row["종가"]) if "종가" in row else 0
            chg = float(row["등락률"]) if "등락률" in row else 0.0
            items.append({
                "ticker": ticker,
                "name": name,
                "close": round(close, 2),
                "change_pct": round(chg, 2)
            })
            time.sleep(0.05)

        # 종합 제외하고 정렬 (종합은 별도 표시용으로 맨 앞에)
        kospi_main = [i for i in items if i["name"] == "코스피"]
        others = sorted([i for i in items if i["name"] != "코스피"], key=lambda x: x["change_pct"], reverse=True)

        result = {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "kospi": kospi_main[0] if kospi_main else None, "sectors": others}
        save_json("sector_change.json", result)
        print(f"  ✓ {len(others)}개 업종 + 코스피 종합")

    except Exception as e:
        print(f"  ✗ 업종: {e}")
        import traceback; traceback.print_exc()


# ══════════════════════════════════════
# 4) 시가총액 상위 30
# ══════════════════════════════════════
def fetch_marketcap_top(date):
    """시가총액 상위 200"""
    print("\n[4/4] 시가총액 상위 200")
    try:
        from pykrx import stock

        df = stock.get_market_cap(date, market="ALL")
        if df.empty:
            print("  ⚠ 데이터 없음")
            return

        top = df.nlargest(200, "시가총액")
        items = []
        for ticker, row in top.iterrows():
            name = stock.get_market_ticker_name(ticker)
            mcap = int(row["시가총액"])
            close = int(row["종가"]) if "종가" in row else 0
            chg_pct = float(row["등락률"]) if "등락률" in row else 0.0
            items.append({
                "ticker": ticker,
                "name": name,
                "close": close,
                "change_pct": round(chg_pct, 2),
                "market_cap": mcap,
                "market_cap_tr": round(mcap / 1_000_000_000_000, 1)  # 조 단위
            })

        result = {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "items": items}
        save_json("marketcap_top.json", result)
        print(f"  ✓ {len(items)}건")

    except Exception as e:
        print(f"  ✗ 시총: {e}")
        import traceback; traceback.print_exc()


# ══════════════════════════════════════
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="조회일 YYYYMMDD")
    args = parser.parse_args()

    date = get_date(args.date)
    dstr = f"{date[:4]}-{date[4:6]}-{date[6:]}"

    print("=" * 50)
    print(f"KRX 투자자 지표 수집 ({dstr})")
    print("=" * 50)

    fetch_investor_top(date)
    time.sleep(1)
    fetch_volume_top(date)
    time.sleep(1)
    fetch_sector_change(date)
    time.sleep(1)
    fetch_marketcap_top(date)

    print("\n" + "=" * 50)
    print("완료!")


if __name__ == "__main__":
    main()
