#!/usr/bin/env python3
"""
DAILY_PRICES 테이블 생성 (1회성)
================================
VM에서 실행: python3 ~/swingfarmer.github.io/scripts/create_daily_prices.py
"""
import os, oracledb

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

W = os.path.expanduser('~/wallet')
conn = oracledb.connect(user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD',''),
    dsn='db1007_medium', config_dir=W, wallet_location=W,
    wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD',''))
cur = conn.cursor()
print("=== DB 연결 성공 ===")

cur.execute("SELECT table_name FROM user_tables WHERE table_name='DAILY_PRICES'")
exists = cur.fetchone()

if exists:
    cur.execute("SELECT COUNT(*) FROM daily_prices")
    cnt = cur.fetchone()[0]
    cur.execute("""SELECT TO_CHAR(MIN(trade_date),'YYYY-MM-DD'),
                          TO_CHAR(MAX(trade_date),'YYYY-MM-DD'),
                          COUNT(DISTINCT stock_code)
                   FROM daily_prices""")
    mn, mx, stocks = cur.fetchone()
    print(f"DAILY_PRICES 이미 존재: {cnt}건, {stocks}종목, {mn} ~ {mx}")
else:
    print("[+] DAILY_PRICES 생성...")
    cur.execute("""CREATE TABLE daily_prices (
        stock_code  VARCHAR2(10)  NOT NULL,
        trade_date  DATE          NOT NULL,
        open_price  NUMBER,
        high_price  NUMBER,
        low_price   NUMBER,
        close_price NUMBER        NOT NULL,
        volume      NUMBER,
        CONSTRAINT pk_daily_prices PRIMARY KEY (stock_code, trade_date)
    )""")
    # 날짜 기준 조회용 인덱스
    cur.execute("CREATE INDEX idx_dp_date ON daily_prices(trade_date)")
    # 종목별 최신일 빠르게 찾기
    cur.execute("CREATE INDEX idx_dp_code_date ON daily_prices(stock_code, trade_date DESC)")
    conn.commit()
    print("  → DAILY_PRICES 생성 완료 (PK: stock_code+trade_date)")

cur.close()
conn.close()
print("✅ 완료")
