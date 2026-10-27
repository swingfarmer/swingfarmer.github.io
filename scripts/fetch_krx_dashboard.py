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


def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return None


def save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    size = os.path.getsize(path)
    print(f"  💾 {filename} 저장 ({size // 1024}KB)")


def add_rank_changes(new_items, prev_items, key="ticker"):
    """전일 대비 순위 변동 계산. 각 item에 rank_change, is_new 추가."""
    if not prev_items:
        for it in new_items:
            it["rank_change"] = 0
            it["is_new"] = True
        return

    prev_rank = {}
    prev_set = set()
    for i, it in enumerate(prev_items):
        prev_rank[it[key]] = i + 1
        prev_set.add(it[key])

    new_set = set()
    for i, it in enumerate(new_items):
        new_rank = i + 1
        k = it[key]
        new_set.add(k)
        if k in prev_rank:
            it["rank_change"] = prev_rank[k] - new_rank  # 양수=순위 상승
            it["is_new"] = False
        else:
            it["rank_change"] = 0
            it["is_new"] = True

    # OUT 종목 (전일 Top N에 있었으나 오늘 없는 것)
    out_list = []
    for it in prev_items:
        if it[key] not in new_set:
            out_list.append({"ticker": it[key], "name": it.get("name", ""), "prev_rank": prev_rank[it[key]]})
    return out_list


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
    """외국인/기관 순매수 Top 50 (코스피+코스닥)"""
    print("\n[1/4] 외국인/기관 순매수 Top 50")
    try:
        from pykrx import stock
        import pandas as pd

        result = {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "foreign": [], "institution": []}

        # 투자자별로 따로 조회: "외국인", "기관합계"
        for label, investor in [("foreign", "외국인"), ("institution", "기관합계")]:
            frames = []
            for market in ["KOSPI", "KOSDAQ"]:
                try:
                    df = stock.get_market_net_purchases_of_equities(date, date, market, investor)
                    if not df.empty:
                        frames.append(df)
                except Exception as e2:
                    print(f"  ⚠ {market}/{investor}: {e2}")
                time.sleep(0.3)

            if not frames:
                print(f"  ⚠ {investor} 데이터 없음")
                continue

            combined = pd.concat(frames)

            # 순매수거래대금 컬럼 찾기
            net_col = None
            for c in combined.columns:
                if '순매수' in str(c) and '대금' in str(c):
                    net_col = c
                    break
            if not net_col:
                # fallback: 순매수 포함 컬럼
                for c in combined.columns:
                    if '순매수' in str(c):
                        net_col = c
                        break
            if not net_col:
                print(f"  ⚠ 순매수 컬럼 못 찾음: {list(combined.columns)}")
                continue

            # 종목명 컬럼 제외하고 numeric만
            top = combined.nlargest(50, net_col)
            for ticker, row in top.iterrows():
                name_val = row.get("종목명", "") or stock.get_market_ticker_name(ticker)
                result[label].append({
                    "ticker": ticker,
                    "name": str(name_val),
                    "net_buy": int(row[net_col]),
                })

        # 전일 대비 순위 변동
        prev = load_json("investor_top.json")
        for label in ["foreign", "institution"]:
            prev_items = prev.get(label, []) if prev else []
            out = add_rank_changes(result[label], prev_items, key="ticker")
            if out:
                result[label + "_out"] = out[:10]  # 이탈 상위 10

        save_json("investor_top.json", result)
        print(f"  ✓ 외국인 {len(result['foreign'])}건, 기관 {len(result['institution'])}건")

    except Exception as e:
        print(f"  ✗ 외국인/기관: {e}")
        import traceback; traceback.print_exc()


# ══════════════════════════════════════
# 2) 거래대금 상위 20
# ══════════════════════════════════════
def fetch_volume_top(date):
    """거래대금 상위 50 (코스피+코스닥)"""
    print("\n[2/4] 거래대금 상위 50")
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
        top = combined.nlargest(50, vol_col)

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

        prev = load_json("volume_top.json")
        prev_items = prev.get("items", []) if prev else []
        out = add_rank_changes(items, prev_items, key="ticker")

        result = {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "items": items}
        if out:
            result["out"] = out[:10]
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

        # 업종 전일대비 순위 변동 (등락률 순위)
        prev = load_json("sector_change.json")
        prev_sectors = prev.get("sectors", []) if prev else []
        add_rank_changes(others, prev_sectors, key="ticker")

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

        prev = load_json("marketcap_top.json")
        prev_items = prev.get("items", []) if prev else []
        out = add_rank_changes(items, prev_items, key="ticker")

        result = {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "items": items}
        if out:
            result["out"] = out[:10]
        save_json("marketcap_top.json", result)
        print(f"  ✓ {len(items)}건")

    except Exception as e:
        print(f"  ✗ 시총: {e}")
        import traceback; traceback.print_exc()


# ══════════════════════════════════════
# 히스토리 저장 (순위 추적용 경량 포맷)
# ══════════════════════════════════════
HIST_DIR = os.path.join(DATA_DIR, "hist")
MAX_HIST_DAYS = 90  # 최대 보관일


def save_daily_archive(dstr):
    """당일 전체 데이터를 hist/YYYY-MM-DD.json으로 아카이브."""
    os.makedirs(HIST_DIR, exist_ok=True)
    archive = {}
    for fname in ["investor_top.json", "volume_top.json", "sector_change.json", "marketcap_top.json"]:
        d = load_json(fname)
        if d:
            archive[fname.replace(".json", "")] = d
    if archive:
        apath = os.path.join(HIST_DIR, f"{dstr}.json")
        with open(apath, 'w', encoding='utf-8') as f:
            json.dump(archive, f, ensure_ascii=False, separators=(',', ':'))
        print(f"\n  📁 일별 아카이브: hist/{dstr}.json ({os.path.getsize(apath)//1024}KB)")


def update_rank_history(dstr):
    """순위 추적 경량 히스토리 업데이트 (그래프용)."""
    hist_file = os.path.join(DATA_DIR, "rank_history.json")
    hist = load_json("rank_history.json") or {"dates": [], "tabs": {}}

    # 중복 방지
    if dstr in hist["dates"]:
        idx = hist["dates"].index(dstr)
        hist["dates"].pop(idx)
        for tab in hist["tabs"]:
            for tk in hist["tabs"][tab]:
                ranks = hist["tabs"][tab][tk].get("r", [])
                if idx < len(ranks):
                    ranks.pop(idx)

    hist["dates"].append(dstr)

    # 탭별 순위 기록
    tab_files = {
        "investor_f": ("investor_top.json", "foreign", "net_buy"),
        "investor_i": ("investor_top.json", "institution", "net_buy"),
        "volume": ("volume_top.json", "items", "trading_value"),
        "sector": ("sector_change.json", "sectors", "change_pct"),
        "mcap": ("marketcap_top.json", "items", "market_cap_tr"),
    }

    for tab_key, (fname, list_key, val_key) in tab_files.items():
        d = load_json(fname)
        if not d:
            continue
        items = d.get(list_key, [])
        if tab_key not in hist["tabs"]:
            hist["tabs"][tab_key] = {}

        for rank, it in enumerate(items, 1):
            tk = it.get("ticker", it.get("name", ""))
            if not tk:
                continue
            if tk not in hist["tabs"][tab_key]:
                hist["tabs"][tab_key][tk] = {"name": it.get("name", ""), "r": []}
            entry = hist["tabs"][tab_key][tk]
            # 이전 날짜에 없었으면 null 채우기
            while len(entry["r"]) < len(hist["dates"]) - 1:
                entry["r"].append(None)
            entry["r"].append(rank)

        # 오늘 리스트에 없는 종목은 null
        for tk in hist["tabs"][tab_key]:
            while len(hist["tabs"][tab_key][tk]["r"]) < len(hist["dates"]):
                hist["tabs"][tab_key][tk]["r"].append(None)

    # 90일 초과 분 제거
    while len(hist["dates"]) > MAX_HIST_DAYS:
        hist["dates"].pop(0)
        for tab in hist["tabs"]:
            to_del = []
            for tk in hist["tabs"][tab]:
                hist["tabs"][tab][tk]["r"].pop(0)
                # 전부 null이면 삭제
                if all(v is None for v in hist["tabs"][tab][tk]["r"]):
                    to_del.append(tk)
            for tk in to_del:
                del hist["tabs"][tab][tk]

    # 날짜 목록 별도 저장 (프론트 일자 검색용)
    dates_file = os.path.join(DATA_DIR, "available_dates.json")
    avail = []
    for fn in sorted(os.listdir(HIST_DIR)):
        if fn.endswith(".json") and fn != "available_dates.json":
            avail.append(fn.replace(".json", ""))
    with open(dates_file, 'w') as f:
        json.dump(avail, f, separators=(',', ':'))

    save_json("rank_history.json", hist)
    print(f"  📈 순위 히스토리: {len(hist['dates'])}일, {sum(len(v) for v in hist['tabs'].values())}종목")


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

    # 히스토리 저장
    save_daily_archive(dstr)
    update_rank_history(dstr)

    print("\n" + "=" * 50)
    print("완료!")


if __name__ == "__main__":
    main()
