#!/usr/bin/env python3
"""
한국은행 ECOS Open API 금리 수집 → Oracle DB 저장
==================================================
기준금리, 국고채(3/5/10년), CD(91일), 회사채(AA-) 등

사용법:
  python3 fetch_ecos.py                    # 최근 30일 수집
  python3 fetch_ecos.py --backfill 3650    # 과거 10년 역추적
  python3 fetch_ecos.py --from 20200101 --to 20201231  # 기간 지정

도메인: ecos.bok.or.kr/api/
제한: 일 100,000건 (넉넉)
API 키: ~/.env_secrets → ECOS_API_KEY
"""
import os, sys, json, time, argparse
from datetime import datetime, timedelta, timezone
import urllib.request
import ssl
import oracledb

KST = timezone(timedelta(hours=9))
BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# 수집 대상 금리 지표
INDICATORS = [
    # (통계표코드, 항목코드, 주기, 항목명)
    ('722Y001', '0101000', 'D', '한국은행 기준금리'),
    ('817Y002', '010101000', 'D', '콜금리(1일)'),
    ('817Y002', '010502000', 'D', 'CD(91일)'),
    ('817Y002', '010503000', 'D', 'CP(91일)'),
    ('817Y002', '010190000', 'D', '국고채(1년)'),
    ('817Y002', '010200000', 'D', '국고채(3년)'),
    ('817Y002', '010200001', 'D', '국고채(5년)'),
    ('817Y002', '010210000', 'D', '국고채(10년)'),
    ('817Y002', '010220000', 'D', '국고채(20년)'),
    ('817Y002', '010230000', 'D', '국고채(30년)'),
    ('817Y002', '010300000', 'D', '회사채(AA-,3년)'),
    ('817Y002', '010320000', 'D', '회사채(BBB-,3년)'),
    ('817Y002', '010504000', 'D', 'CMA(수시형)'),
]

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

API_KEY = os.environ.get('ECOS_API_KEY', '')
WALLET_DIR = os.path.expanduser('~/wallet')

def get_conn():
    return oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))

def fetch_ecos(stat_code, item_code, cycle, start_date, end_date):
    """ECOS API 호출. 최대 100,000건/일."""
    # URL: /api/StatisticSearch/{key}/json/kr/1/1000/{stat_code}/{cycle}/{start}/{end}/{item_code1}
    url = f"{BASE_URL}/{API_KEY}/json/kr/1/10000/{stat_code}/{cycle}/{start_date}/{end_date}/{item_code}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            raw = resp.read().decode('utf-8')
        data = json.loads(raw)

        # 에러 체크
        if 'StatisticSearch' not in data:
            # RESULT 에러 메시지 확인
            if 'RESULT' in data:
                code = data['RESULT'].get('CODE', '')
                msg = data['RESULT'].get('MESSAGE', '')
                if code == 'INFO-200':
                    return []  # 데이터 없음 (정상)
                print(f"    ⚠ ECOS 오류: {code} - {msg}")
            return None

        rows = data['StatisticSearch'].get('row', [])
        return rows
    except Exception as e:
        print(f"  ⚠ ECOS 호출 실패: {e}")
        return None

def save_rates(conn, rows, item_nm_override=None):
    """ECOS 금리 데이터 Oracle INTEREST_RATES 테이블 저장."""
    cur = conn.cursor()
    inserted = 0
    for row in rows:
        time_str = row.get('TIME', '')
        val = row.get('DATA_VALUE', '')
        stat_code = row.get('STAT_CODE', '')
        item_code = row.get('ITEM_CODE1', '')
        item_nm = item_nm_override or row.get('ITEM_NAME1', '')
        unit = row.get('UNIT_NAME', '')

        if not time_str or not val or val == '-':
            continue

        try:
            rate = float(val)
        except:
            continue

        # 날짜 파싱 (YYYYMMDD for daily)
        try:
            dt = datetime.strptime(time_str, '%Y%m%d').date()
        except:
            try:
                dt = datetime.strptime(time_str, '%Y%m').date()
            except:
                continue

        # data_type: ECOS_{stat_code} 형태
        data_type = f"ECOS"
        # item_code: 통계표코드_항목코드 (유일성 보장)
        code_key = f"{stat_code}_{item_code}"[:20]

        try:
            cur.execute("""MERGE INTO interest_rates t
                USING (SELECT :dt AS rate_date, :dtype AS data_type, :code AS item_code FROM dual) s
                ON (t.rate_date = s.rate_date AND t.data_type = s.data_type AND t.item_code = s.item_code)
                WHEN NOT MATCHED THEN INSERT (rate_date, data_type, item_code, item_nm, rate)
                VALUES (:dt2, :dtype2, :code2, :nm, :rate)
                WHEN MATCHED THEN UPDATE SET item_nm=:nm2, rate=:rate2""",
                {
                    'dt': dt, 'dtype': data_type, 'code': code_key,
                    'dt2': dt, 'dtype2': data_type, 'code2': code_key,
                    'nm': item_nm[:80], 'nm2': item_nm[:80],
                    'rate': rate, 'rate2': rate,
                })
            inserted += 1
        except Exception as e:
            print(f"    ⚠ 저장 실패 ({time_str} {item_nm}): {e}")
    conn.commit()
    cur.close()
    return inserted

def main():
    parser = argparse.ArgumentParser(description='한국은행 ECOS 금리 수집')
    parser.add_argument('--backfill', type=int, help='과거 N일 역추적')
    parser.add_argument('--from', dest='date_from', help='시작일 (YYYYMMDD)')
    parser.add_argument('--to', dest='date_to', help='종료일 (YYYYMMDD)')
    args = parser.parse_args()

    if not API_KEY:
        print("❌ ECOS_API_KEY가 설정되지 않았습니다. ~/.env_secrets 확인")
        sys.exit(1)

    now = datetime.now(KST)
    print(f"📊 한국은행 ECOS 금리 수집 시작: {now.strftime('%Y-%m-%d %H:%M KST')}")

    # 기간 설정
    if args.date_from and args.date_to:
        start_date = args.date_from
        end_date = args.date_to
    elif args.backfill:
        start_dt = now - timedelta(days=args.backfill)
        start_date = start_dt.strftime('%Y%m%d')
        end_date = now.strftime('%Y%m%d')
    else:
        # 기본: 최근 30일
        start_dt = now - timedelta(days=30)
        start_date = start_dt.strftime('%Y%m%d')
        end_date = now.strftime('%Y%m%d')

    print(f"📅 기간: {start_date} ~ {end_date}")

    # ECOS는 한 번 호출에 최대 10,000건 반환 가능
    # 일별 데이터: 1년 ≈ 250건 × 9개 지표 = 2,250건/년
    # 10년 = 22,500건 → 지표별로 나눠서 호출하면 충분

    # 기간이 길면 2년 단위로 분할
    start_dt = datetime.strptime(start_date, '%Y%m%d')
    end_dt = datetime.strptime(end_date, '%Y%m%d')

    conn = get_conn()
    total_records = 0
    total_api_calls = 0

    for stat_code, item_code, cycle, item_nm in INDICATORS:
        print(f"\n📈 {item_nm} ({stat_code}/{item_code})")

        # 2년 단위 분할
        chunk_start = start_dt
        indicator_total = 0

        while chunk_start < end_dt:
            chunk_end = min(chunk_start + timedelta(days=730), end_dt)
            s = chunk_start.strftime('%Y%m%d')
            e = chunk_end.strftime('%Y%m%d')

            rows = fetch_ecos(stat_code, item_code, cycle, s, e)
            total_api_calls += 1

            if rows is None:
                print(f"  {s}~{e}: 호출 실패")
            elif len(rows) == 0:
                print(f"  {s}~{e}: 데이터 없음")
            else:
                cnt = save_rates(conn, rows, item_nm)
                indicator_total += cnt
                total_records += cnt
                print(f"  {s}~{e}: {cnt}건 저장")

            chunk_start = chunk_end + timedelta(days=1)
            time.sleep(0.3)

        print(f"  → 소계: {indicator_total}건")

    conn.close()
    print(f"\n✅ 완료: {total_records}건 저장, API {total_api_calls}회 호출")

if __name__ == '__main__':
    main()
