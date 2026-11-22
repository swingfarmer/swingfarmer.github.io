"""
부동산 실거래가 트래커 — 수집 스크립트 v5 (Oracle DB 동기화)
==========================================================
구(region) 하나씩 수집 → 바로 Oracle DB 적재 → 메모리 해제 (122).
  (122) 예전 v4는 연도 전체를 메모리에 쌓은 뒤 한 번에 넣어서, 11월쯤엔 300MB를 넘겨
        1GB VM이 메모리 부족으로 굳었음(11/22 05:30). 지금은 구 하나치(수 MB)만 들고 있음.
  (122) 연도별 JSON(data/realestate/YYYY.json, 레포·사이트 어디서도 안 읽음)은 더 안 만듦.
        건수 요약 data/realestate_index.json(헬스체크가 봄)은 그대로.
  --months N 은 「최근 N개월이 걸친 연도」를 통째로 다시 받음(그해 1월~이번 달). 늦게 들어온 해제(계약 취소)까지
        매일 반영하려는 것 — 범위는 v4와 같음.

사용법:
  python3 -u scripts/fetch_realestate.py              → 전체 (Tier1 20년 + Tier2 3년)
  python3 -u scripts/fetch_realestate.py --months 2    → 최근 2개월 갱신
  python3 -u scripts/fetch_realestate.py --year 2024   → 특정 연도만
  python3 -u scripts/fetch_realestate.py --no-db       → JSON만 저장 (Oracle 적재 생략)

DB 반영 방식 (082 수정)
  구(region)·연도 단위로 "그 구의 모든 달 호출이 성공했을 때만" 기존 행을 지우고 다시 넣음.
  하나라도 실패한 구는 기존 DB 데이터를 그대로 둠 (예전: 연도 전체 삭제 → 실패한 구·월 데이터 유실).
  지우는 범위도 이번에 받은 거래유형만 (--type trade 면 매매만, 전월세는 유지).
  API 에러(한도 초과 등)는 HTTP 200으로 와도 실패로 처리 (scripts/re_api.py).

환경변수: DATA_GO_KR_KEY, ORACLE_DB_PASSWORD, ORACLE_WALLET_PASSWORD
"""

import os, sys, json, time, argparse
import xml.etree.ElementTree as ET
import urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from re_api import api_call as _api_call
from datetime import date, timedelta
from collections import defaultdict

API_KEY = os.environ.get('DATA_GO_KR_KEY', '')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(ROOT_DIR, 'data', 'realestate')
INDEX_FILE = os.path.join(ROOT_DIR, 'data', 'realestate_index.json')
CALL_DELAY = 0.3

ENDPOINTS = {
    'trade': 'http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev',
    'rent':  'http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent',
}

TIER1 = {
    '11500':'강서구','11470':'양천구','11560':'영등포구','11590':'동작구',
    '11650':'서초구','11680':'강남구','11710':'송파구','11740':'강동구',
    '11440':'마포구','11170':'용산구','11200':'성동구','11215':'광진구',
    '41450':'하남시',
}
TIER1_YEARS = 20

TIER2 = {
    '11110':'종로구','11140':'중구','11230':'동대문구','11260':'중랑구',
    '11290':'성북구','11305':'강북구','11320':'도봉구','11350':'노원구',
    '11380':'은평구','11410':'서대문구','11530':'구로구','11545':'금천구',
    '11620':'관악구',
    '41135':'성남분당구','41131':'성남수정구',
    '28185':'인천연수구','28260':'인천서구',
}
TIER2_YEARS = 3

ALL_REGIONS = {**TIER1, **TIER2}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--months', type=int, help='최근 N개월만 (갱신용)')
    p.add_argument('--year', type=int, help='특정 연도만')
    p.add_argument('--tier1-only', action='store_true')
    p.add_argument('--type', choices=['all','trade','rent'], default='all')
    p.add_argument('--no-db', action='store_true', help='Oracle DB 적재 생략')
    return p.parse_args()


# ══ Oracle DB 동기화 ══
WALLET_DIR = os.path.expanduser('~/wallet')

def get_oracle_conn():
    import oracledb
    return oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_tp', config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))


def sync_to_oracle(conn, yr, items, ok_regions, deal_types):
    """구·연도 단위 동기화: ok_regions(모든 달 성공한 구)만, deal_types(S/J/W)만 지우고 다시 넣음.
    (122) 접속(conn)은 부르는 쪽이 연도마다 한 번 열어 넘김. 구 하나씩 불러서 구마다 commit.
    반환: (삭제 건수, 적재 건수) — 실패하면 None"""
    if not ok_regions:
        return (0, 0)
    cur = conn.cursor()
    try:
        dt_ph = ','.join(f':dt{i}' for i in range(len(deal_types)))
        deleted = 0
        for rg in sorted(ok_regions):
            p = {'y': str(yr), 'rg': rg}
            p.update({f'dt{i}': d for i, d in enumerate(deal_types)})
            cur.execute(f"DELETE FROM real_estate WHERE prop_type='APT' AND deal_year=:y AND region=:rg AND deal_type IN ({dt_ph})", p)
            deleted += cur.rowcount
        items = [it for it in items if it.get('r') in ok_regions and it['T'] in deal_types]

        BATCH = 500
        inserted = 0
        for i in range(0, len(items), BATCH):
            batch = items[i:i+BATCH]
            rows = []
            for it in batch:
                t = it['T']
                rows.append({
                    'v_pt': 'APT', 'v_dt': t, 'v_rg': it.get('r',''),
                    'v_dg': it.get('d',''), 'v_nm': it.get('n',''),
                    'v_am': it.get('a', 0), 'v_fn': it.get('f',''),
                    'v_pr': it.get('p') if t == 'S' else None,
                    'v_dp': it.get('dp') if t != 'S' else None,
                    'v_mr': it.get('mp') if t == 'W' else None,
                    'v_yr': str(it.get('y','')), 'v_mo': str(it.get('m','')),
                    'v_dd': str(it.get('dy','')), 'v_by': str(it.get('by',''))
                })
            cur.executemany("""INSERT INTO real_estate
                (prop_type, deal_type, region, dong, name, area_m2, floor_no,
                 price, deposit, monthly_rent, deal_year, deal_month, deal_day, build_year)
                VALUES (:v_pt,:v_dt,:v_rg,:v_dg,:v_nm,:v_am,:v_fn,:v_pr,:v_dp,:v_mr,:v_yr,:v_mo,:v_dd,:v_by)""", rows)
            inserted += len(batch)

        conn.commit()   # 이 구의 지우기+넣기 한 번에 확정 (중간 실패 시 rollback)
        return (deleted, inserted)
    except Exception as e:
        conn.rollback()
        print(f'  ⚠️ Oracle 적재 실패(되돌림, 이 구는 DB 그대로): {e}')
        return None
    finally:
        cur.close()


def get_year_months(year):
    today = date.today()
    return [f'{year}{m:02d}' for m in range(1,13) if int(f'{year}{m:02d}') <= int(today.strftime('%Y%m'))]


def api_call(endpoint, lawd_cd, deal_ymd):
    """페이지별 XML 리스트 / 실패 시 None (scripts/re_api.py)"""
    return _api_call(endpoint, API_KEY, lawd_cd, deal_ymd)


def parse_trade(xml_str, rname):
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
            items.append({'T':'S','r':rname,'d':t('umdNm') or t('법정동'),'n':t('aptNm') or t('아파트'),
                'a':float(t('excluUseAr') or t('전용면적') or '0'),'f':t('floor') or t('층'),
                'p':amt_int,'y':t('dealYear') or t('년'),'m':t('dealMonth') or t('월'),
                'dy':t('dealDay') or t('일'),'by':t('buildYear') or t('건축년도')})
    except: pass
    return items


def parse_rent(xml_str, rname):
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
            items.append({'T':'J' if mon_int==0 else 'W','r':rname,'d':t('umdNm') or t('법정동'),
                'n':t('aptNm') or t('아파트'),'a':float(t('excluUseAr') or t('전용면적') or '0'),
                'f':t('floor') or t('층'),'dp':dep_int,'mp':mon_int,
                'y':t('dealYear') or t('년'),'m':t('dealMonth') or t('월'),
                'dy':t('dealDay') or t('일'),'by':t('buildYear') or t('건축년도')})
    except: pass
    return items


def calc_stats(items):
    region_stats = {}
    apt_stats = {}
    for t in (i for i in items if i['T']=='S'):
        r = t['r']
        if r not in region_stats: region_stats[r] = []
        region_stats[r].append(t['p'])
        k = f"{r}|{t['n']}"
        if k not in apt_stats: apt_stats[k] = {'r':r,'n':t['n'],'cnt':0,'amts':[]}
        apt_stats[k]['cnt'] += 1; apt_stats[k]['amts'].append(t['p'])

    rs = {}
    for r, a in region_stats.items():
        sa = sorted(a)
        rs[r] = {'count':len(a),'avg':round(sum(a)/len(a)),'med':sa[len(sa)//2],'max':max(a),'min':min(a)}

    top = sorted(apt_stats.values(), key=lambda x:x['cnt'], reverse=True)[:20]
    for t in top: t['avg']=round(sum(t['amts'])/len(t['amts'])); del t['amts']
    return rs, top


def count_types(cnt, items):
    """(122) 연도 건수 요약용 — 구마다 더함 (연도 JSON·통계 파일은 안 만듦)"""
    for i in items:
        cnt['total'] += 1
        cnt[{'S': 'trade', 'J': 'jeonse', 'W': 'wolse'}[i['T']]] += 1


def main():
    if not API_KEY:
        print('❌ DATA_GO_KR_KEY 미설정'); sys.exit(1)

    args = parse_args()
    today = date.today()
    types = ['trade','rent'] if args.type=='all' else [args.type]
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 연도별 수집 계획 ──
    year_regions = {}  # year → {code: name, ...}

    if args.months:
        months = []
        for i in range(args.months):
            d = today.replace(day=1) - timedelta(days=30*i)
            months.append(d.strftime('%Y%m'))
        months = sorted(set(months))
        regions = ALL_REGIONS
        for ym in months:
            yr = ym[:4]
            if yr not in year_regions: year_regions[yr] = {}
            year_regions[yr].update(regions)
    elif args.year:
        year_regions[str(args.year)] = ALL_REGIONS
    else:
        # Tier1: 20년
        for yr in range(today.year - TIER1_YEARS, today.year + 1):
            year_regions[str(yr)] = dict(TIER1)
        # Tier2: 3년
        for yr in range(today.year - TIER2_YEARS, today.year + 1):
            if str(yr) not in year_regions: year_regions[str(yr)] = {}
            year_regions[str(yr)].update(TIER2)

    total_calls = 0
    for yr, regs in year_regions.items():
        total_calls += len(regs) * len(get_year_months(int(yr))) * len(types)

    if total_calls > 10000:
        print(f'⚠️ API 콜 {total_calls} > 10,000. 옵션 줄이세요'); sys.exit(1)

    print(f'🏠 실거래가 수집 v5 (구마다 바로 DB 적재 — 메모리 최소)')
    print(f'   연도: {min(year_regions)}~{max(year_regions)} ({len(year_regions)}년)')
    print(f'   API 콜: {total_calls}건 | 예상: {total_calls*CALL_DELAY/60:.0f}분')
    print()

    index_years = {}
    call_count = 0
    global_done = 0

    for yr in sorted(year_regions.keys()):
        regs = year_regions[yr]
        months = get_year_months(int(yr))
        if not months:
            continue

        yr_calls = len(regs) * len(months) * len(types)
        print(f'━━━ {yr}년 ({len(regs)}개 지역, {len(months)}개월, {yr_calls}콜) ━━━')

        yr_done = 0
        failed = set()   # 한 달이라도 실패한 구 이름
        cnt = {'total': 0, 'trade': 0, 'jeonse': 0, 'wolse': 0}
        dts = (['S'] if 'trade' in types else []) + (['J', 'W'] if 'rent' in types else [])
        conn = None
        if not args.no_db:
            try:
                conn = get_oracle_conn()
            except Exception as e:
                print(f'  ⚠️ Oracle 접속 실패 — 이 연도 DB 그대로 둠: {e}')
        n_del = n_ins = n_ok = 0

        for code, name in regs.items():
            items = []   # (122) 이 구 것만 — 끝나면 DB에 넣고 버림
            for ym in months:
                for dtype in types:
                    yr_done += 1
                    global_done += 1
                    call_count += 1
                    gpct = global_done / total_calls * 100
                    print(f'  [{global_done}/{total_calls} {gpct:.0f}%] {name} {ym} {dtype}...', end='', flush=True)

                    pages = api_call(ENDPOINTS[dtype], code, ym)
                    if pages is None:
                        failed.add(name)
                        print()
                        continue

                    parsed = []
                    for xml in pages:
                        parsed.extend(parse_trade(xml, name) if dtype == 'trade' else parse_rent(xml, name))

                    items.extend(parsed)
                    print(f' {len(parsed)}건', flush=True)

            # ── 이 구 바로 DB 적재 (한 달이라도 실패한 구는 DB 그대로) + 메모리 해제 ──
            count_types(cnt, items)
            if conn is not None and name not in failed:
                r = sync_to_oracle(conn, yr, items, {name}, dts)
                if r is None:
                    failed.add(name)
                else:
                    n_del += r[0]; n_ins += r[1]; n_ok += 1
            del items

        if conn is not None:
            try: conn.close()
            except Exception: pass
            print(f'  🗄️ Oracle: {n_ok}개 구 {n_del:,}건 삭제 → {n_ins:,}건 적재')
        if cnt['total'] and not failed:
            index_years[yr] = dict(cnt)
            print(f'  📊 {yr}년 {cnt["total"]:,}건 (매매 {cnt["trade"]:,} · 전세 {cnt["jeonse"]:,} · 월세 {cnt["wolse"]:,})')
        if failed:
            print(f'  ⚠️ 실패한 구 {len(failed)}개 — DB 기존 데이터 유지: {", ".join(sorted(failed))}')
        if not cnt['total']:
            print(f'  ⚠️ {yr}년 데이터 없음')
        print()

    # ── 인덱스 저장 ──
    # 기존 인덱스 병합 (갱신 모드일 때)
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                old_idx = json.load(f)
            for k, v in old_idx.get('years', {}).items():
                if k not in index_years:
                    index_years[k] = v
        except: pass

    index = {'updated': today.isoformat(), 'regions': ALL_REGIONS, 'years': index_years}
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    total_items = sum(v['total'] for v in index_years.values())
    print(f'✅ 완료 — {len(index_years)}개 연도, {total_items:,}건, API {call_count}콜')


if __name__ == '__main__':
    main()
