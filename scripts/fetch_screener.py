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
  data/kr/screener/investor_hist.json (수급 누적 — 60거래일 롤링)

# TODO [오라클 이관]
# data/kr/screener/ 일별 JSON을 오라클로 옮기면
# GitHub 쪽 screener/ 폴더 삭제하여 용량 확보 가능 (10년 ~125MB 추정).
# 이관 후 이 스크립트도 오라클 cron으로 전환.
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
FILE_KEEP   = None           # 무제한 보관 (오라클 이관 예정)


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
    """종목별 투자자 매매 동향 (최근 거래일 기준).
    FHKST01010900 응답은 날짜별 행 — 각 행에 외인/기관/프로그램 필드."""
    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/'
           f'inquire-investor'
           f'?FID_COND_MRKT_DIV_CODE=J'
           f'&FID_INPUT_ISCD={code}')
    data = kis_request(url, token, 'FHKST01010900')
    if not data:
        return None
    output = data.get('output', [])
    if not output:
        return None

    # 디버그: 첫 종목에서 응답 필드명 전체 출력
    global _investor_fields_logged
    if not _investor_fields_logged:
        keys = list(output[0].keys()) if output else []
        print(f'   📋 투자자 응답 필드: {keys}')
        # 첫 행 값도 출력
        if output:
            print(f'   📋 첫 행 데이터: {output[0]}')
        _investor_fields_logged = True

    # 최신 거래일 데이터 (첫 행)
    row = output[0]

    # 필드명 후보 (KIS API 버전에 따라 다를 수 있음)
    result = {}

    # 외국인 순매수
    frgn_qty = (safe_int(row.get('frgn_ntby_qty'))
                or safe_int(row.get('frgn_ntby_stcn'))
                or safe_int(row.get('ntby_qty')))
    frgn_amt = (safe_int(row.get('frgn_ntby_tr_pbmn'))
                or safe_int(row.get('frgn_ntby_tr_mhht')))
    result['foreign_qty'] = frgn_qty
    result['foreign_amt'] = frgn_amt

    # 기관 순매수
    orgn_qty = (safe_int(row.get('orgn_ntby_qty'))
                or safe_int(row.get('orgn_ntby_stcn')))
    orgn_amt = (safe_int(row.get('orgn_ntby_tr_pbmn'))
                or safe_int(row.get('orgn_ntby_tr_mhht')))
    result['institution_qty'] = orgn_qty
    result['institution_amt'] = orgn_amt

    # 프로그램 순매수 — FHKST01010900에는 프로그램 필드 없음
    # → fetch_program_trade()에서 별도 수집 (FHPPG04650201)
    result['program_qty'] = 0
    result['program_amt'] = 0

    return result

_investor_fields_logged = False  # 첫 호출에서만 로그


def fetch_program_trade(token, code):
    """종목별 프로그램매매추이(일별) — FHPPG04650201.
    최근 5거래일 프로그램 순매수 수량/금액 반환.
    [{date, program_qty, program_amt}, ...]  (날짜 오름차순)"""
    global _program_fields_logged
    today_str = date.today().strftime('%Y%m%d')
    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/'
           f'program-trade-by-stock-daily'
           f'?FID_COND_MRKT_DIV_CODE=J'
           f'&FID_INPUT_ISCD={code}'
           f'&FID_INPUT_DATE_1={today_str}')
    data = kis_request(url, token, 'FHPPG04650201')

    # 디버그: 첫 종목에서 에러 확인
    if not _program_fields_logged and data is None:
        print(f'   ⚠️ 프로그램매매 API 호출 실패 — 에러 응답 직접 확인 중...')
        try:
            req = urllib.request.Request(url, headers={
                'Content-Type':  'application/json; charset=UTF-8',
                'authorization': f'Bearer {token}',
                'appkey':        KIS_APP_KEY,
                'appsecret':     KIS_APP_SECRET,
                'tr_id':         'FHPPG04650201',
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = json.loads(resp.read().decode('utf-8'))
            print(f'   📋 rt_cd={raw.get("rt_cd")}, msg_cd={raw.get("msg_cd")}, msg1={raw.get("msg1")}')
            print(f'   📋 응답 키: {list(raw.keys())}')
        except urllib.error.HTTPError as he:
            body = he.read().decode('utf-8', errors='replace')
            print(f'   📋 HTTP {he.code}: {body[:300]}')
        except Exception as ex:
            print(f'   📋 예외: {ex}')
        _program_fields_logged = True
        return []

    if not data:
        return []

    output = data.get('output', [])
    if not output:
        output = data.get('output2', [])
    if not output:
        return []

    # 디버그: 첫 종목에서 응답 필드명 전체 출력
    if not _program_fields_logged:
        keys = list(output[0].keys()) if output else []
        print(f'   📋 프로그램매매 응답 필드: {keys}')
        if output:
            print(f'   📋 첫 행: {output[0]}')
        _program_fields_logged = True

    result = []
    for row in output[:5]:  # 최근 5일만
        d = (row.get('stck_bsop_date', '')
             or row.get('bsop_date', '')
             or row.get('stck_bsop_date_1', ''))
        if not d:
            continue
        # 프로그램 순매수 수량/금액 (필드명 후보)
        pgm_qty = (safe_int(row.get('prgm_ntby_qty'))
                   or safe_int(row.get('ntby_qty'))
                   or safe_int(row.get('prgm_seln_qty'))
                   - safe_int(row.get('prgm_shnu_qty', 0))
                   if safe_int(row.get('prgm_seln_qty')) else 0)
        # 매도-매수 분리형이면 순매수 계산
        if pgm_qty == 0:
            sell = safe_int(row.get('prgm_seln_qty', 0))
            buy = safe_int(row.get('prgm_shnu_qty', 0))
            if sell or buy:
                pgm_qty = buy - sell

        pgm_amt = (safe_int(row.get('prgm_ntby_tr_pbmn'))
                   or safe_int(row.get('ntby_tr_pbmn'))
                   or 0)
        if pgm_amt == 0:
            sell_a = safe_int(row.get('prgm_seln_tr_pbmn', 0))
            buy_a = safe_int(row.get('prgm_shnu_tr_pbmn', 0))
            if sell_a or buy_a:
                pgm_amt = buy_a - sell_a

        result.append({
            'date': d,
            'program_qty': pgm_qty,
            'program_amt': pgm_amt,
        })

    # 날짜 오름차순 정렬
    result.sort(key=lambda x: x['date'])
    return result

_program_fields_logged = False


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


def calc_rsi(closes, period=14):
    """RSI (Relative Strength Index)."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        change = closes[i] - closes[i - 1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calc_ema(prices, period):
    """EMA 시리즈의 마지막 값 반환."""
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_macd(closes):
    """MACD, Signal 마지막 값 반환."""
    if len(closes) < 35:  # 26 + 9
        return None, None, None, None
    # EMA12, EMA26 시리즈 생성
    k12, k26 = 2 / 13, 2 / 27
    ema12 = sum(closes[:12]) / 12
    ema26 = sum(closes[:26]) / 26
    macd_series = []
    for i in range(26, len(closes)):
        if i < 26:
            continue
        # EMA12 up to i
        e12 = sum(closes[:12]) / 12
        for j in range(12, i + 1):
            e12 = closes[j] * k12 + e12 * (1 - k12)
        e26 = sum(closes[:26]) / 26
        for j in range(26, i + 1):
            e26 = closes[j] * k26 + e26 * (1 - k26)
        macd_series.append(e12 - e26)
    if len(macd_series) < 10:
        return None, None, None, None
    # Signal (EMA9 of MACD)
    k9 = 2 / 10
    sig = sum(macd_series[:9]) / 9
    prev_sig = sig
    for m in macd_series[9:]:
        prev_sig = sig
        sig = m * k9 + sig * (1 - k9)
    macd_now = macd_series[-1]
    macd_prev = macd_series[-2]
    return macd_now, sig, macd_prev, prev_sig


def detect_signals(ohlcv):
    """OHLCV 배열에서 모든 기술적 시그널 판별."""
    signals = {}
    if len(ohlcv) < 51:
        return signals

    closes = [d['close'] for d in ohlcv]
    volumes = [d['volume'] for d in ohlcv]
    latest = ohlcv[-1]
    price = latest['close']

    # ── MA / 크로스 ──
    ma5_now = calc_ma(closes, 5)
    ma5_prev = calc_ma(closes[:-1], 5)
    ma20_now = calc_ma(closes, 20)
    ma20_prev = calc_ma(closes[:-1], 20)
    ma50_now = calc_ma(closes, 50)
    ma50_prev = calc_ma(closes[:-1], 50)
    ma60_now = calc_ma(closes, 60) if len(closes) >= 60 else None

    # ① 50일선(10주선) 종가 돌파
    if ma50_now and ma50_prev:
        prev_close = ohlcv[-2]['close']
        if prev_close < ma50_prev and price >= ma50_now:
            signals['ma50_breakout'] = {
                'price': price, 'ma50': round(ma50_now)}

    # ⑤ 골든크로스 (MA5 > MA20 돌파)
    if ma5_now and ma5_prev and ma20_now and ma20_prev:
        if ma5_prev <= ma20_prev and ma5_now > ma20_now:
            signals['golden_cross'] = {
                'price': price, 'ma5': round(ma5_now),
                'ma20': round(ma20_now)}

    # ⑥ 데드크로스 (MA5 < MA20 돌파)
    if ma5_now and ma5_prev and ma20_now and ma20_prev:
        if ma5_prev >= ma20_prev and ma5_now < ma20_now:
            signals['dead_cross'] = {
                'price': price, 'ma5': round(ma5_now),
                'ma20': round(ma20_now)}

    # ⑦ 정배열 (MA5 > MA20 > MA60)
    if ma5_now and ma20_now and ma60_now:
        if ma5_now > ma20_now > ma60_now:
            signals['aligned_bull'] = {
                'price': price, 'ma5': round(ma5_now),
                'ma20': round(ma20_now), 'ma60': round(ma60_now)}

    # ── 볼린저밴드 ──
    bb_upper = calc_bollinger_upper(closes)
    if bb_upper:
        bb_upper = round(bb_upper)
        if price > bb_upper:
            signals['bb_upper_close'] = {
                'price': price, 'bb_upper': bb_upper}
        elif latest['high'] > bb_upper:
            signals['bb_upper_intra'] = {
                'price': price, 'high': latest['high'],
                'bb_upper': bb_upper}

    # ── 3일 연속 양봉 10%↑ ──
    if len(ohlcv) >= 4:
        last3 = ohlcv[-3:]
        all_bullish = all(d['close'] > d['open'] for d in last3)
        if all_bullish:
            base_close = ohlcv[-4]['close']
            if base_close > 0:
                gain = (price - base_close) / base_close * 100
                if gain >= 10:
                    signals['rally_3d_10pct'] = {
                        'price': price, 'gain_3d': round(gain, 1)}

    # ── 거래량 ──
    vol_avg20 = calc_ma(volumes, 20)
    vol_avg5 = calc_ma(volumes[-5:], 5) if len(volumes) >= 5 else None
    vol_avg100 = calc_ma(volumes, min(len(volumes), 100))

    # ⑧ 거래량 폭발 (당일 > 20일평균 × 2)
    if vol_avg20 and vol_avg20 > 0 and latest['volume'] > 0:
        vol_ratio = latest['volume'] / vol_avg20
        if vol_ratio >= 2:
            signals['volume_spike'] = {
                'price': price, 'volume': latest['volume'],
                'avg20': round(vol_avg20),
                'ratio': round(vol_ratio, 1)}

    # ⑭ 거래량 돌파 (5일평균 > 100일평균) — 이미지 스크리너 재현
    if vol_avg5 and vol_avg100 and vol_avg100 > 0:
        vol_change = (vol_avg5 / vol_avg100 - 1) * 100
        if vol_avg5 > vol_avg100:
            signals['volume_breakout'] = {
                'price': price, 'vol_avg5': round(vol_avg5),
                'vol_avg100': round(vol_avg100),
                'change_pct': round(vol_change, 1)}

    # ── 52주 신고가/신저가 ──
    if len(closes) >= 5:
        high_52w = max(d['high'] for d in ohlcv)
        low_52w = min(d['low'] for d in ohlcv)
        if latest['high'] >= high_52w:
            signals['new_high_52w'] = {'price': price, 'high': latest['high']}
        if latest['low'] <= low_52w:
            signals['new_low_52w'] = {'price': price, 'low': latest['low']}

    # ── RSI ──
    rsi = calc_rsi(closes)
    if rsi is not None:
        if rsi <= 30:
            signals['rsi_oversold'] = {'price': price, 'rsi': rsi}
        elif rsi >= 70:
            signals['rsi_overbought'] = {'price': price, 'rsi': rsi}

    # ── MACD 골든크로스 ──
    macd_now, sig_now, macd_prev, sig_prev = calc_macd(closes)
    if macd_now is not None and sig_now is not None:
        if macd_prev <= sig_prev and macd_now > sig_now:
            signals['macd_golden'] = {
                'price': price, 'macd': round(macd_now, 1),
                'signal': round(sig_now, 1)}

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
    """무제한 보관 — 삭제 없음."""
    pass


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
        'golden_cross': [],
        'dead_cross': [],
        'aligned_bull': [],
        'bb_upper_close': [],
        'bb_upper_intra': [],
        'rally_3d_10pct': [],
        'volume_spike': [],
        'volume_breakout': [],
        'new_high_52w': [],
        'new_low_52w': [],
        'rsi_oversold': [],
        'rsi_overbought': [],
        'macd_golden': [],
        'foreign_top15_buy': [],
        'foreign_top15_sell': [],
        'institution_top15_buy': [],
        'institution_top15_sell': [],
        'foreign_consecutive': [],
        'institution_consecutive': [],
        'program_absorb_bull': [],    # 프로그램매도 소화 + 외인순매수 (강세)
        'program_absorb_bear': [],    # 프로그램매수 + 외인순매도 (약세)
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

        for key in ['ma50_breakout', 'golden_cross', 'dead_cross',
                     'aligned_bull', 'bb_upper_close', 'bb_upper_intra',
                     'rally_3d_10pct', 'volume_spike', 'volume_breakout',
                     'new_high_52w', 'new_low_52w',
                     'rsi_oversold', 'rsi_overbought', 'macd_golden']:
            if key in sig:
                entry = {**base, **sig[key]}
                all_signals[key].append(entry)

        # 3) 수급 (외인/기관)
        inv = fetch_investor(token, code)
        time.sleep(CALL_DELAY)

        # 4) 프로그램매매 (별도 엔드포인트 FHPPG04650201)
        pgm_days = fetch_program_trade(token, code)
        time.sleep(CALL_DELAY)

        if inv:
            # 이력 기록 — 외인/기관은 당일 값
            if code not in inv_hist:
                inv_hist[code] = {}
            inv_hist[code][today_iso] = {
                'foreign': inv.get('foreign_qty', 0),
                'institution': inv.get('institution_qty', 0),
                'program': 0,  # 아래에서 프로그램 데이터로 덮어씀
            }

            # 프로그램매매 이력 병합 (최근 5거래일 백필)
            today_pgm_qty = 0
            today_pgm_amt = 0
            for pd in pgm_days:
                d_raw = pd['date']  # YYYYMMDD
                d_iso = f'{d_raw[:4]}-{d_raw[4:6]}-{d_raw[6:8]}'
                if d_iso in inv_hist[code]:
                    # 기존 날짜에 프로그램 데이터 추가
                    inv_hist[code][d_iso]['program'] = pd['program_qty']
                else:
                    # 과거 날짜 — 프로그램만 기록 (외인/기관은 이미 이전 실행에서 기록됨)
                    inv_hist[code][d_iso] = {
                        'foreign': inv_hist[code].get(d_iso, {}).get('foreign', 0),
                        'institution': inv_hist[code].get(d_iso, {}).get('institution', 0),
                        'program': pd['program_qty'],
                    }
                if d_iso == today_iso:
                    today_pgm_qty = pd['program_qty']
                    today_pgm_amt = pd['program_amt']

            investor_today.append({
                'code': code, 'name': name, 'sector': sector,
                'price': latest_price,
                'foreign_qty': inv.get('foreign_qty', 0),
                'foreign_amt': inv.get('foreign_amt', 0),
                'institution_qty': inv.get('institution_qty', 0),
                'institution_amt': inv.get('institution_amt', 0),
                'program_qty': today_pgm_qty,
                'program_amt': today_pgm_amt,
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

    # ── 프로그램매도 소화 + 외인순매수 (3일 연속) ──
    # 조건: 프로그램 순매도(음수) + 외인 순매수(양수) 3일 연속
    #       → 외인이 프로그램 매도 물량을 흡수하며 추가 매수 (강세 패턴)
    # 반대: 프로그램 순매수(양수) + 외인 순매도(음수) 3일 연속 (약세 패턴)
    has_program_data = any(
        s.get('program_qty', 0) != 0 for s in investor_today
    )

    if has_program_data:
        print('\n🔍 프로그램 vs 외인 패턴 분석...')
        for s in stocks:
            code = s['code']
            if code not in inv_hist:
                continue
            dates = sorted(inv_hist[code].keys(), reverse=True)
            if len(dates) < 3:
                continue

            # 최근 3거래일 체크
            bull_days = 0   # 프로그램매도 + 외인매수
            bear_days = 0   # 프로그램매수 + 외인매도
            for d in dates[:3]:
                day = inv_hist[code][d]
                pgm = day.get('program', 0)
                frn = day.get('foreign', 0)
                if pgm < 0 and frn > 0:
                    bull_days += 1
                if pgm > 0 and frn < 0:
                    bear_days += 1

            base = {'code': code, 'name': s['name'],
                    'sector': s['sector']}

            if bull_days >= 3:
                # 최근 일자 수급 정보 추가
                latest = inv_hist[code][dates[0]]
                all_signals['program_absorb_bull'].append({
                    **base,
                    'consecutive': bull_days,
                    'foreign_qty': latest.get('foreign', 0),
                    'program_qty': latest.get('program', 0),
                })
            if bear_days >= 3:
                latest = inv_hist[code][dates[0]]
                all_signals['program_absorb_bear'].append({
                    **base,
                    'consecutive': bear_days,
                    'foreign_qty': latest.get('foreign', 0),
                    'program_qty': latest.get('program', 0),
                })

        all_signals['program_absorb_bull'].sort(
            key=lambda x: x.get('foreign_qty', 0), reverse=True)
        all_signals['program_absorb_bear'].sort(
            key=lambda x: x.get('foreign_qty', 0))

        bull_n = len(all_signals['program_absorb_bull'])
        bear_n = len(all_signals['program_absorb_bear'])
        if bull_n or bear_n:
            print(f'   강세패턴(프매도+외매수): {bull_n}종목')
            print(f'   약세패턴(프매수+외매도): {bear_n}종목')
    else:
        print('\n⚠️  프로그램매매 데이터 없음 — 시그널 비활성')
        print('   → 월요일 Actions 로그에서 📋 투자자 항목 확인 필요')

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

    # 무제한 보관 (cleanup_old_files는 no-op)
    cleanup_old_files()

    # ── 결과 출력 ──
    print(f'\n{"="*50}')
    print(f'✅ 스크리너 완료 → {out_file}')
    print(f'   보관 중: {len(dates)}일치')
    print()
    for k, v in summary.items():
        label = {
            'ma50_breakout':          '10주선 돌파',
            'golden_cross':           '골든크로스',
            'dead_cross':             '데드크로스',
            'aligned_bull':           '정배열',
            'bb_upper_close':         '볼밴상단 종가돌파',
            'bb_upper_intra':         '볼밴상단 장중돌파',
            'rally_3d_10pct':         '3일양봉 10%↑',
            'volume_spike':           '거래량 폭발(2배↑)',
            'volume_breakout':        '거래량 돌파(5일>100일)',
            'new_high_52w':           '52주 신고가',
            'new_low_52w':            '52주 신저가',
            'rsi_oversold':           'RSI 과매도(≤30)',
            'rsi_overbought':         'RSI 과매수(≥70)',
            'macd_golden':            'MACD 골든',
            'foreign_top15_buy':      '외인 매수 Top15',
            'foreign_top15_sell':     '외인 매도 Top15',
            'institution_top15_buy':  '기관 매수 Top15',
            'institution_top15_sell': '기관 매도 Top15',
            'foreign_consecutive':    '외인 연속매수(3일↑)',
            'institution_consecutive':'기관 연속매수(3일↑)',
            'program_absorb_bull':   '🟢 프매도+외매수(3일↑)',
            'program_absorb_bear':   '🔴 프매수+외매도(3일↑)',
        }.get(k, k)
        print(f'   {label}: {v}종목')


if __name__ == '__main__':
    main()
