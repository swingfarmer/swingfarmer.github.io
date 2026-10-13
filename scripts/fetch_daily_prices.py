#!/usr/bin/env python3
"""
DAILY_PRICES 일일 수집 — KIS API 일봉(FHKST01010900)
=====================================================
당일 포함 최근 5거래일 종가를 Oracle에 MERGE (upsert).
기존 데이터가 있으면 덮어쓰므로 중복 걱정 없음.

cron 예시 (평일 18:40, fetch_prices 이후):
  40 18 * * 1-5 cd ~/swingfarmer.github.io && . ~/.env_secrets && python3 scripts/fetch_daily_prices.py >> logs/fetch_daily_prices.log 2>&1

사용법:
  python3 scripts/fetch_daily_prices.py            # 최근 5거래일
  python3 scripts/fetch_daily_prices.py --days 20  # 최근 20거래일
"""
import os, sys, csv, json, time
import urllib.request
from datetime import date, datetime, timedelta

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
CALL_DELAY  = 0.06


def load_stocks(filepath):
    stocks = []
    if not os.path.exists(filepath):
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
        return token
    except Exception as e:
        print(f'❌ 토큰 발급 실패: {e}')
        sys.exit(1)


def fetch_daily_chart(token, stock_code, start_date, end_date):
    """KIS API FHKST01010900 — 일봉 조회."""
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
        'tr_id':         'FHKST03010100',
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return None, str(e)

    if data.get('rt_cd') != '0':
        return None, data.get('msg1', 'error')

    items = data.get('output2', [])
    rows = []
    for item in items:
        dt_str = item.get('stck_bsop_date', '')
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
            print(f'    ⚠ {stock_code}/{r["date"]}: {e}')
    conn.commit()
    cur.close()
    return cnt


def main():
    import argparse
    parser = argparse.ArgumentParser(description='DAILY_PRICES 일일 수집')
    parser.add_argument('--days', type=int, default=5, help='최근 N 거래일 (기본: 5)')
    args = parser.parse_args()

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수 필요')
        sys.exit(1)

    today = date.today()
    # 달력일 기준 넉넉하게 (주말/공휴일 감안)
    start_dt = today - timedelta(days=args.days * 2)
    start_date = start_dt.strftime('%Y%m%d')
    end_date = today.strftime('%Y%m%d')

    kospi = load_stocks(KOSPI_LIST)
    kosdaq = load_stocks(KOSDAQ_LIST)
    all_stocks = kospi + kosdaq

    print(f'📊 DAILY_PRICES 일일 수집: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'   기간: {start_date} ~ {end_date} (최근 {args.days}거래일)')
    print(f'   종목: {len(all_stocks)}개')

    token = get_access_token()
    print(f'🔑 토큰 발급 완료')

    conn = oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))

    total_saved = 0
    errors = []

    for i, s in enumerate(all_stocks, 1):
        code = s['code']
        rows, err = fetch_daily_chart(token, code, start_date, end_date)
        if err:
            errors.append(s['name'])
            time.sleep(CALL_DELAY)
            continue
        if rows:
            saved = save_to_oracle(conn, code, rows)
            total_saved += saved
        time.sleep(CALL_DELAY)

        # 진행률 (50개마다)
        if i % 50 == 0:
            print(f'  [{i}/{len(all_stocks)}] {total_saved}건 저장...')

    # 결과
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM daily_prices")
    db_total = cur.fetchone()[0]
    cur.execute("""SELECT TO_CHAR(MAX(trade_date),'YYYY-MM-DD') FROM daily_prices""")
    latest = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f'\n✅ 일일 수집 완료: {total_saved}건 저장/갱신')
    print(f'   DB 총 {db_total}건, 최신일 {latest}')
    if errors:
        print(f'   ❌ 실패: {len(errors)}건')


if __name__ == '__main__':
    main()
