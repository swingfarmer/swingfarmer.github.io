#!/usr/bin/env python3
"""
한국수출입은행 Open API 수집 → Oracle DB 저장
==============================================
AP01: 환율 (매매기준율, 송금 등)
AP02: 대출금리
AP03: 국제금리

사용법:
  python3 fetch_exim.py                    # 오늘 수집
  python3 fetch_exim.py --backfill 365     # 과거 365일 역추적
  python3 fetch_exim.py --date 20260101    # 특정일 수집

도메인: oapi.koreaexim.go.kr (2026.4.30 이후 신규)
제한: 일 1,000회, 영업일 11시 업데이트, 비영업일 null
API 키: ~/.env_secrets → KOREAEXIM_API_KEY
"""
import os, sys, json, time, argparse
from datetime import datetime, timedelta, timezone
import urllib.request
import oracledb

KST = timezone(timedelta(hours=9))
BASE_URL = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"

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

API_KEY = os.environ.get('KOREAEXIM_API_KEY', '')
WALLET_DIR = os.path.expanduser('~/wallet')

def get_conn():
    return oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))

def fetch_api(data_type, search_date):
    """수출입은행 API 호출. result=1 성공, 그 외 실패/비영업일."""
    url = f"{BASE_URL}?authkey={API_KEY}&searchdate={search_date}&data={data_type}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode('utf-8')
        data = json.loads(raw)
        if not data:
            return None  # 비영업일 또는 데이터 없음
        # result 필드 체크 (첫 번째 항목에 있음)
        if isinstance(data, list) and len(data) > 0:
            r = data[0].get('result', 1)
            if r != 1:
                return None
        return data
    except Exception as e:
        print(f"  ⚠ API 호출 실패 ({data_type}, {search_date}): {e}")
        return None

def parse_num(val):
    """문자열 → float. 쉼표 제거."""
    if val is None or val == '': return None
    try:
        return float(str(val).replace(',', ''))
    except:
        return None

def save_exchange_rates(conn, rate_date_str, items):
    """AP01 환율 데이터 Oracle 저장."""
    cur = conn.cursor()
    dt = datetime.strptime(rate_date_str, '%Y%m%d').date()
    inserted = 0
    for item in items:
        cur_unit = item.get('cur_unit', '').strip()
        if not cur_unit: continue
        try:
            cur.execute("""MERGE INTO exchange_rates t
                USING (SELECT :dt AS rate_date, :cu AS cur_unit FROM dual) s
                ON (t.rate_date = s.rate_date AND t.cur_unit = s.cur_unit)
                WHEN NOT MATCHED THEN INSERT (rate_date, cur_unit, cur_nm, ttb, tts, deal_bas_r, bkpr,
                    yy_efee_r, ten_dd_efee_r, kftc_deal_bas_r, kftc_bkpr)
                VALUES (:dt2, :cu2, :nm, :ttb, :tts, :dbr, :bkpr, :yy, :ten, :kdbr, :kbkpr)
                WHEN MATCHED THEN UPDATE SET
                    cur_nm=:nm2, ttb=:ttb2, tts=:tts2, deal_bas_r=:dbr2, bkpr=:bkpr2,
                    yy_efee_r=:yy2, ten_dd_efee_r=:ten2, kftc_deal_bas_r=:kdbr2, kftc_bkpr=:kbkpr2""",
                {
                    'dt': dt, 'cu': cur_unit,
                    'dt2': dt, 'cu2': cur_unit,
                    'nm': item.get('cur_nm', ''), 'nm2': item.get('cur_nm', ''),
                    'ttb': parse_num(item.get('ttb')), 'ttb2': parse_num(item.get('ttb')),
                    'tts': parse_num(item.get('tts')), 'tts2': parse_num(item.get('tts')),
                    'dbr': parse_num(item.get('deal_bas_r')), 'dbr2': parse_num(item.get('deal_bas_r')),
                    'bkpr': parse_num(item.get('bkpr')), 'bkpr2': parse_num(item.get('bkpr')),
                    'yy': parse_num(item.get('yy_efee_r')), 'yy2': parse_num(item.get('yy_efee_r')),
                    'ten': parse_num(item.get('ten_dd_efee_r')), 'ten2': parse_num(item.get('ten_dd_efee_r')),
                    'kdbr': parse_num(item.get('kftc_deal_bas_r')), 'kdbr2': parse_num(item.get('kftc_deal_bas_r')),
                    'kbkpr': parse_num(item.get('kftc_bkpr')), 'kbkpr2': parse_num(item.get('kftc_bkpr')),
                })
            inserted += 1
        except Exception as e:
            print(f"    ⚠ {cur_unit} 저장 실패: {e}")
    conn.commit()
    cur.close()
    return inserted

def save_interest_rates(conn, rate_date_str, data_type, items):
    """AP02/AP03 금리 데이터 Oracle 저장."""
    cur = conn.cursor()
    dt = datetime.strptime(rate_date_str, '%Y%m%d').date()
    inserted = 0
    for item in items:
        # AP02: sfln_intrc(대출금리), AP03: int_r(국제금리)
        rate_val = parse_num(item.get('sfln_intrc') or item.get('int_r'))
        item_nm = item.get('sfln_nm') or item.get('int_r_nm') or ''
        # item_code: AP02에는 없음 → item_nm을 코드로 사용. AP03에도 별도 코드 없음
        item_code = item_nm[:20] if item_nm else f"item_{inserted}"
        try:
            cur.execute("""MERGE INTO interest_rates t
                USING (SELECT :dt AS rate_date, :dtype AS data_type, :code AS item_code FROM dual) s
                ON (t.rate_date = s.rate_date AND t.data_type = s.data_type AND t.item_code = s.item_code)
                WHEN NOT MATCHED THEN INSERT (rate_date, data_type, item_code, item_nm, rate)
                VALUES (:dt2, :dtype2, :code2, :nm, :rate)
                WHEN MATCHED THEN UPDATE SET item_nm=:nm2, rate=:rate2""",
                {
                    'dt': dt, 'dtype': data_type, 'code': item_code,
                    'dt2': dt, 'dtype2': data_type, 'code2': item_code,
                    'nm': item_nm, 'nm2': item_nm,
                    'rate': rate_val, 'rate2': rate_val,
                })
            inserted += 1
        except Exception as e:
            print(f"    ⚠ {item_nm} 저장 실패: {e}")
    conn.commit()
    cur.close()
    return inserted

def collect_date(conn, date_str, verbose=True):
    """특정 날짜 AP01+AP02+AP03 수집."""
    total = 0
    api_calls = 0

    # AP01 환율
    data = fetch_api('AP01', date_str)
    api_calls += 1
    if data:
        cnt = save_exchange_rates(conn, date_str, data)
        total += cnt
        if verbose: print(f"  AP01 환율: {cnt}건")
    else:
        if verbose: print(f"  AP01 환율: 데이터 없음 (비영업일?)")

    time.sleep(0.3)

    # AP02 대출금리
    data = fetch_api('AP02', date_str)
    api_calls += 1
    if data:
        cnt = save_interest_rates(conn, date_str, 'AP02', data)
        total += cnt
        if verbose: print(f"  AP02 대출금리: {cnt}건")
    else:
        if verbose: print(f"  AP02 대출금리: 데이터 없음")

    time.sleep(0.3)

    # AP03 국제금리
    data = fetch_api('AP03', date_str)
    api_calls += 1
    if data:
        cnt = save_interest_rates(conn, date_str, 'AP03', data)
        total += cnt
        if verbose: print(f"  AP03 국제금리: {cnt}건")
    else:
        if verbose: print(f"  AP03 국제금리: 데이터 없음")

    return total, api_calls

def main():
    parser = argparse.ArgumentParser(description='수출입은행 API 수집')
    parser.add_argument('--date', help='특정 날짜 수집 (YYYYMMDD)')
    parser.add_argument('--backfill', type=int, help='과거 N일 역추적')
    parser.add_argument('--dry', action='store_true', help='API만 호출, DB 저장 안 함')
    args = parser.parse_args()

    if not API_KEY:
        print("❌ KOREAEXIM_API_KEY가 설정되지 않았습니다. ~/.env_secrets 확인")
        sys.exit(1)

    now = datetime.now(KST)
    print(f"📊 수출입은행 API 수집 시작: {now.strftime('%Y-%m-%d %H:%M KST')}")

    conn = get_conn()
    total_records = 0
    total_api_calls = 0

    if args.date:
        # 특정 날짜
        print(f"\n📅 {args.date}")
        cnt, calls = collect_date(conn, args.date)
        total_records += cnt
        total_api_calls += calls

    elif args.backfill:
        # 과거 역추적
        days = args.backfill
        print(f"\n🔄 과거 {days}일 백필 시작...")

        # DB에 이미 있는 날짜 조회 (스킵용)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT TO_CHAR(rate_date, 'YYYYMMDD') FROM exchange_rates")
        existing_dates = {r[0] for r in cur.fetchall()}
        cur.close()
        print(f"  DB에 이미 {len(existing_dates)}일 존재")

        skipped = 0
        collected = 0
        no_data = 0

        for i in range(days):
            dt = now - timedelta(days=i)
            date_str = dt.strftime('%Y%m%d')

            # 토/일 스킵 (API 호출 절약)
            if dt.weekday() >= 5:
                skipped += 1
                continue

            # 이미 수집된 날짜 스킵
            if date_str in existing_dates:
                skipped += 1
                continue

            # 일 1,000회 제한 체크 (날짜당 3회 호출)
            if total_api_calls + 3 > 990:
                print(f"\n⚠ API 호출 제한 근접 ({total_api_calls}회). 중단합니다.")
                print(f"  다음 실행 시 --backfill으로 이어서 수집하세요.")
                break

            print(f"📅 {date_str} ({i+1}/{days})", end=" → ")
            cnt, calls = collect_date(conn, date_str, verbose=False)
            total_records += cnt
            total_api_calls += calls

            if cnt > 0:
                collected += 1
                print(f"{cnt}건 저장")
            else:
                no_data += 1
                print("데이터 없음")

            time.sleep(0.5)  # API 속도 조절

        print(f"\n📊 백필 결과: 수집 {collected}일, 데이터없음 {no_data}일, 스킵 {skipped}일")

    else:
        # 오늘 수집
        date_str = now.strftime('%Y%m%d')
        print(f"\n📅 오늘: {date_str}")
        cnt, calls = collect_date(conn, date_str)
        total_records += cnt
        total_api_calls += calls

    conn.close()
    print(f"\n✅ 완료: {total_records}건 저장, API {total_api_calls}회 호출")

if __name__ == '__main__':
    main()
