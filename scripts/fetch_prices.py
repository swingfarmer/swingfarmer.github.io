"""
한국주식 주가 데이터 수집 — KIS Open API
=========================================
한투 Open API로 KOSPI 200 종목의 현재가·시총·52주 고저·PER/PBR 수집.
재무 데이터(DART)와 분리 — 이 파일만 매일 갱신.

사용법:
  python scripts/fetch_prices.py

출력: data/kr/prices.json

환경변수 (필수):
  KIS_APP_KEY     — 한투 Open API 앱 키
  KIS_APP_SECRET  — 한투 Open API 앱 시크릿

환경변수 (선택):
  KIS_BASE_URL    — API base URL (기본: https://openapi.koreainvestment.com:9443)
"""

import os, sys, csv, json, time
import urllib.request
from datetime import date

KIS_APP_KEY    = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE       = os.environ.get('KIS_BASE_URL', 'https://openapi.koreainvestment.com:9443')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)
STOCK_LIST = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
OUT_FILE   = os.path.join(ROOT_DIR, 'data', 'kr', 'prices.json')

CALL_DELAY = 0.06  # ~16 req/s (KIS 제한: 초당 20)


def load_stock_list():
    stocks = []
    with open(STOCK_LIST, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 2:
                stocks.append({'code': parts[0].strip(), 'name': parts[1].strip()})
    return stocks


def get_access_token():
    """OAuth 토큰 발급."""
    url = f'{KIS_BASE}/oauth2/tokenP'
    body = json.dumps({
        'grant_type': 'client_credentials',
        'appkey':     KIS_APP_KEY,
        'appsecret':  KIS_APP_SECRET,
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
        print(f'🔑 토큰 발급 완료 (유효: {data.get("token_type","")})')
        return token
    except Exception as e:
        print(f'❌ 토큰 발급 실패: {e}')
        sys.exit(1)


def fetch_stock_price(token, stock_code):
    """종목별 현재가 조회 (FHKST01010100)."""
    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/inquire-price'
           f'?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD={stock_code}')

    req = urllib.request.Request(url, headers={
        'Content-Type':  'application/json; charset=UTF-8',
        'authorization': f'Bearer {token}',
        'appkey':        KIS_APP_KEY,
        'appsecret':     KIS_APP_SECRET,
        'tr_id':         'FHKST01010100',
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('rt_cd') != '0':
            return None
        return data.get('output', {})
    except:
        return None


def safe_int(val):
    """문자열 → int, 실패 또는 0이면 None."""
    try:
        v = int(val)
        return v if v != 0 else None
    except:
        return None


def safe_float(val):
    """문자열 → float, 실패 또는 0 이하면 None."""
    try:
        v = float(val)
        return round(v, 2) if v > 0 else None
    except:
        return None


def main():
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수 필요')
        sys.exit(1)

    today = date.today()
    stocks = load_stock_list()

    print(f'📈 주가 데이터 수집 (KIS Open API)')
    print(f'   기준일: {today}')
    print(f'   종목: {len(stocks)}개')
    print()

    token = get_access_token()

    prices = {}
    errors = []

    for i, s in enumerate(stocks, 1):
        code = s['code']
        print(f'[{i}/{len(stocks)}] {s["name"]} ({code})...', end='', flush=True)

        out = fetch_stock_price(token, code)
        if not out:
            print(' ✗')
            errors.append(s['name'])
            time.sleep(CALL_DELAY)
            continue

        price = safe_int(out.get('stck_prpr'))         # 현재가
        if not price:
            print(' ✗ (가격 없음)')
            errors.append(s['name'])
            time.sleep(CALL_DELAY)
            continue

        entry = {'price': price}

        # 시가총액 (억원 변환)
        mcap = safe_int(out.get('hts_avls'))  # HTS 시가총액 (억원 단위)
        if mcap:
            entry['market_cap'] = mcap

        # 상장주식수
        shares = safe_int(out.get('lstn_stcn'))
        if shares:
            entry['shares'] = shares

        # PER / PBR / EPS / BPS
        entry['per'] = safe_float(out.get('per'))
        entry['pbr'] = safe_float(out.get('pbr'))
        entry['eps'] = safe_int(out.get('eps'))
        entry['bps'] = safe_int(out.get('bps'))

        # 52주 최고/최저
        entry['high_52w'] = safe_int(out.get('w52_hgpr'))
        entry['low_52w']  = safe_int(out.get('w52_lwpr'))

        # 배당수익률 (HTS 기준)
        div_y = safe_float(out.get('hts_shrn_div_rate'))  # 예상 배당률
        if div_y:
            entry['div_yield'] = div_y

        prices[code] = entry
        print(' ✓')
        time.sleep(CALL_DELAY)

    # 저장
    output = {
        'updated':     today.isoformat(),
        'source':      'KIS Open API',
        'stock_count': len(prices),
        'prices':      prices,
    }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'\n{"="*50}')
    print(f'✅ {len(prices)}종목 → {OUT_FILE}')
    if errors:
        print(f'❌ 실패: {len(errors)} — {", ".join(errors[:10])}')


if __name__ == '__main__':
    main()
