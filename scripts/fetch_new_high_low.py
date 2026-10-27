#!/usr/bin/env python3
"""
52주 신고가/신저가 비율 (Breadth Indicator)
============================================
KRX 전종목 대상, pykrx로 수집.

동작:
  1) 260거래일 윈도우(VM 로컬)에서 종목별 52주 고가/저가 산출
  2) 당일 종가 >= 52주 고가 → 신고가, 종가 <= 52주 저가 → 신저가
  3) data/krx/new_high_low.json (당일 요약+종목리스트)
  4) data/krx/new_high_low_history.json (일별 추이, 무제한 누적)

사용법:
  python3 scripts/fetch_new_high_low.py                    # 오늘
  python3 scripts/fetch_new_high_low.py --date 20261027    # 특정일
  python3 scripts/fetch_new_high_low.py --build-window     # 초기 260일 윈도우 구축 (1회, ~10분)

크론: 평일 20:55 (fetch_krx_dashboard 뒤)
55 20 * * 1-5 . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/fetch_new_high_low.py >> ~/logs/fetch_new_high_low.log 2>&1
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

# VM 로컬 윈도우 파일 (GitHub 미포함, ~10MB)
WINDOW_FILE = os.path.expanduser("~/new_high_low_window.json")
WINDOW_DAYS = 260  # 52주 ≈ 260거래일


def save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    size = os.path.getsize(path)
    print(f"  💾 {filename} 저장 ({size // 1024}KB)")


def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return None


def load_window():
    if os.path.exists(WINDOW_FILE):
        with open(WINDOW_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {"dates": [], "kospi": {}, "kosdaq": {}}


def save_window(window):
    with open(WINDOW_FILE, 'w', encoding='utf-8') as f:
        json.dump(window, f, ensure_ascii=False, separators=(',', ':'))
    size = os.path.getsize(WINDOW_FILE)
    print(f"  💾 윈도우 저장 ({size // (1024*1024)}MB)")


def get_date(args_date=None):
    if args_date:
        return args_date
    dt = datetime.now()
    wd = dt.weekday()
    if wd == 5:
        dt -= timedelta(days=1)
    elif wd == 6:
        dt -= timedelta(days=2)
    return dt.strftime("%Y%m%d")


def fmt_date(d):
    """YYYYMMDD → YYYY-MM-DD"""
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def fetch_ohlcv_all(date, market):
    """해당 날짜의 시장 전종목 OHLCV 수집. {ticker: [high, low, close], ...} 반환."""
    from pykrx import stock

    result = {}
    try:
        df = stock.get_market_ohlcv(date, market=market)
        if df is None or df.empty:
            return result
        for ticker, row in df.iterrows():
            h = int(row.get("고가", 0))
            l = int(row.get("저가", 0))
            c = int(row.get("종가", 0))
            v = int(row.get("거래량", 0))
            # 거래정지/관리종목 제외 (종가=0 또는 거래량=0)
            if c > 0 and v > 0:
                result[ticker] = [h, l, c]
    except Exception as e:
        print(f"  ⚠ {market} {date} OHLCV 수집 실패: {e}")
    return result


def get_trading_dates(end_date, num_days):
    """end_date 이전 num_days 거래일 목록 반환 (pykrx 기반)."""
    from pykrx import stock

    # 넉넉하게 1.6배 역산
    start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=int(num_days * 1.6))
    start = start_dt.strftime("%Y%m%d")

    # 코스피 일봉 날짜로 거래일 추출
    try:
        df = stock.get_index_ohlcv(start, end_date, "1001")  # 1001=코스피
        if df is not None and not df.empty:
            dates = [d.strftime("%Y%m%d") for d in df.index]
            return dates[-num_days:]  # 최근 num_days개
    except Exception as e:
        print(f"  ⚠ 거래일 조회 실패: {e}")

    return []


def build_window(end_date):
    """260거래일 윈도우 초기 구축 (1회성, ~10분)."""
    print(f"\n🔨 윈도우 구축 시작 (기준일: {fmt_date(end_date)}, {WINDOW_DAYS}거래일)")

    trading_dates = get_trading_dates(end_date, WINDOW_DAYS)
    if not trading_dates:
        print("  ❌ 거래일 조회 실패")
        return None

    print(f"  📅 {fmt_date(trading_dates[0])} ~ {fmt_date(trading_dates[-1])} ({len(trading_dates)}일)")

    window = {"dates": [], "kospi": {}, "kosdaq": {}}

    for i, date in enumerate(trading_dates):
        print(f"  [{i+1}/{len(trading_dates)}] {fmt_date(date)} ...", end="", flush=True)

        for market in ["KOSPI", "KOSDAQ"]:
            data = fetch_ohlcv_all(date, market)
            mkey = market.lower()

            for ticker, hlc in data.items():
                if ticker not in window[mkey]:
                    # 이전 날짜에 데이터 없으면 None으로 채움
                    window[mkey][ticker] = {"h": [None]*i, "l": [None]*i, "c": [None]*i}
                window[mkey][ticker]["h"].append(hlc[0])
                window[mkey][ticker]["l"].append(hlc[1])
                window[mkey][ticker]["c"].append(hlc[2])

            time.sleep(0.5)

        # 이 날짜에 데이터 없는 종목은 None 추가
        for mkey in ["kospi", "kosdaq"]:
            for ticker in window[mkey]:
                if len(window[mkey][ticker]["h"]) <= i:
                    window[mkey][ticker]["h"].append(None)
                    window[mkey][ticker]["l"].append(None)
                    window[mkey][ticker]["c"].append(None)

        window["dates"].append(date)
        print(f" KOSPI {sum(1 for t in window['kospi'] if window['kospi'][t]['c'][-1] is not None)}, KOSDAQ {sum(1 for t in window['kosdaq'] if window['kosdaq'][t]['c'][-1] is not None)}")

        # 10일마다 중간저장
        if (i + 1) % 10 == 0:
            save_window(window)

    save_window(window)
    print(f"\n✅ 윈도우 구축 완료: KOSPI {len(window['kospi'])}종목, KOSDAQ {len(window['kosdaq'])}종목")
    return window


def update_window(window, date):
    """윈도우에 하루치 추가, 260일 초과분 제거."""
    if date in window["dates"]:
        print(f"  ℹ {fmt_date(date)} 이미 윈도우에 포함")
        return window

    print(f"\n📊 {fmt_date(date)} 데이터 수집")

    for market in ["KOSPI", "KOSDAQ"]:
        mkey = market.lower()
        data = fetch_ohlcv_all(date, market)
        print(f"  {market}: {len(data)}종목")

        # 기존 종목 업데이트 + 신규 종목 추가
        existing = set(window[mkey].keys())
        fetched = set(data.keys())

        for ticker in fetched:
            hlc = data[ticker]
            if ticker not in window[mkey]:
                n = len(window["dates"])
                window[mkey][ticker] = {"h": [None]*n, "l": [None]*n, "c": [None]*n}
            window[mkey][ticker]["h"].append(hlc[0])
            window[mkey][ticker]["l"].append(hlc[1])
            window[mkey][ticker]["c"].append(hlc[2])

        # 이 날짜에 데이터 없는 기존 종목
        for ticker in existing - fetched:
            window[mkey][ticker]["h"].append(None)
            window[mkey][ticker]["l"].append(None)
            window[mkey][ticker]["c"].append(None)

        time.sleep(0.5)

    window["dates"].append(date)

    # 260일 초과분 제거
    while len(window["dates"]) > WINDOW_DAYS:
        window["dates"].pop(0)
        for mkey in ["kospi", "kosdaq"]:
            for ticker in list(window[mkey].keys()):
                window[mkey][ticker]["h"].pop(0)
                window[mkey][ticker]["l"].pop(0)
                window[mkey][ticker]["c"].pop(0)
                # 전부 None인 종목 정리
                if all(v is None for v in window[mkey][ticker]["c"]):
                    del window[mkey][ticker]

    save_window(window)
    return window


def compute_breadth(window, date):
    """윈도우에서 52주 신고가/신저가 계산."""
    from pykrx import stock

    if date not in window["dates"]:
        print(f"  ❌ {fmt_date(date)} 윈도우에 없음")
        return None

    idx = window["dates"].index(date)
    date_iso = fmt_date(date)

    result = {
        "date": date_iso,
        "kospi": {"total": 0, "new_high": 0, "new_low": 0, "high_pct": 0, "low_pct": 0},
        "kosdaq": {"total": 0, "new_high": 0, "new_low": 0, "high_pct": 0, "low_pct": 0},
        "all": {"total": 0, "new_high": 0, "new_low": 0, "high_pct": 0, "low_pct": 0},
        "new_highs": [],
        "new_lows": []
    }

    # 유효 윈도우 길이 (최소 60거래일 이상이어야 의미 있음)
    win_len = idx + 1  # 첫날~현재
    if win_len < 60:
        print(f"  ⚠ 윈도우 {win_len}일 — 최소 60일 필요 (데이터 계속 누적 중)")

    for mkey in ["kospi", "kosdaq"]:
        stocks = window[mkey]
        for ticker, hlc in stocks.items():
            today_c = hlc["c"][idx] if idx < len(hlc["c"]) else None
            if today_c is None or today_c == 0:
                continue

            result[mkey]["total"] += 1

            # 52주(또는 보유 윈도우) 내 최고가/최저가 (당일 제외)
            past_highs = [v for v in hlc["h"][:idx] if v is not None and v > 0]
            past_lows = [v for v in hlc["l"][:idx] if v is not None and v > 0]

            if not past_highs or not past_lows:
                continue

            high_52w = max(past_highs)
            low_52w = min(past_lows)
            today_h = hlc["h"][idx] if idx < len(hlc["h"]) else None
            today_l = hlc["l"][idx] if idx < len(hlc["l"]) else None

            if today_h is None or today_l is None:
                continue

            # 신고가: 당일 고가 >= 52주 고가
            if today_h >= high_52w:
                result[mkey]["new_high"] += 1
                try:
                    name = stock.get_market_ticker_name(ticker)
                except:
                    name = ticker
                result["new_highs"].append({
                    "ticker": ticker, "name": name,
                    "market": mkey.upper(), "close": today_c,
                    "high_52w": high_52w, "today_high": today_h
                })

            # 신저가: 당일 저가 <= 52주 저가
            if today_l <= low_52w:
                result[mkey]["new_low"] += 1
                try:
                    name = stock.get_market_ticker_name(ticker)
                except:
                    name = ticker
                result["new_lows"].append({
                    "ticker": ticker, "name": name,
                    "market": mkey.upper(), "close": today_c,
                    "low_52w": low_52w, "today_low": today_l
                })

    # 비율 계산
    for mkey in ["kospi", "kosdaq"]:
        t = result[mkey]["total"]
        if t > 0:
            result[mkey]["high_pct"] = round(result[mkey]["new_high"] / t * 100, 2)
            result[mkey]["low_pct"] = round(result[mkey]["new_low"] / t * 100, 2)

    # ALL
    result["all"]["total"] = result["kospi"]["total"] + result["kosdaq"]["total"]
    result["all"]["new_high"] = result["kospi"]["new_high"] + result["kosdaq"]["new_high"]
    result["all"]["new_low"] = result["kospi"]["new_low"] + result["kosdaq"]["new_low"]
    if result["all"]["total"] > 0:
        result["all"]["high_pct"] = round(result["all"]["new_high"] / result["all"]["total"] * 100, 2)
        result["all"]["low_pct"] = round(result["all"]["new_low"] / result["all"]["total"] * 100, 2)

    # 신고가: 종가 높은 순, 신저가: 종가 낮은 순
    result["new_highs"].sort(key=lambda x: x["close"], reverse=True)
    result["new_lows"].sort(key=lambda x: x["close"])

    # 윈도우 길이 정보
    result["window_days"] = win_len

    return result


def update_history(result):
    """일별 추이 히스토리 누적."""
    hist_file = "new_high_low_history.json"
    history = load_json(hist_file) or []

    entry = {
        "date": result["date"],
        "window": result.get("window_days", 0),
        "kospi_total": result["kospi"]["total"],
        "kospi_high": result["kospi"]["new_high"],
        "kospi_low": result["kospi"]["new_low"],
        "kospi_high_pct": result["kospi"]["high_pct"],
        "kospi_low_pct": result["kospi"]["low_pct"],
        "kosdaq_total": result["kosdaq"]["total"],
        "kosdaq_high": result["kosdaq"]["new_high"],
        "kosdaq_low": result["kosdaq"]["new_low"],
        "kosdaq_high_pct": result["kosdaq"]["high_pct"],
        "kosdaq_low_pct": result["kosdaq"]["low_pct"],
        "all_high": result["all"]["new_high"],
        "all_low": result["all"]["new_low"],
        "all_high_pct": result["all"]["high_pct"],
        "all_low_pct": result["all"]["low_pct"],
    }

    # 코스피 지수 추가 (가능하면)
    try:
        from pykrx import stock
        date_str = result["date"].replace("-", "")
        df = stock.get_index_ohlcv(date_str, date_str, "1001")
        if df is not None and not df.empty:
            entry["kospi_index"] = float(df.iloc[-1]["종가"])
    except:
        pass

    # 같은 날짜 있으면 덮어쓰기
    history = [h for h in history if h["date"] != result["date"]]
    history.append(entry)
    history.sort(key=lambda x: x["date"])

    save_json(hist_file, history)
    return history


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="날짜 YYYYMMDD")
    parser.add_argument("--build-window", action="store_true", help="260일 윈도우 초기 구축")
    args = parser.parse_args()

    date = get_date(args.date)
    print(f"📈 52주 신고가/신저가 비율 — {fmt_date(date)}")

    if args.build_window:
        window = build_window(date)
        if not window:
            sys.exit(1)
    else:
        window = load_window()
        if not window["dates"]:
            print("  ❌ 윈도우 없음. --build-window 먼저 실행하세요.")
            sys.exit(1)

    # 윈도우 업데이트
    if date not in window["dates"]:
        window = update_window(window, date)

    # 계산
    result = compute_breadth(window, date)
    if not result:
        sys.exit(1)

    # 저장
    save_json("new_high_low.json", result)

    # 히스토리 누적
    update_history(result)

    # 요약 출력
    print(f"\n═══ 52주 신고가/신저가 ═══")
    print(f"  KOSPI  : 전체 {result['kospi']['total']} │ 신고가 {result['kospi']['new_high']}({result['kospi']['high_pct']}%) │ 신저가 {result['kospi']['new_low']}({result['kospi']['low_pct']}%)")
    print(f"  KOSDAQ : 전체 {result['kosdaq']['total']} │ 신고가 {result['kosdaq']['new_high']}({result['kosdaq']['high_pct']}%) │ 신저가 {result['kosdaq']['new_low']}({result['kosdaq']['low_pct']}%)")
    print(f"  합산   : 전체 {result['all']['total']} │ 신고가 {result['all']['new_high']}({result['all']['high_pct']}%) │ 신저가 {result['all']['new_low']}({result['all']['low_pct']}%)")
    print(f"  윈도우 : {result['window_days']}거래일")
    print(f"\n✅ 완료")


if __name__ == "__main__":
    main()
