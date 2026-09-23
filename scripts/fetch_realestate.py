"""
부동산 실거래가 트래커 — 수집 스크립트 v3 (메모리 최적화)
=======================================================
연도별로 수집 → 즉시 파일 저장 → 메모리 해제. OOM 방지.

사용법:
  python3 -u scripts/fetch_realestate.py              → 전체 (Tier1 20년 + Tier2 3년)
  python3 -u scripts/fetch_realestate.py --months 2    → 최근 2개월 갱신
  python3 -u scripts/fetch_realestate.py --year 2024   → 특정 연도만

환경변수: DATA_GO_KR_KEY
"""

import os, sys, json, time, argparse
import xml.etree.ElementTree as ET
import urllib.request, urllib.parse
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
    return p.parse_args()


def get_year_months(year):
    today = date.today()
    return [f'{year}{m:02d}' for m in range(1,13) if int(f'{year}{m:02d}') <= int(today.strftime('%Y%m'))]


def api_call(endpoint, lawd_cd, deal_ymd):
    params = {'serviceKey': API_KEY, 'LAWD_CD': lawd_cd, 'DEAL_YMD': deal_ymd, 'pageNo':'1', 'numOfRows':'9999'}
    url = endpoint + '?' + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=20) as resp:
                data = resp.read().decode('utf-8')
            time.sleep(CALL_DELAY)
            return data
        except Exception as e:
            if attempt < 2:
                print(f' ⏳재시도({attempt+2}/3)...', end='', flush=True)
                time.sleep(2)
            else:
                print(f' ❌실패', end='', flush=True)
                time.sleep(CALL_DELAY)
                return None


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


def save_year(yr, items):
    """연도 데이터 즉시 저장."""
    trades = [i for i in items if i['T']=='S']
    jeonse = [i for i in items if i['T']=='J']
    wolse = [i for i in items if i['T']=='W']
    rs, top = calc_stats(items) if trades else ({}, [])

    data = {
        'year': int(yr),
        'stats': {'total':len(items),'trade':len(trades),'jeonse':len(jeonse),'wolse':len(wolse)},
        'region_stats': rs, 'top_apts': top, 'items': items,
    }
    fpath = os.path.join(OUTPUT_DIR, f'{yr}.json')
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    size = os.path.getsize(fpath) / 1024 / 1024
    return {'total':len(items),'trade':len(trades),'jeonse':len(jeonse),'wolse':len(wolse),'size_mb':round(size,1)}


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

    print(f'🏠 실거래가 수집 v3 (메모리 최적화)')
    print(f'   연도: {min(year_regions)}~{max(year_regions)} ({len(year_regions)}년)')
    print(f'   API 콜: {total_calls}건 | 예상: {total_calls*CALL_DELAY/60:.0f}분')
    print(f'   ✅ 연도별 즉시 저장 (OOM 방지)')
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

        items = []
        yr_done = 0

        for code, name in regs.items():
            for ym in months:
                for dtype in types:
                    yr_done += 1
                    global_done += 1
                    call_count += 1
                    gpct = global_done / total_calls * 100
                    print(f'  [{global_done}/{total_calls} {gpct:.0f}%] {name} {ym} {dtype}...', end='', flush=True)

                    xml = api_call(ENDPOINTS[dtype], code, ym)
                    if not xml:
                        print()
                        continue

                    if dtype == 'trade':
                        parsed = parse_trade(xml, name)
                    else:
                        parsed = parse_rent(xml, name)

                    items.extend(parsed)
                    print(f' {len(parsed)}건', flush=True)

        # ── 이 연도 즉시 저장 + 메모리 해제 ──
        if items:
            stats = save_year(yr, items)
            index_years[yr] = stats
            print(f'  💾 {yr}.json 저장: {stats["total"]:,}건 ({stats["size_mb"]}MB)')
        else:
            print(f'  ⚠️ {yr}년 데이터 없음')

        del items  # 메모리 해제
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
