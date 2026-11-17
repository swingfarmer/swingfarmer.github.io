"""
이동평균선 체크 — 주봉 10주선 / 월봉 20월선
=============================================
매주 금요일 장마감 후 발송 (봇1 기술알림)

사용법:
  python3 fetch_ma_check.py --weekly          # 주봉 10주선 체크
  python3 fetch_ma_check.py --monthly         # 월봉 20월선 중간점검
  python3 fetch_ma_check.py --monthly-final   # 월봉 20월선 확정 (월말)

대상: 코스피·코스닥 지수 + 시총 100위 전종목
"""

import os, sys, json, argparse, time
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import yfinance as yf
from telegram_helper import send_dm

# ── 종목 로드 ──────────────────────────────────────────

def load_csv_tickers(filepath):
    """CSV → {ticker: name} dict"""
    result = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 2:
                result[parts[0].strip()] = parts[1].strip()
    return result

def get_top100_tickers():
    """시총 100위 종목 + 시장 구분 반환"""
    # 1) marketcap_top.json에서 상위 100개
    mcap_path = os.path.join(SCRIPT_DIR, '..', 'data', 'krx', 'marketcap_top.json')
    with open(mcap_path, 'r', encoding='utf-8') as f:
        mcap = json.load(f)
    top100 = mcap['items'][:100]

    # 2) KOSPI/KOSDAQ CSV로 시장 구분
    kospi = load_csv_tickers(os.path.join(SCRIPT_DIR, 'kospi200_list.csv'))
    kosdaq = load_csv_tickers(os.path.join(SCRIPT_DIR, 'kosdaq_list.csv'))

    stocks = []
    for item in top100:
        ticker = item['ticker']
        name = item['name']
        if ticker in kospi:
            suffix = '.KS'
        elif ticker in kosdaq:
            suffix = '.KQ'
        else:
            suffix = '.KS'  # 기본값 KOSPI
        stocks.append({
            'ticker': ticker,
            'yf_sym': f'{ticker}{suffix}',
            'name': name,
        })
    return stocks

# ── yfinance 데이터 수집 ──────────────────────────────

def fetch_weekly_data(symbols, period='6mo'):
    """주봉 데이터 — 배치 다운로드 (청크 단위)"""
    all_data = {}
    chunk_size = 30
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        try:
            df = yf.download(chunk, period=period, interval='1wk',
                             auto_adjust=True, progress=False, threads=True)
            if df.empty:
                continue
            # 단일 종목이면 컬럼 구조가 다름
            if len(chunk) == 1:
                sym = chunk[0]
                if 'Close' in df.columns:
                    all_data[sym] = df['Close'].dropna().tolist()
            else:
                if 'Close' in df.columns:
                    close_df = df['Close']
                    for sym in chunk:
                        if sym in close_df.columns:
                            vals = close_df[sym].dropna().tolist()
                            if vals:
                                all_data[sym] = vals
        except Exception as e:
            print(f'  ⚠ 주봉 청크 {i}~{i+chunk_size} 실패: {e}')
        time.sleep(1)
    return all_data

def fetch_monthly_data(symbols, period='3y'):
    """월봉 데이터 — 배치 다운로드 (청크 단위)"""
    all_data = {}
    chunk_size = 30
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        try:
            df = yf.download(chunk, period=period, interval='1mo',
                             auto_adjust=True, progress=False, threads=True)
            if df.empty:
                continue
            if len(chunk) == 1:
                sym = chunk[0]
                if 'Close' in df.columns:
                    all_data[sym] = df['Close'].dropna().tolist()
            else:
                if 'Close' in df.columns:
                    close_df = df['Close']
                    for sym in chunk:
                        if sym in close_df.columns:
                            vals = close_df[sym].dropna().tolist()
                            if vals:
                                all_data[sym] = vals
        except Exception as e:
            print(f'  ⚠ 월봉 청크 {i}~{i+chunk_size} 실패: {e}')
        time.sleep(1)
    return all_data

# ── MA 계산 ────────────────────────────────────────────

def calc_ma_ratio(prices, ma_len):
    """종가 / MA = 비율(%). 데이터 부족 시 None"""
    if len(prices) < ma_len:
        return None
    ma = sum(prices[-ma_len:]) / ma_len
    if ma == 0:
        return None
    current = prices[-1]
    return round(current / ma * 100, 2)

# ── 3분류 로직 ─────────────────────────────────────────

def classify_3groups(stock_results, idx_ratio_map, ma_label):
    """
    3분류: 지수보다 강한 / 중간 / 지수보다 약한
    stock_results: [(name, ratio, market)] — market='KS' or 'KQ'
    idx_ratio_map: {'KS': 코스피비율, 'KQ': 코스닥비율}
    
    코스피 110%일 때: 110%+강 / 100~110%중간 / 100%-약
    코스피 90%일 때:  100%+강 / 90~100%중간 / 90%-약
    → 기준선: max(100, 지수)와 min(100, 지수)
    """
    strong = []   # 지수보다 강한
    middle = []   # 중간 (이평선과 지수 사이)
    weak = []     # 지수보다 약한
    na_list = []

    for name, ratio, market in stock_results:
        if ratio is None:
            na_list.append(name)
            continue
        
        idx_r = idx_ratio_map.get(market)
        if idx_r is None:
            idx_r = 100.0  # fallback

        hi = max(100.0, idx_r)
        lo = min(100.0, idx_r)

        if ratio >= hi:
            strong.append((name, ratio))
        elif ratio >= lo:
            middle.append((name, ratio))
        else:
            weak.append((name, ratio))

    strong.sort(key=lambda x: -x[1])
    middle.sort(key=lambda x: -x[1])
    weak.sort(key=lambda x: x[1])

    return strong, middle, weak, na_list

def _make_group_labels(idx_ratio_map, ma_label):
    """지수 상태에 따라 그룹 라벨 생성"""
    # 대표값으로 코스피 기준 라벨 (코스닥도 같은 구조)
    ks = idx_ratio_map.get('KS', 100.0)
    
    if ks >= 100:
        return (
            f'🔺 지수보다 강한 ({ma_label}↑ 지수↑)',
            f'➖ {ma_label}↑ 지수↓',
            f'🔻 {ma_label} 이하',
        )
    else:
        return (
            f'🔺 {ma_label} 이상',
            f'➖ {ma_label}↓ 지수↑',
            f'🔻 지수보다 약한 ({ma_label}↓ 지수↓)',
        )

# ── 메시지 포맷 ────────────────────────────────────────

def format_weekly_message(index_results, stock_results, date_str, idx_ratio_map):
    """주봉 10주선 체크 메시지 (3분류)"""
    header = f'📊 <b>주봉 10주선 체크</b> ({date_str} 금)\n'

    # 지수
    idx_lines = '\n▶ <b>지수</b>\n'
    for name, ratio in index_results:
        arrow = '🔺' if ratio >= 100 else '🔻'
        idx_lines += f'  {arrow} {name} <b>{ratio:.2f}%</b>\n'

    # 3분류
    strong, middle, weak, na_list = classify_3groups(stock_results, idx_ratio_map, '10주선')
    lbl_s, lbl_m, lbl_w = _make_group_labels(idx_ratio_map, '10주선')

    msgs = []
    msg1 = header + idx_lines
    msg1 += f'\n▶ <b>{lbl_s}</b> ({len(strong)}종목)\n'
    msg1 += _format_stock_lines(strong)
    if na_list:
        msg1 += f'\n⚠ 데이터 부족: {", ".join(na_list[:10])}'
    msgs.append(msg1)

    msg2 = f'▶ <b>{lbl_m}</b> ({len(middle)}종목)\n'
    msg2 += _format_stock_lines(middle)
    msgs.append(msg2)

    msg3 = f'▶ <b>{lbl_w}</b> ({len(weak)}종목)\n'
    msg3 += _format_stock_lines(weak)
    msgs.append(msg3)

    return _split_messages(msgs)

def format_monthly_message(index_results, stock_results, date_str, idx_ratio_map, is_final=False):
    """월봉 20월선 체크 메시지 (3분류)"""
    if is_final:
        header = f'🔒 <b>월봉 20월선 확정</b> ({date_str})\n'
    else:
        header = f'📋 <b>월봉 20월선 중간점검</b> ({date_str} 금)\n'

    # 지수
    idx_lines = '\n▶ <b>지수</b>\n'
    for name, ratio in index_results:
        arrow = '🔺' if ratio >= 100 else '🔻'
        idx_lines += f'  {arrow} {name} <b>{ratio:.2f}%</b>\n'

    # 3분류
    strong, middle, weak, na_list = classify_3groups(stock_results, idx_ratio_map, '20월선')
    lbl_s, lbl_m, lbl_w = _make_group_labels(idx_ratio_map, '20월선')

    msgs = []
    msg1 = header + idx_lines
    msg1 += f'\n▶ <b>{lbl_s}</b> ({len(strong)}종목)\n'
    msg1 += _format_stock_lines(strong)
    if na_list:
        msg1 += f'\n⚠ 데이터 부족: {", ".join(na_list[:10])}'
    msgs.append(msg1)

    msg2 = f'▶ <b>{lbl_m}</b> ({len(middle)}종목)\n'
    msg2 += _format_stock_lines(middle)
    msgs.append(msg2)

    msg3 = f'▶ <b>{lbl_w}</b> ({len(weak)}종목)\n'
    msg3 += _format_stock_lines(weak)
    msgs.append(msg3)

    return _split_messages(msgs)

def _format_stock_lines(items):
    """종목 리스트를 3열 포맷으로"""
    lines = ''
    for i in range(0, len(items), 3):
        row = items[i:i+3]
        parts = [f'{name} {ratio:.1f}%' for name, ratio in row]
        lines += '  ' + ' | '.join(parts) + '\n'
    return lines

def _split_messages(msgs):
    """4096자 제한으로 메시지 분할"""
    result = []
    for msg in msgs:
        while len(msg) > 4000:
            cut = msg[:4000].rfind('\n')
            if cut < 100:
                cut = 4000
            result.append(msg[:cut])
            msg = msg[cut:]
        if msg.strip():
            result.append(msg)
    return result

# ── 메인 ────────────────────────────────────────────────

def run_weekly():
    """주봉 10주선 체크"""
    today = datetime.now().strftime('%Y.%m.%d')
    print(f'📊 주봉 10주선 체크 시작 ({today})')

    stocks = get_top100_tickers()
    yf_syms = [s['yf_sym'] for s in stocks]

    # 지수
    idx_syms = ['^KS11', '^KQ11']
    all_syms = idx_syms + yf_syms

    print(f'  종목 {len(yf_syms)}개 + 지수 2개 다운로드 중...')
    data = fetch_weekly_data(all_syms)

    # 지수 결과 + idx_ratio_map
    index_results = []
    idx_ratio_map = {}  # {'KS': 코스피비율, 'KQ': 코스닥비율}
    for sym, name, key in [('^KS11', '코스피', 'KS'), ('^KQ11', '코스닥', 'KQ')]:
        if sym in data:
            ratio = calc_ma_ratio(data[sym], 10)
            if ratio:
                index_results.append((name, ratio))
                idx_ratio_map[key] = ratio
                print(f'  {name}: {ratio:.2f}%')

    # 종목 결과 — (name, ratio, market)
    stock_results = []
    ok_count = 0
    for s in stocks:
        sym = s['yf_sym']
        name = s['name']
        market = 'KQ' if sym.endswith('.KQ') else 'KS'
        if sym in data:
            ratio = calc_ma_ratio(data[sym], 10)
            stock_results.append((name, ratio, market))
            if ratio:
                ok_count += 1
        else:
            stock_results.append((name, None, market))

    print(f'  계산 완료: {ok_count}/{len(stocks)}개 성공')

    # 발송
    msgs = format_weekly_message(index_results, stock_results, today, idx_ratio_map)
    for i, msg in enumerate(msgs):
        send_dm(msg)
        print(f'  [봇1] 주봉 메시지 {i+1}/{len(msgs)} 발송')
        if i < len(msgs) - 1:
            time.sleep(1)

def run_monthly(is_final=False):
    """월봉 20월선 체크"""
    today = datetime.now().strftime('%Y.%m.%d')
    label = '확정' if is_final else '중간점검'
    print(f'📋 월봉 20월선 {label} 시작 ({today})')

    stocks = get_top100_tickers()
    yf_syms = [s['yf_sym'] for s in stocks]

    idx_syms = ['^KS11', '^KQ11']
    all_syms = idx_syms + yf_syms

    print(f'  종목 {len(yf_syms)}개 + 지수 2개 다운로드 중...')
    data = fetch_monthly_data(all_syms)

    # 지수 결과 + idx_ratio_map
    index_results = []
    idx_ratio_map = {}
    for sym, name, key in [('^KS11', '코스피', 'KS'), ('^KQ11', '코스닥', 'KQ')]:
        if sym in data:
            ratio = calc_ma_ratio(data[sym], 20)
            if ratio:
                index_results.append((name, ratio))
                idx_ratio_map[key] = ratio
                print(f'  {name}: {ratio:.2f}%')

    # 종목 결과 — (name, ratio, market)
    stock_results = []
    ok_count = 0
    for s in stocks:
        sym = s['yf_sym']
        name = s['name']
        market = 'KQ' if sym.endswith('.KQ') else 'KS'
        if sym in data:
            ratio = calc_ma_ratio(data[sym], 20)
            stock_results.append((name, ratio, market))
            if ratio:
                ok_count += 1
        else:
            stock_results.append((name, None, market))

    print(f'  계산 완료: {ok_count}/{len(stocks)}개 성공')

    # 발송
    msgs = format_monthly_message(index_results, stock_results, today, idx_ratio_map, is_final)
    for i, msg in enumerate(msgs):
        send_dm(msg)
        print(f'  [봇1] 월봉 메시지 {i+1}/{len(msgs)} 발송')
        if i < len(msgs) - 1:
            time.sleep(1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='이동평균선 체크')
    parser.add_argument('--weekly', action='store_true', help='주봉 10주선')
    parser.add_argument('--monthly', action='store_true', help='월봉 20월선 중간점검')
    parser.add_argument('--monthly-final', action='store_true', help='월봉 20월선 확정')

    args = parser.parse_args()

    if not (args.weekly or args.monthly or args.monthly_final):
        print('사용법: --weekly / --monthly / --monthly-final')
        sys.exit(1)

    if args.weekly:
        run_weekly()
    if args.monthly:
        run_monthly(is_final=False)
    if args.monthly_final:
        run_monthly(is_final=True)
