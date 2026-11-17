#!/usr/bin/env python3
"""
오피스텔·상업업무용 실거래가 수집 → Oracle DB 직접 저장
=====================================================
※ 082: 홈(~/fetch_offi_comm.py)에서 레포로 옮김. 크론은 레포 경로로 바꿀 것.

사용법:
  python3 -u scripts/fetch_offi_comm.py --check     → DB 중복 점검만 (API 호출 없음)
  python3 -u fetch_offi_comm.py                → 최근 3년 전체 수집
  python3 -u fetch_offi_comm.py --months 2     → 최근 2개월만
  python3 -u fetch_offi_comm.py --year 2025    → 특정 연도만
  python3 -u fetch_offi_comm.py --type offi    → 오피스텔만
  python3 -u fetch_offi_comm.py --type comm    → 상업업무용만

환경변수: DATA_GO_KR_KEY, ORACLE_DB_PASSWORD, ORACLE_WALLET_PASSWORD

DB 반영 방식 (082 수정)
  예전: INSERT만 → 같은 기간을 다시 돌릴 때마다 같은 거래가 한 벌씩 더 쌓임(중복).
  지금: 종류(오피스텔 매매 / 오피스텔 전월세 / 상업용 매매)·구·연도 단위로
        "그 구의 모든 달 호출이 성공했을 때만" 기존 행을 지우고 다시 넣음 → 몇 번 돌려도 중복 없음.
        실패한 구는 기존 데이터 유지. API 에러(한도 초과 등)는 실패로 처리 (scripts/re_api.py).
"""

import os, sys, time, argparse, subprocess
import xml.etree.ElementTree as ET
import urllib.request, urllib.parse
from datetime import date, timedelta
import oracledb
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from re_api import api_call as _api_call

# env_secrets 로드
result = subprocess.run(['bash','-c','source ~/.env_secrets && env'], capture_output=True, text=True)
for line in result.stdout.splitlines():
    if '=' in line:
        k,v = line.split('=',1)
        if k.startswith(('ORACLE_','DATA_GO')):
            os.environ[k] = v

API_KEY = os.environ.get('DATA_GO_KR_KEY', '')
CALL_DELAY = 0.3
BATCH_SIZE = 2000

# ── API 엔드포인트 ──
ENDPOINTS = {
    'offi_trade': 'http://apis.data.go.kr/1613000/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade',
    'offi_rent':  'http://apis.data.go.kr/1613000/RTMSDataSvcOffiRent/getRTMSDataSvcOffiRent',
    'comm_trade': 'http://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade',
}

# ── 지역 코드 ──
# 오피스텔: 아파트와 같은 주요 지역
OFFI_REGIONS = {
    '11500':'강서구','11470':'양천구','11560':'영등포구','11590':'동작구',
    '11650':'서초구','11680':'강남구','11710':'송파구','11740':'강동구',
    '11440':'마포구','11170':'용산구','11200':'성동구','11215':'광진구',
    '11110':'종로구','11140':'중구','11230':'동대문구','11260':'중랑구',
    '11290':'성북구','11305':'강북구','11320':'도봉구','11350':'노원구',
    '11380':'은평구','11410':'서대문구','11530':'구로구','11545':'금천구',
    '11620':'관악구',
}

# 상업업무용: 여의도만 (영등포구)
COMM_REGIONS = {
    '11560':'영등포구',
}

DEFAULT_YEARS = 3


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--months', type=int, help='최근 N개월만')
    p.add_argument('--year', type=int, help='특정 연도만')
    p.add_argument('--type', choices=['all','offi','comm'], default='all')
    p.add_argument('--check', action='store_true', help='DB 중복 점검만')
    return p.parse_args()


def get_year_months(year):
    today = date.today()
    return [f'{year}{m:02d}' for m in range(1,13)
            if int(f'{year}{m:02d}') <= int(today.strftime('%Y%m'))]


def api_call(endpoint, lawd_cd, deal_ymd):
    """페이지별 XML 리스트 / 실패 시 None"""
    return _api_call(endpoint, API_KEY, lawd_cd, deal_ymd)


def parse_offi_trade(xml_str, rname):
    items = []
    try:
        for item in ET.fromstring(xml_str).iter('item'):
            t = lambda tag: (item.findtext(tag) or '').strip()
            amt = (t('dealAmount') or t('거래금액') or '').replace(',','').replace(' ','')
            if not amt: continue
            try: amt_int = int(amt)
            except: continue
            cancel = t('cdealType') or t('해제여부')
            if cancel == 'O': continue
            items.append(('OFT','S', rname, t('umdNm') or t('법정동'),
                t('offiNm') or t('오피스텔') or t('aptNm') or '',
                float(t('excluUseAr') or t('전용면적') or '0'),
                str(t('floor') or t('층'))[:10],
                amt_int, None, None,
                t('dealYear') or t('년'), t('dealMonth') or t('월'),
                t('dealDay') or t('일'), str(t('buildYear') or t('건축년도'))[:10]))
    except: pass
    return items


def parse_offi_rent(xml_str, rname):
    items = []
    try:
        for item in ET.fromstring(xml_str).iter('item'):
            t = lambda tag: (item.findtext(tag) or '').strip()
            dep = (t('deposit') or t('보증금액') or '').replace(',','').replace(' ','')
            if not dep: continue
            try: dep_int = int(dep)
            except: continue
            mon = (t('monthlyRent') or t('월세금액') or '0').replace(',','').replace(' ','')
            try: mon_int = int(mon)
            except: mon_int = 0
            dtype = 'J' if mon_int == 0 else 'W'
            items.append(('OFT', dtype, rname, t('umdNm') or t('법정동'),
                t('offiNm') or t('오피스텔') or t('aptNm') or '',
                float(t('excluUseAr') or t('전용면적') or '0'),
                str(t('floor') or t('층'))[:10],
                None, dep_int, mon_int,
                t('dealYear') or t('년'), t('dealMonth') or t('월'),
                t('dealDay') or t('일'), str(t('buildYear') or t('건축년도'))[:10]))
    except: pass
    return items


def parse_comm_trade(xml_str, rname):
    items = []
    try:
        for item in ET.fromstring(xml_str).iter('item'):
            t = lambda tag: (item.findtext(tag) or '').strip()
            amt = (t('dealAmount') or t('거래금액') or '').replace(',','').replace(' ','')
            if not amt: continue
            try: amt_int = int(amt)
            except: continue
            cancel = t('cdealType') or t('해제여부')
            if cancel == 'O': continue
            items.append(('COM','S', rname, t('umdNm') or t('법정동'),
                t('buildNm') or t('건물명') or t('offiNm') or '',
                float(t('excluUseAr') or t('전용면적') or '0'),
                str(t('floor') or t('층'))[:10],
                amt_int, None, None,
                t('dealYear') or t('년'), t('dealMonth') or t('월'),
                t('dealDay') or t('일'), str(t('buildYear') or t('건축년도'))[:10]))
    except: pass
    return items


def get_conn():
    return oracledb.connect(
        user='ADMIN',
        password=os.environ['ORACLE_DB_PASSWORD'],
        dsn='db1007_medium',
        config_dir='/home/ubuntu/wallet',
        wallet_location='/home/ubuntu/wallet',
        wallet_password=os.environ['ORACLE_WALLET_PASSWORD']
    )


INSERT_SQL = """INSERT INTO real_estate
    (prop_type, deal_type, region, dong, name, area_m2, floor_no,
     price, deposit, monthly_rent, deal_year, deal_month, deal_day, build_year)
VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13,:14)"""


# (종류키) → (prop_type, 이번에 지우고 다시 넣을 deal_type들)
SCOPE = {'offi_trade': ('OFT', ['S']), 'offi_rent': ('OFT', ['J', 'W']), 'comm_trade': ('COM', ['S'])}

KEY_SQL = ("region||'|'||name||'|'||dong||'|'||area_m2||'|'||floor_no||'|'||NVL(price,-1)||'|'||"
           "NVL(deposit,-1)||'|'||NVL(monthly_rent,-1)||'|'||deal_year||'|'||deal_month||'|'||deal_day")


def check_dup():
    """유형·거래별 전체 행 수 vs 서로 다른 거래 수 (API 호출 없음)"""
    conn = get_conn(); cur = conn.cursor()
    print('유형 거래  전체행   서로다른거래  중복배수')
    cur.execute(f"""SELECT prop_type, deal_type, COUNT(*), COUNT(DISTINCT {KEY_SQL})
        FROM real_estate GROUP BY prop_type, deal_type ORDER BY prop_type, deal_type""")
    for pt, dt, n, d in cur.fetchall():
        print(f'{pt:4} {dt:2} {n:>10,} {d:>12,}  {n/d if d else 0:5.2f}배')
    print()
    print('OFT·COM 연도별')
    cur.execute(f"""SELECT prop_type, deal_year, COUNT(*), COUNT(DISTINCT {KEY_SQL})
        FROM real_estate WHERE prop_type IN ('OFT','COM')
        GROUP BY prop_type, deal_year ORDER BY prop_type, deal_year""")
    for pt, yr, n, d in cur.fetchall():
        print(f'{pt:4} {yr} {n:>10,} {d:>12,}  {n/d if d else 0:5.2f}배')
    cur.close(); conn.close()


def sync(cur, conn, ep_key, yr, rows, ok_regions):
    """ok_regions만, SCOPE의 deal_type만 지우고 다시 넣기. 한 트랜잭션."""
    pt, dts = SCOPE[ep_key]
    dt_ph = ','.join(f':dt{i}' for i in range(len(dts)))
    deleted = 0
    for rg in sorted(ok_regions):
        p = {'pt': pt, 'y': str(yr), 'rg': rg}
        p.update({f'dt{i}': d for i, d in enumerate(dts)})
        cur.execute(f"DELETE FROM real_estate WHERE prop_type=:pt AND deal_year=:y AND region=:rg AND deal_type IN ({dt_ph})", p)
        deleted += cur.rowcount
    rows = [r for r in rows if r[2] in ok_regions]
    for i in range(0, len(rows), BATCH_SIZE):
        cur.executemany(INSERT_SQL, rows[i:i+BATCH_SIZE])
    conn.commit()
    return deleted, len(rows)


def main():
    args = parse_args()
    if args.check:
        check_dup(); return
    if not API_KEY:
        print('❌ DATA_GO_KR_KEY 미설정'); sys.exit(1)

    today = date.today()

    # 수집 대상 결정
    tasks = []  # (endpoint_key, regions, parse_func, label)
    if args.type in ('all','offi'):
        tasks.append(('offi_trade', OFFI_REGIONS, parse_offi_trade, '오피스텔 매매'))
        tasks.append(('offi_rent', OFFI_REGIONS, parse_offi_rent, '오피스텔 전월세'))
    if args.type in ('all','comm'):
        tasks.append(('comm_trade', COMM_REGIONS, parse_comm_trade, '상업업무용 매매'))

    # 연도 계산
    if args.months:
        months_list = []
        for i in range(args.months):
            d = today.replace(day=1) - timedelta(days=30*i)
            months_list.append(d.strftime('%Y%m'))
        years = sorted(set(ym[:4] for ym in months_list))
    elif args.year:
        years = [str(args.year)]
    else:
        years = [str(y) for y in range(today.year - DEFAULT_YEARS, today.year + 1)]

    total_calls = 0
    for ep_key, regions, _, _ in tasks:
        for yr in years:
            total_calls += len(regions) * len(get_year_months(int(yr)))

    print(f'🏢 오피스텔·상업 실거래가 수집 → Oracle DB (구·연도 단위 교체)')
    print(f'   연도: {min(years)}~{max(years)} ({len(years)}년)')
    print(f'   API 콜: {total_calls}건 | 예상: {total_calls*CALL_DELAY/60:.0f}분+')
    print()

    conn = get_conn()
    cur = conn.cursor()
    global_done = 0
    tot_del = tot_ins = 0
    fail_total = 0

    for ep_key, regions, parse_func, label in tasks:
        print(f'━━━ {label} ━━━')
        for yr in years:
            months = get_year_months(int(yr))
            if not months: continue
            rows, failed = [], set()
            for code, name in regions.items():
                for ym in months:
                    global_done += 1
                    pct = global_done / total_calls * 100 if total_calls else 0
                    print(f'  [{global_done}/{total_calls} {pct:.0f}%] {name} {ym}...', end='', flush=True)
                    pages = api_call(ENDPOINTS[ep_key], code, ym)
                    if pages is None:
                        failed.add(name)
                        print()
                        continue
                    n0 = len(rows)
                    for xml in pages:
                        rows.extend(parse_func(xml, name))
                    print(f' {len(rows)-n0}건', flush=True)
            ok = set(regions.values()) - failed
            try:
                d, n = sync(cur, conn, ep_key, yr, rows, ok)
            except Exception as e:
                conn.rollback()
                print(f'  ⚠️ {yr} DB 반영 실패(되돌림): {e}')
                continue
            tot_del += d; tot_ins += n; fail_total += len(failed)
            msg = f'  💾 {yr}: {len(ok)}개 구 {d:,}건 삭제 → {n:,}건 적재'
            if failed:
                msg += f' / ⚠️ 실패 {len(failed)}개 구는 기존 유지: {", ".join(sorted(failed))}'
            print(msg)
        print()

    cur.execute("SELECT prop_type, deal_type, COUNT(*) FROM real_estate WHERE prop_type IN ('OFT','COM') GROUP BY prop_type, deal_type ORDER BY prop_type, deal_type")
    results = cur.fetchall()
    print(f'{"="*50}')
    print(f'✅ 완료: {tot_del:,}건 삭제 → {tot_ins:,}건 적재' + (f' / 실패 구·연도 {fail_total}개' if fail_total else ''))
    labels = {'S':'매매','J':'전세','W':'월세'}
    ptypes = {'OFT':'오피스텔','COM':'상업업무용'}
    for pt, dt, cnt in results:
        print(f'  {ptypes.get(pt,pt)} {labels.get(dt,dt)}: {cnt:,}건')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
