"""
KOSPI 200 스크리너 — 기술적 시그널 + 수급
==========================================
KIS Open API로 일봉 + 투자자 매매 수집 → 시그널 판별 → 일자별 JSON 저장.

시그널:
  1) 50일선(10주선) 종가 돌파
  2) 볼밴 상단 종가 돌파
  3) 볼밴 상단 장중 돌파 (종가 미돌파)
  4) 3일 연속 양봉 + 합계 10%↑
  5) 외인 순매수 Top 15 / 순매도 Top 15
  6) 기관 순매수 Top 15 / 순매도 Top 15
  7) 외인 연속 순매수
  8) 기관 연속 순매수

사용법:
  python scripts/fetch_screener.py

환경변수:
  KIS_APP_KEY, KIS_APP_SECRET (필수)

출력:
  data/kr/screener/YYYY-MM-DD.json   (일별)
  data/kr/screener/index.json        (날짜 목록)
  data/kr/screener/investor_hist.json (수급 누적 — 60일 보관)
"""

import os, sys, json, time, math, glob
import urllib.request
from datetime import date, datetime, timedelta

# ── 설정 ──
KIS_APP_KEY    = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE       = os.environ.get('KIS_BASE_URL',
                                'https://openapi.koreainvestment.com:9443')

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR    = os.path.dirname(SCRIPT_DIR)
STOCK_LIST  = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
OUT_DIR     = os.path.join(ROOT_DIR, 'data', 'kr', 'screener')
HIST_FILE   = os.path.join(OUT_DIR, 'investor_hist.json')
INDEX_FILE  = os.path.join(OUT_DIR, 'index.json')

CALL_DELAY  = 0.08          # ~12 req/s (안전 마진)
OHLCV_DAYS  = 150           # 캘린더일 기준 (거래일 ~100)
HIST_KEEP   = 60            # 수급 이력 보관 거래일
FILE_KEEP   = 3650          # 스크리너 파일 보관 일수 (10년)


# ── 유틸 ──
def load_stock_list():
    stocks = []
    with open(STOCK_LIST, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                stocks.append({
                    'code': parts[0].strip(),
                    'name': parts[1].strip(),
                    'sector': parts[2].strip()
                })
    return stocks


def safe_int(v):
    try:
        return int(v)
    except:
        return 0


def safe_float(v):
    try:
        return float(v)
    except:
        return 0.0


# ── KIS API ──
def kis_request(url, token, tr_id):
    """KIS API GET 요청."""
    req = urllib.request.Request(url, headers={
        'Content-Type':  'application/json; charset=UTF-8',
        'authorization': f'Bearer {token}',
        'appkey':        KIS_APP_KEY,
        'appsecret':     KIS_APP_SECRET,
        'tr_id':         tr_id,
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('rt_cd') != '0':
            return None
        return data
    except Exception as e:
        return None


def get_access_token():
    url = f'{KIS_BASE}/oauth2/tokenP'
    body = json.dumps({
        'grant_type': 'client_credentials',
        'appkey': KIS_APP_KEY,
        'appsecret': KIS_APP_SECRET,
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json; charset=UTF-8',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        token = data.get('access_token', '')
        if not token:
            print(f'❌ 토큰 발급 실패: {data}')
            sys.exit(1)
        print('🔑 토큰 발급 완료')
        return token
    except Exception as e:
        print(f'❌ 토큰 발급 실패: {e}')
        sys.exit(1)


def fetch_ohlcv(token, code, end_date):
    """종목별 일봉 OHLCV (최근 ~100거래일)."""
    start = (datetime.strptime(end_date, '%Y%m%d') -
             timedelta(days=OHLCV_DAYS)).strftime('%Y%m%d')
    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/'
           f'inquire-daily-itemchartprice'
           f'?FID_COND_MRKT_DIV_CODE=J'
           f'&FID_INPUT_ISCD={code}'
           f'&FID_INPUT_DATE_1={start}'
           f'&FID_INPUT_DATE_2={end_date}'
           f'&FID_PERIOD_DIV_CODE=D'
           f'&FID_ORG_ADJ_PRC=0')
    data = kis_request(url, token, 'FHKST03010100')
    if not data:
        return []
    rows = data.get('output2', [])
    result = []
    for r in rows:
        d = r.get('stck_bsop_date', '')
        if not d:
            continue
        result.append({
            'date':   d,
            'open':   safe_int(r.get('stck_oprc')),
            'high':   safe_int(r.get('stck_hgpr')),
            'low':    safe_int(r.get('stck_lwpr')),
            'close':  safe_int(r.get('stck_clpr')),
            'volume': safe_int(r.get('acml_vol')),
        })
    # 날짜 오름차순 정렬
    result.sort(key=lambda x: x['date'])
    return result


def fetch_investor(token, code):
    """종목별 투자자 매매 동향 (최근 거래일 기준)."""
    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/'
           f'inquire-investor'
           f'?FID_COND_MRKT_DIV_CODE=J'
           f'&FID_INPUT_ISCD={code}')
    data = kis_request(url, token, 'FHKST01010900')
    if not data:
        return None
    output = data.get('output', [])
    result = {}
    for item in output:
        name = item.get('invr_nm', '').strip()
        net = safe_int(item.get('ntby_qty'))          # 순매수 수량
        net_amt = safe_int(item.get('ntby_tr_pbmn'))  # 순매수 금액
        if '외국인' in name:
            result['foreign_qty'] = net
            result['foreign_amt'] = net_amt
        elif '기관' in name:
            result['institution_qty'] = net
            result['institution_amt'] = net_amt
    return result if result else None


# ── 기술적 지표 계산 ──
def calc_ma(closes, n):
    """단순 이동평균."""
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def calc_bollinger_upper(closes, n=20, k=2):
    """볼린저밴드 상단."""
    if len(closes) < n:
        return None
    window = closes[-n:]
    ma = sum(window) / n
    variance = sum((x - ma) ** 2 for x in window) / n
    std = math.sqrt(variance)
    return ma + k * std


def detect_signals(ohlcv):
    """OHLCV 배열에서 모든 기술적 시그널 판별."""
    signals = {}
    if len(ohlcv) < 51:  # MA50 최소 요구
        return signals

    closes = [d['close'] for d in ohlcv]
    latest = ohlcv[-1]

    # ① 50일선(10주선) 종가 돌파
    ma50_now = calc_ma(closes, 50)
    ma50_prev = calc_ma(closes[:-1], 50) if len(closes) > 50 else None
    if ma50_now and ma50_prev:
        prev_close = ohlcv[-2]['close']
        if prev_close < ma50_prev and latest['close'] >= ma50_now:
            signals['ma50_breakout'] = {
                'price': latest['close'],
                'ma50': round(ma50_now),
            }

    # ② ③ 볼밴 상단 돌파
    bb_upper = calc_bollinger_upper(closes)
    if bb_upper:
        bb_upper = round(bb_upper)
        if latest['close'] > bb_upper:
            signals['bb_upper_close'] = {
                'price': latest['close'],
                'bb_upper': bb_upper,
            }
        elif latest['high'] > bb_upper:
            signals['bb_upper_intra'] = {
                'price': latest['close'],
                'high': latest['high'],
                'bb_upper': bb_upper,
            }

    # ④ 3일 연속 양봉 + 합계 10%↑
    if len(ohlcv) >= 4:
        last3 = ohlcv[-3:]
        all_bullish = all(d['close'] > d['open'] for d in last3)
        if all_bullish:
            base_close = ohlcv[-4]['close']
            if base_close > 0:
                gain = (latest['close'] - base_close) / base_close * 100
                if gain >= 10:
                    signals['rally_3d_10pct'] = {
                        'price': latest['close'],
                        'gain_3d': round(gain, 1),
                    }

    return signals


# ── 수급 이력 관리 ──
def load_investor_history():
    if os.path.exists(HIST_FILE):
        with open(HIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_investor_history(hist):
    with open(HIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False)


def trim_history(hist, keep=HIST_KEEP):
    """오래된 이력 정리."""
    for code in list(hist.keys()):
        dates = sorted(hist[code].keys(), reverse=True)
        for d in dates[keep:]:
            del hist[code][d]
        if not hist[code]:
            del hist[code]
    return hist


def count_consecutive_buy(hist, code, field):
    """연속 순매수 거래일 수."""
    if code not in hist:
        return 0
    dates = sorted(hist[code].keys(), reverse=True)
    count = 0
    for d in dates:
        val = hist[code][d].get(field, 0)
        if val > 0:
            count += 1
        else:
            break
    return count


# ── 파일 관리 ──
def update_index():
    """screener 디렉토리의 날짜별 파일 목록으로 index.json 갱신."""
    files = glob.glob(os.path.join(OUT_DIR, '20??-??-??.json'))
    dates = sorted([os.path.splitext(os.path.basename(f))[0]
                     for f in files], reverse=True)
    idx = {'dates': dates, 'latest': dates[0] if dates else None}
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    return dates


def cleanup_old_files():
    """1년 이상 지난 파일 삭제."""
    cutoff = (date.today() - timedelta(days=FILE_KEEP)).isoformat()
    files = glob.glob(os.path.join(OUT_DIR, '20??-??-??.json'))
    removed = 0
    for f in files:
        fname = os.path.splitext(os.path.basename(f))[0]
        if fname < cutoff:
            os.remove(f)
            removed += 1
    if removed:
        print(f'🗑️  오래된 파일 {removed}개 삭제')


# ── 메인 ──
def main():
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수 필요')
        sys.exit(1)

    today = date.today()
    today_str = today.strftime('%Y%m%d')
    today_iso = today.isoformat()

    stocks = load_stock_list()
    print(f'📊 KOSPI 200 스크리너')
    print(f'   기준일: {today_iso}')
    print(f'   종목: {len(stocks)}개')
    print()

    token = get_access_token()

    # 수급 이력 로드
    inv_hist = load_investor_history()

    # ── 종목별 데이터 수집 ──
    all_signals = {
        'ma50_breakout': [],
        'bb_upper_close': [],
        'bb_upper_intra': [],
        'rally_3d_10pct': [],
        'foreign_top15_buy': [],
        'foreign_top15_sell': [],
        'institution_top15_buy': [],
        'institution_top15_sell': [],
        'foreign_consecutive': [],
        'institution_consecutive': [],
    }

    # 수급 데이터 임시 저장 (Top 15 정렬용)
    investor_today = []

    total = len(stocks)
    for i, s in enumerate(stocks, 1):
        code = s['code']
        name = s['name']
        sector = s['sector']
        print(f'[{i}/{total}] {name}', end='', flush=True)

        # 1) OHLCV
        ohlcv = fetch_ohlcv(token, code, today_str)
        time.sleep(CALL_DELAY)

        if not ohlcv:
            print(' ✗ (OHLCV 없음)')
            continue

        latest_price = ohlcv[-1]['close'] if ohlcv else 0

        # 2) 기술적 시그널
        sig = detect_signals(ohlcv)
        base = {'code': code, 'name': name, 'sector': sector,
                'price': latest_price}

        for key in ['ma50_breakout', 'bb_upper_close',
                     'bb_upper_intra', 'rally_3d_10pct']:
            if key in sig:
                entry = {**base, **sig[key]}
                all_signals[key].append(entry)

        # 3) 수급
        inv = fetch_investor(token, code)
        time.sleep(CALL_DELAY)

        if inv:
            # 이력 기록
            if code not in inv_hist:
                inv_hist[code] = {}
            inv_hist[code][today_iso] = {
                'foreign': inv.get('foreign_qty', 0),
                'institution': inv.get('institution_qty', 0),
            }

            investor_today.append({
                'code': code, 'name': name, 'sector': sector,
                'price': latest_price,
                'foreign_qty': inv.get('foreign_qty', 0),
                'foreign_amt': inv.get('foreign_amt', 0),
                'institution_qty': inv.get('institution_qty', 0),
                'institution_amt': inv.get('institution_amt', 0),
            })

        sig_keys = [k for k in sig]
        print(f' ✓ {sig_keys}' if sig_keys else ' ✓')

    # ── 수급 Top 15 + 연속 매수 ──
    print('\n📊 수급 정리...')

    # 외인 Top 15 매수/매도
    sorted_foreign = sorted(investor_today,
                            key=lambda x: x['foreign_amt'], reverse=True)
    all_signals['foreign_top15_buy'] = [
        {**x, 'net_amt': x['foreign_amt'], 'net_qty': x['foreign_qty']}
        for x in sorted_foreign[:15] if x['foreign_amt'] > 0
    ]
    all_signals['foreign_top15_sell'] = [
        {**x, 'net_amt': x['foreign_amt'], 'net_qty': x['foreign_qty']}
        for x in sorted_foreign[-15:][::-1] if x['foreign_amt'] < 0
    ]
    # 기관 Top 15
    sorted_inst = sorted(investor_today,
                         key=lambda x: x['institution_amt'], reverse=True)
    all_signals['institution_top15_buy'] = [
        {**x, 'net_amt': x['institution_amt'],
         'net_qty': x['institution_qty']}
        for x in sorted_inst[:15] if x['institution_amt'] > 0
    ]
    all_signals['institution_top15_sell'] = [
        {**x, 'net_amt': x['institution_amt'],
         'net_qty': x['institution_qty']}
        for x in sorted_inst[-15:][::-1] if x['institution_amt'] < 0
    ]

    # 연속 순매수
    for s in stocks:
        fc = count_consecutive_buy(inv_hist, s['code'], 'foreign')
        ic = count_consecutive_buy(inv_hist, s['code'], 'institution')
        base = {'code': s['code'], 'name': s['name'],
                'sector': s['sector']}
        if fc >= 3:
            all_signals['foreign_consecutive'].append(
                {**base, 'consecutive': fc})
        if ic >= 3:
            all_signals['institution_consecutive'].append(
                {**base, 'consecutive': ic})

    # 연속 순매수 정렬 (일수 내림차순)
    all_signals['foreign_consecutive'].sort(
        key=lambda x: x['consecutive'], reverse=True)
    all_signals['institution_consecutive'].sort(
        key=lambda x: x['consecutive'], reverse=True)

    # ── 저장 ──
    os.makedirs(OUT_DIR, exist_ok=True)

    # 수급 이력 정리 & 저장
    inv_hist = trim_history(inv_hist)
    save_investor_history(inv_hist)

    # 서머리
    summary = {k: len(v) for k, v in all_signals.items()}

    output = {
        'date':    today_iso,
        'updated': today_iso,
        'signals': all_signals,
        'summary': summary,
    }

    out_file = os.path.join(OUT_DIR, f'{today_iso}.json')
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 인덱스 갱신
    dates = update_index()

    # 오래된 파일 삭제
    cleanup_old_files()

    # ── 결과 출력 ──
    print(f'\n{"="*50}')
    print(f'✅ 스크리너 완료 → {out_file}')
    print(f'   보관 중: {len(dates)}일치')
    print()
    for k, v in summary.items():
        label = {
            'ma50_breakout':          '10주선 돌파',
            'bb_upper_close':         '볼밴상단 종가돌파',
            'bb_upper_intra':         '볼밴상단 장중돌파',
            'rally_3d_10pct':         '3일양봉 10%↑',
            'foreign_top15_buy':      '외인 매수 Top15',
            'foreign_top15_sell':     '외인 매도 Top15',
            'institution_top15_buy':  '기관 매수 Top15',
            'institution_top15_sell': '기관 매도 Top15',
            'foreign_consecutive':    '외인 연속매수(3일↑)',
            'institution_consecutive':'기관 연속매수(3일↑)',
        }.get(k, k)
        print(f'   {label}: {v}종목')


if __name__ == '__main__':
    main()
