#!/usr/bin/env python3
"""
KOSPI·KOSDAQ 지수 백필 → DAILY_PRICES (1회성)
==============================================
yfinance ^KS11 / ^KQ11 → stock_code='KS11','KQ11'로 저장.
같은 DAILY_PRICES 테이블에 종목과 함께 보관.

사용법:
  python3 scripts/backfill_index.py                # 기본: 2026-07-01 ~ 오늘
  python3 scripts/backfill_index.py --start 2026-01-01
"""
import os, sys, argparse
from datetime import date, datetime

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

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance 필요: pip install yfinance --break-system-packages")
    sys.exit(1)

WALLET_DIR = os.path.expanduser('~/wallet')

INDEXES = [
    ('^KS11', 'KS11', 'KOSPI'),
    ('^KQ11', 'KQ11', 'KOSDAQ'),
]


def get_conn():
    return oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))


def fetch_index(ticker_symbol, start, end):
    """yfinance로 지수 일봉 가져오기."""
    tk = yf.Ticker(ticker_symbol)
    df = tk.history(start=start, end=end)
    if df.empty:
        return []
    rows = []
    for idx, row in df.iterrows():
        dt = idx.date() if hasattr(idx, 'date') else idx
        close = row.get('Close')
        if close and close > 0:
            rows.append({
                'date':   dt,
                'open':   round(float(row.get('Open', 0)), 2),
                'high':   round(float(row.get('High', 0)), 2),
                'low':    round(float(row.get('Low', 0)), 2),
                'close':  round(float(close), 2),
                'volume': int(row.get('Volume', 0)),
            })
    return rows


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
            print(f'  ⚠ {stock_code}/{r["date"]}: {e}')
    conn.commit()
    cur.close()
    return cnt


def main():
    parser = argparse.ArgumentParser(description='KOSPI·KOSDAQ 지수 백필')
    parser.add_argument('--start', default='2026-07-01', help='시작일 (기본: 2026-07-01)')
    args = parser.parse_args()

    today = date.today()
    # yfinance end는 exclusive라서 +1일
    end_str = (today.replace(day=today.day)).isoformat()

    print(f'📊 지수 백필: {args.start} ~ {today}')

    conn = get_conn()

    for yf_ticker, db_code, label in INDEXES:
        print(f'\n[{label}] {yf_ticker} → DB코드 {db_code}')
        rows = fetch_index(yf_ticker, args.start, end_str)
        print(f'  수집: {len(rows)}건')
        if rows:
            saved = save_to_oracle(conn, db_code, rows)
            print(f'  저장: {saved}건 ({rows[-1]["date"]} ~ {rows[0]["date"]})')

    # 현황
    cur = conn.cursor()
    for _, db_code, label in INDEXES:
        cur.execute("""SELECT COUNT(*), TO_CHAR(MIN(trade_date),'YYYY-MM-DD'),
                              TO_CHAR(MAX(trade_date),'YYYY-MM-DD')
                       FROM daily_prices WHERE stock_code=:code""", {'code': db_code})
        cnt, mn, mx = cur.fetchone()
        print(f'\n  {label}({db_code}): {cnt}일, {mn} ~ {mx}')
    cur.close()
    conn.close()
    print('\n✅ 완료')


if __name__ == '__main__':
    main()
