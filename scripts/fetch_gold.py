#!/usr/bin/env python3
"""
금시세(GC=F) 수집 → Oracle DB 저장
===================================
yfinance GC=F (COMEX Gold Futures, $/oz)
→ GOLD_PRICES 테이블 (price_usd, price_krw_g, usd_krw)

사용법:
  python3 fetch_gold.py                    # 최근 5일 수집
  python3 fetch_gold.py --backfill         # 전체 히스토리 일괄 수집 (20년+)
  python3 fetch_gold.py --backfill 365     # 과거 365일
  python3 fetch_gold.py --update-krw       # 환율 있는 날 KRW/g 일괄 갱신
"""
import os, sys, argparse
from datetime import datetime, timedelta, timezone

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance 필요: pip install yfinance --break-system-packages")
    sys.exit(1)

import oracledb

KST = timezone(timedelta(hours=9))
OZ_TO_G = 31.1035  # 1 troy oz = 31.1035g

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

WALLET_DIR = os.path.expanduser('~/wallet')

def get_conn():
    return oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))


def fetch_gold_history(period='5d'):
    """yfinance에서 금 선물 히스토리 가져오기."""
    print(f"📊 금시세 수집 (GC=F, period={period})...")
    tk = yf.Ticker('GC=F')
    df = tk.history(period=period)
    if df.empty:
        print("  ❌ 데이터 없음")
        return []

    rows = []
    for idx, row in df.iterrows():
        dt = idx.date() if hasattr(idx, 'date') else idx
        close = round(float(row['Close']), 2) if row['Close'] else None
        if close and close > 100:  # 유효성 체크
            rows.append({'date': dt, 'price_usd': close})

    print(f"  → {len(rows)}일치 수집")
    return rows


def save_gold_prices(conn, rows):
    """Oracle GOLD_PRICES에 MERGE (upsert)."""
    cur = conn.cursor()
    inserted = 0
    updated = 0
    for r in rows:
        try:
            cur.execute("""MERGE INTO gold_prices t
                USING (SELECT :dt AS price_date FROM dual) s
                ON (t.price_date = s.price_date)
                WHEN NOT MATCHED THEN INSERT (price_date, price_usd, source)
                    VALUES (:dt2, :usd, :src)
                WHEN MATCHED THEN UPDATE SET price_usd = :usd2, source = :src2""",
                {
                    'dt': r['date'], 'dt2': r['date'],
                    'usd': r['price_usd'], 'usd2': r['price_usd'],
                    'src': 'yfinance', 'src2': 'yfinance',
                })
            # MERGE는 rowcount 구분 안 되지만 카운트용
            inserted += 1
        except Exception as e:
            print(f"    ⚠ {r['date']} 저장 실패: {e}")
    conn.commit()
    cur.close()
    print(f"  → {inserted}건 저장/갱신")
    return inserted


def update_krw_prices(conn):
    """EXCHANGE_RATES에 USD 환율이 있는 날에 대해 KRW/g 계산 갱신."""
    cur = conn.cursor()

    # 환율 있는데 KRW 미계산인 행 + 환율 변경된 행 모두 갱신
    cur.execute("""UPDATE gold_prices g SET
        usd_krw = (SELECT e.deal_bas_r FROM exchange_rates e
                   WHERE e.cur_unit = 'USD' AND e.rate_date = g.price_date),
        price_krw_g = ROUND(g.price_usd *
            (SELECT e.deal_bas_r FROM exchange_rates e
             WHERE e.cur_unit = 'USD' AND e.rate_date = g.price_date)
            / :oz, 0)
    WHERE EXISTS (SELECT 1 FROM exchange_rates e
                  WHERE e.cur_unit = 'USD' AND e.rate_date = g.price_date)
      AND (price_krw_g IS NULL
           OR usd_krw != (SELECT e.deal_bas_r FROM exchange_rates e
                          WHERE e.cur_unit = 'USD' AND e.rate_date = g.price_date))""",
        {'oz': OZ_TO_G})

    cnt = cur.rowcount
    conn.commit()
    cur.close()
    print(f"  → KRW/g 갱신: {cnt}건")
    return cnt


def main():
    parser = argparse.ArgumentParser(description='금시세(GC=F) 수집')
    parser.add_argument('--backfill', nargs='?', const='max', default=None,
                        help='과거 수집. 숫자=N일, 생략=전체(max)')
    parser.add_argument('--update-krw', action='store_true',
                        help='환율 기반 KRW/g 일괄 갱신만')
    args = parser.parse_args()

    now = datetime.now(KST)
    print(f"🥇 금시세 수집: {now.strftime('%Y-%m-%d %H:%M KST')}")

    conn = get_conn()

    if args.update_krw:
        update_krw_prices(conn)
        # 현황 출력
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM gold_prices")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM gold_prices WHERE price_krw_g IS NOT NULL")
        krw_cnt = cur.fetchone()[0]
        cur.execute("""SELECT TO_CHAR(MIN(price_date),'YYYY-MM-DD'),
                              TO_CHAR(MAX(price_date),'YYYY-MM-DD') FROM gold_prices""")
        mn, mx = cur.fetchone()
        cur.close()
        print(f"\n📊 현황: 총 {total}일, KRW변환 {krw_cnt}일, 범위 {mn} ~ {mx}")
        conn.close()
        return

    # 수집
    if args.backfill:
        if args.backfill == 'max':
            period = 'max'
        else:
            days = int(args.backfill)
            if days <= 30:
                period = f'{days}d'
            elif days <= 365:
                period = f'{days // 30}mo' if days >= 60 else f'{days}d'
            else:
                years = days // 365
                period = f'{years}y' if years <= 20 else 'max'
        print(f"  🔄 백필 모드: period={period}")
    else:
        period = '5d'

    rows = fetch_gold_history(period)
    if rows:
        save_gold_prices(conn, rows)
        # KRW/g 자동 갱신
        update_krw_prices(conn)

    # 현황 출력
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM gold_prices")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM gold_prices WHERE price_krw_g IS NOT NULL")
    krw_cnt = cur.fetchone()[0]
    cur.execute("""SELECT TO_CHAR(MIN(price_date),'YYYY-MM-DD'),
                          TO_CHAR(MAX(price_date),'YYYY-MM-DD') FROM gold_prices""")
    mn, mx = cur.fetchone()
    cur.close()
    print(f"\n📊 현황: 총 {total}일, KRW변환 {krw_cnt}일, 범위 {mn} ~ {mx}")

    conn.close()
    print("✅ 완료")


if __name__ == '__main__':
    main()
