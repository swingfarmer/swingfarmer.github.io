#!/usr/bin/env python3
"""
SECTOR_PRICES 일일 수집 — KIS API 업종지수 일봉(FHKUP03500100)
===============================================================
26개 KOSPI 업종지수 OHLCV를 Oracle에 MERGE (upsert).

cron 예시 (평일 20:15, fetch_daily_prices 이후):
  15 20 * * 1-5 . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/fetch_sector_prices.py >> ~/cron.log 2>&1

사용법:
  python3 scripts/fetch_sector_prices.py            # 최근 30거래일
  python3 scripts/fetch_sector_prices.py --days 200  # 최근 200거래일 (초기 적재)
"""
import os, sys, json, time
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
WALLET_DIR     = os.path.expanduser('~/wallet')
CALL_DELAY     = 0.1

# 26개 KOSPI 업종지수 (은행 0022 제외 — 데이터 없음)
SECTORS = [
    ('0001', '종합'), ('0002', '대형주'), ('0003', '중형주'), ('0004', '소형주'),
    ('0005', '음식료품'), ('0006', '섬유의복'), ('0007', '종이목재'), ('0008', '화학'),
    ('0009', '의약품'), ('0010', '비금속광물'), ('0011', '철강금속'), ('0012', '기계'),
    ('0013', '전기전자'), ('0014', '의료정밀'), ('0015', '운수장비'), ('0016', '유통업'),
    ('0017', '전기가스업'), ('0018', '건설업'), ('0019', '운수창고업'), ('0020', '통신업'),
    ('0021', '금융업'), ('0024', '증권'), ('0025', '보험'),
    ('0026', '서비스업'), ('0027', '제조업'), ('0028', '코스피200'),
]


def get_access_token():
    url = f'{KIS_BASE}/oauth2/tokenP'
    body = json.dumps({
        'grant_type': 'client_credentials',
        'appkey': KIS_APP_KEY,
        'appsecret': KIS_APP_SECRET,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())['access_token']


def fetch_sector_daily(token, sector_code, date_from, date_to):
    """업종지수 일봉 조회 — FHKUP03500100"""
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'authorization': f'Bearer {token}',
        'appkey': KIS_APP_KEY,
        'appsecret': KIS_APP_SECRET,
        'custtype': 'P',
        'tr_id': 'FHKUP03500100',
    }
    params = (
        f'FID_COND_MRKT_DIV_CODE=U'
        f'&FID_INPUT_ISCD={sector_code}'
        f'&FID_INPUT_DATE_1={date_from}'
        f'&FID_INPUT_DATE_2={date_to}'
        f'&FID_PERIOD_DIV_CODE=D'
    )
    url = f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice?{params}'
    req = urllib.request.Request(url, headers=headers)

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
        close = item.get('bstp_nmix_prpr', '')
        if not dt_str or not close or close == '0':
            continue
        try:
            rows.append({
                'date':   datetime.strptime(dt_str, '%Y%m%d').date(),
                'open':   float(item.get('bstp_nmix_oprc', 0) or 0),
                'high':   float(item.get('bstp_nmix_hgpr', 0) or 0),
                'low':    float(item.get('bstp_nmix_lwpr', 0) or 0),
                'close':  float(close),
                'volume': int(item.get('acml_vol', 0) or 0),
                'amount': int(item.get('acml_tr_pbmn', 0) or 0),
            })
        except:
            continue
    return rows, None


def ensure_table(conn):
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM sector_prices WHERE ROWNUM=1")
    except:
        conn.rollback()
        cur.execute("""CREATE TABLE sector_prices (
            sector_code  VARCHAR2(10)  NOT NULL,
            sector_name  VARCHAR2(40),
            trade_date   DATE          NOT NULL,
            open_price   NUMBER(12,2),
            high_price   NUMBER(12,2),
            low_price    NUMBER(12,2),
            close_price  NUMBER(12,2),
            volume       NUMBER(16),
            trade_amount NUMBER(20),
            CONSTRAINT pk_sector_prices PRIMARY KEY (sector_code, trade_date)
        )""")
        conn.commit()
        print('✅ SECTOR_PRICES 테이블 생성')
    cur.close()


def save_to_oracle(conn, sector_code, sector_name, rows):
    if not rows:
        return 0
    cur = conn.cursor()
    cnt = 0
    for r in rows:
        try:
            cur.execute("""MERGE INTO sector_prices t
                USING (SELECT :code AS sector_code, :dt AS trade_date FROM dual) s
                ON (t.sector_code = s.sector_code AND t.trade_date = s.trade_date)
                WHEN NOT MATCHED THEN INSERT
                    (sector_code, sector_name, trade_date, open_price, high_price, low_price, close_price, volume, trade_amount)
                    VALUES (:code2, :nm, :dt2, :op, :hi, :lo, :cl, :vol, :amt)
                WHEN MATCHED THEN UPDATE SET
                    sector_name=:nm2, open_price=:op2, high_price=:hi2, low_price=:lo2,
                    close_price=:cl2, volume=:vol2, trade_amount=:amt2""",
                {
                    'code': sector_code, 'dt': r['date'],
                    'code2': sector_code, 'nm': sector_name, 'dt2': r['date'],
                    'op': r['open'], 'hi': r['high'], 'lo': r['low'],
                    'cl': r['close'], 'vol': r['volume'], 'amt': r.get('amount'),
                    'nm2': sector_name,
                    'op2': r['open'], 'hi2': r['high'], 'lo2': r['low'],
                    'cl2': r['close'], 'vol2': r['volume'], 'amt2': r.get('amount'),
                })
            cnt += 1
        except Exception as e:
            print(f'    ⚠ {sector_code}/{r["date"]}: {e}')
    conn.commit()
    cur.close()
    return cnt


def main():
    import argparse
    parser = argparse.ArgumentParser(description='SECTOR_PRICES 업종지수 수집')
    parser.add_argument('--days', type=int, default=30, help='최근 N 거래일 (기본: 30)')
    args = parser.parse_args()

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수 필요')
        sys.exit(1)

    print(f'=== 업종지수 수집 시작 ({args.days}일) ===')
    token = get_access_token()
    print('✅ 토큰 발급')

    # 날짜 범위
    today = date.today()
    date_from = (today - timedelta(days=int(args.days * 1.6))).strftime('%Y%m%d')
    date_to = today.strftime('%Y%m%d')

    conn = oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))
    print('✅ Oracle 연결')

    ensure_table(conn)

    total = 0
    for i, (code, name) in enumerate(SECTORS):
        rows, err = fetch_sector_daily(token, code, date_from, date_to)
        if err:
            print(f'  ❌ {code} {name}: {err}')
            continue
        saved = save_to_oracle(conn, code, name, rows)
        total += saved
        print(f'  [{i+1}/{len(SECTORS)}] {code} {name}: {len(rows)}건 → {saved}건 저장')
        time.sleep(CALL_DELAY)

    conn.close()
    print(f'\n=== 완료: 총 {total}건 저장 ===')


if __name__ == '__main__':
    main()
