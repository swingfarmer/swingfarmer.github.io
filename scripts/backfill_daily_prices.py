#!/usr/bin/env python3
"""
DAILY_PRICES 백필 — KIS API 일봉(FHKST01010900)
=================================================
KOSPI(시총1조↑) + KOSDAQ(시총5천억↑) 전 종목의
과거 종가 히스토리를 Oracle DB에 저장.

사용법:
  python3 scripts/backfill_daily_prices.py                  # 기본: 2026-07-01 ~ 오늘
  python3 scripts/backfill_daily_prices.py --start 20260901 # 시작일 지정
  python3 scripts/backfill_daily_prices.py --resume 005930  # 중단 후 재개 (해당 코드부터)

KIS API FHKST01010900:
  - 일봉 조회 (시가/고가/저가/종가/거래량)
  - 최대 100건/호출 (100 거래일)
  - 호출 제한: 초당 20회 → delay 0.06s
  - 토큰 발급: 1분 1회 제한 → 스크립트 시작 시 1회만
"""
import os, sys, csv, json, time
import urllib.request
from datetime import date, datetime

# ── 환경변수 ──
def load_env():
    f = os.path.expanduser('~/.env_secrets')
    if os.path.exists(f):
        for line in open(f):
            line = line.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('export '): line = line[7:]
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
load_env()

import oracledb

KIS_APP_KEY    = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE       = os.environ.get('KIS_BASE_URL', 'https://openapi.koreainvestment.com:9443')

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
KOSPI_LIST  = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
KOSDAQ_LIST = os.path.join(SCRIPT_DIR, 'kosdaq_list.csv')

WALLET_DIR  = os.path.expanduser('~/wallet')
CALL_DELAY  = 0.06   # 초당 ~16회 (제한: 20)

DEFAULT_START = '20260701'  # 백필 시작일


def load_stocks(filepath):
    """CSV → [{code, name}]"""
    stocks = []
    if not os.path.exists(filepath):
        print(f'  ⚠ {filepath} 없음')
        return stocks
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 2:
                stocks.append({'code': parts[0].strip(), 'name': parts[1].strip()})
    return stocks


def get_access_token():
    """KIS OAuth 토큰 발급 (1분 1회 제한)."""
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
        print(f'🔑 토큰 발급 완료')
        return token
    except Exception as e:
        print(f'❌ 토큰 발급 실패: {e}')
        sys.exit(1)


def fetch_daily_chart(token, stock_code, start_date, end_date):
    """
    KIS API FHKST01010900 — 일봉 조회.
    start_date, end_date: 'YYYYMMDD' 형식
    최대 100건 반환 (end_date 기준 과거 방향).
    반환: [{date, open, high, low, close, volume}, ...]
    """
    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
           f'?FID_COND_MRKT_DIV_CODE=J'
           f'&FID_INPUT_ISCD={stock_code}'
           f'&FID_INPUT_DATE_1={start_date}'
           f'&FID_INPUT_DATE_2={end_date}'
           f'&FID_PERIOD_DIV_CODE=D'
           f'&FID_ORG_ADJ_PRC=0')

    req = urllib.request.Request(url, headers={
        'Content-Type':  'application/json; charset=UTF-8',
        'authorization': f'Bearer {token}',
        'appkey':        KIS_APP_KEY,
        'appsecret':     KIS_APP_SECRET,
        'tr_id':         'FHKST01010400',
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return None, str(e)

    if data.get('rt_cd') != '0':
        return None, data.get('msg1', 'unknown error')

    items = data.get('output2', [])
    rows = []
    for item in items:
        dt_str = item.get('stck_bsop_date', '')  # YYYYMMDD
        close = item.get('stck_clpr', '')
        if not dt_str or not close or close == '0':
            continue
        try:
            rows.append({
                'date':   datetime.strptime(dt_str, '%Y%m%d').date(),
                'open':   int(item.get('stck_oprc', 0) or 0),
                'high':   int(item.get('stck_hgpr', 0) or 0),
                'low':    int(item.get('stck_lwpr', 0) or 0),
                'close':  int(close),
                'volume': int(item.get('acml_vol', 0) or 0),
            })
        except:
            continue

    return rows, None


def save_to_oracle(conn, stock_code, rows):
    """MERGE로 upsert."""
    if not rows:
        return 0
    cur = conn.cursor()
    cnt = 0
    for r in rows:
        try:
            cur.execute("""MERGE INTO daily_prices t
                USING (SELECT :code AS stock_code, :dt AS trade_date FROM dual) s
                ON (t.stock_code = s.stock_code AND t.trade_date = s.trade_date)
                WHEN NOT MATCHED THEN INSERT
                    (stock_code, trade_date, open_price, high_price, low_price, close_price, volume)
                    VALUES (:code2, :dt2, :op, :hi, :lo, :cl, :vol)
                WHEN MATCHED THEN UPDATE SET
                    open_price=:op2, high_price=:hi2, low_price=:lo2, close_price=:cl2, volume=:vol2""",
                {
                    'code': stock_code, 'dt': r['date'],
                    'code2': stock_code, 'dt2': r['date'],
                    'op': r['open'], 'hi': r['high'], 'lo': r['low'],
                    'cl': r['close'], 'vol': r['volume'],
                    'op2': r['open'], 'hi2': r['high'], 'lo2': r['low'],
                    'cl2': r['close'], 'vol2': r['volume'],
                })
            cnt += 1
        except Exception as e:
            print(f'    ⚠ {stock_code}/{r["date"]} 저장실패: {e}')
    conn.commit()
    cur.close()
    return cnt


def main():
    import argparse
    parser = argparse.ArgumentParser(description='DAILY_PRICES 백필')
    parser.add_argument('--start', default=DEFAULT_START, help='시작일 YYYYMMDD (기본: 20260701)')
    parser.add_argument('--resume', default=None, help='재개할 종목코드 (이 코드부터 시작)')
    args = parser.parse_args()

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수 필요')
        sys.exit(1)

    start_date = args.start
    end_date = date.today().strftime('%Y%m%d')

    # 종목 로드
    kospi = load_stocks(KOSPI_LIST)
    kosdaq = load_stocks(KOSDAQ_LIST)
    all_stocks = kospi + kosdaq

    # --resume 처리
    if args.resume:
        idx = next((i for i, s in enumerate(all_stocks) if s['code'] == args.resume), None)
        if idx is None:
            print(f'❌ 종목코드 {args.resume} 못 찾음')
            sys.exit(1)
        all_stocks = all_stocks[idx:]
        print(f'⏩ {args.resume}부터 재개 ({len(all_stocks)}종목 남음)')

    print(f'📊 DAILY_PRICES 백필')
    print(f'   기간: {start_date} ~ {end_date}')
    print(f'   종목: {len(all_stocks)}개')
    print()

    # 토큰 발급
    token = get_access_token()
    time.sleep(1)

    # Oracle 연결
    conn = oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))

    total_saved = 0
    errors = []

    for i, s in enumerate(all_stocks, 1):
        code = s['code']
        print(f'[{i}/{len(all_stocks)}] {s["name"]} ({code})...', end='', flush=True)

        rows, err = fetch_daily_chart(token, code, start_date, end_date)

        if err:
            print(f' ✗ ({err})')
            errors.append(f'{s["name"]}({code})')
            time.sleep(CALL_DELAY)
            continue

        if not rows:
            print(' (0건)')
            time.sleep(CALL_DELAY)
            continue

        saved = save_to_oracle(conn, code, rows)
        total_saved += saved
        print(f' ✓ {saved}건 ({rows[-1]["date"]} ~ {rows[0]["date"]})')
        time.sleep(CALL_DELAY)

    # 결과
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM daily_prices")
    db_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT stock_code) FROM daily_prices")
    db_stocks = cur.fetchone()[0]
    cur.execute("""SELECT TO_CHAR(MIN(trade_date),'YYYY-MM-DD'),
                          TO_CHAR(MAX(trade_date),'YYYY-MM-DD') FROM daily_prices""")
    mn, mx = cur.fetchone()
    cur.close()
    conn.close()

    print(f'\n{"="*50}')
    print(f'✅ 백필 완료: 이번 {total_saved}건 저장')
    print(f'   DB 현황: 총 {db_total}건, {db_stocks}종목, {mn} ~ {mx}')
    if errors:
        print(f'❌ 실패 {len(errors)}건: {", ".join(errors[:10])}')
        if len(errors) > 10:
            print(f'   ... 외 {len(errors)-10}건')


if __name__ == '__main__':
    main()
