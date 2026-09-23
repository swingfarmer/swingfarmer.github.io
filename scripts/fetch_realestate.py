"""
부동산 실거래가 트래커 — 수집 스크립트 v2
=========================================
국토교통부 실거래가 API. 연도별 JSON 분할 저장.

사용법:
  python scripts/fetch_realestate.py                → 전체 수집 (Tier1 20년 + Tier2 3년)
  python scripts/fetch_realestate.py --months 6     → 최근 6개월만 (갱신용)
  python scripts/fetch_realestate.py --year 2024    → 특정 연도만
  python scripts/fetch_realestate.py --tier1-only   → 핵심 13개 지역만

결과: data/realestate/YYYY.json (연도별)
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

# ── Tier 1: 핵심 지역 (20년치) ──
TIER1 = {
    '11500': '강서구',   '11470': '양천구',   '11560': '영등포구',
    '11590': '동작구',   '11650': '서초구',   '11680': '강남구',
    '11710': '송파구',   '11740': '강동구',   '11440': '마포구',
    '11170': '용산구',   '11200': '성동구',   '11215': '광진구',
    '41450': '하남시',
}
TIER1_YEARS = 20

# ── Tier 2: 나머지 (3년치) ──
TIER2 = {
    '11110': '종로구',   '11140': '중구',     '11230': '동대문구',
    '11260': '중랑구',   '11290': '성북구',   '11305': '강북구',
    '11320': '도봉구',   '11350': '노원구',   '11380': '은평구',
    '11410': '서대문구', '11530': '구로구',   '11545': '금천구',
    '11620': '관악구',
    '41135': '성남분당구','41131': '성남수정구',
    '28185': '인천연수구','28260': '인천서구',
}
TIER2_YEARS = 3

ALL_REGIONS = {**TIER1, **TIER2}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--months', type=int, help='최근 N개월만 (갱신용)')
    p.add_argument('--year', type=int, help='특정 연도만')
    p.add_argument('--tier1-only', action='store_true', help='Tier1(핵심 13개)만')
    p.add_argument('--type', choices=['all', 'trade', 'rent'], default='all')
    return p.parse_args()


def get_year_months(year):
    """해당 연도의 YYYYMM 리스트."""
    today = date.today()
    months = []
    for m in range(1, 13):
        ym = f'{year}{m:02d}'
        if int(ym) <= int(today.strftime('%Y%m')):
            months.append(ym)
    return months


def get_recent_months(n):
    """최근 N개월 YYYYMM."""
    today = date.today()
    months = []
    for i in range(n):
        d = today.replace(day=1) - timedelta(days=30 * i)
        ym = d.strftime('%Y%m')
        if ym not in months:
            months.append(ym)
    return sorted(months)


def api_call(endpoint, lawd_cd, deal_ymd):
    params = {
        'serviceKey': API_KEY,
        'LAWD_CD': lawd_cd,
        'DEAL_YMD': deal_ymd,
        'pageNo': '1',
        'numOfRows': '9999',
    }
    url = endpoint + '?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as resp:
            data = resp.read().decode('utf-8')
        time.sleep(CALL_DELAY)
        return data
    except Exception as e:
        time.sleep(CALL_DELAY)
        return None


def parse_trade_xml(xml_str, region_name):
    items = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter('item'):
            t = lambda tag: (item.findtext(tag) or '').strip()
            amt = (t('dealAmount') or t('거래금액') or '').replace(',', '').replace(' ', '')
            if not amt: continue
            try: amt_int = int(amt)
            except: continue
            items.append({
                'T': 'S',  # Sale
                'r': region_name,
                'd': t('umdNm') or t('법정동'),
                'n': t('aptNm') or t('아파트'),
                'a': float(t('excluUseAr') or t('전용면적') or '0'),
                'f': t('floor') or t('층'),
                'p': amt_int,
                'y': t('dealYear') or t('년'),
                'm': t('dealMonth') or t('월'),
                'dy': t('dealDay') or t('일'),
                'by': t('buildYear') or t('건축년도'),
                'c': t('cdealType') or t('해제여부'),
            })
    except: pass
    return items


def parse_rent_xml(xml_str, region_name):
    items = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter('item'):
            t = lambda tag: (item.findtext(tag) or '').strip()
            dep = (t('deposit') or t('보증금액') or '').replace(',', '').replace(' ', '')
            if not dep: continue
            try: dep_int = int(dep)
            except: continue
            mon = (t('monthlyRent') or t('월세금액') or '0').replace(',', '').replace(' ', '')
            try: mon_int = int(mon)
            except: mon_int = 0
            items.append({
                'T': 'J' if mon_int == 0 else 'W',
                'r': region_name,
                'd': t('umdNm') or t('법정동'),
                'n': t('aptNm') or t('아파트'),
                'a': float(t('excluUseAr') or t('전용면적') or '0'),
                'f': t('floor') or t('층'),
                'dp': dep_int,
                'mp': mon_int,
                'y': t('dealYear') or t('년'),
                'm': t('dealMonth') or t('월'),
                'dy': t('dealDay') or t('일'),
                'by': t('buildYear') or t('건축년도'),
            })
    except: pass
    return items


def calc_stats(items):
    """지역별·단지별 통계."""
    region_stats = {}
    apt_stats = {}
    trades = [i for i in items if i['T'] == 'S']
    for t in trades:
        r = t['r']
        if r not in region_stats:
            region_stats[r] = {'count': 0, 'amounts': []}
        region_stats[r]['count'] += 1
        region_stats[r]['amounts'].append(t['p'])
        key = f"{r}|{t['n']}"
        if key not in apt_stats:
            apt_stats[key] = {'r': r, 'n': t['n'], 'cnt': 0, 'amts': []}
        apt_stats[key]['cnt'] += 1
        apt_stats[key]['amts'].append(t['p'])

    for r in region_stats:
        a = region_stats[r]['amounts']
        region_stats[r] = {
            'count': len(a),
            'avg': round(sum(a)/len(a)) if a else 0,
            'med': sorted(a)[len(a)//2] if a else 0,
            'max': max(a) if a else 0,
            'min': min(a) if a else 0,
        }

    top = sorted(apt_stats.values(), key=lambda x: x['cnt'], reverse=True)[:20]
    for t in top:
        t['avg'] = round(sum(t['amts'])/len(t['amts'])) if t['amts'] else 0
        del t['amts']

    return region_stats, top


def main():
    if not API_KEY:
        print('❌ DATA_GO_KR_KEY 미설정'); sys.exit(1)

    args = parse_args()
    today = date.today()
    types = ['trade', 'rent'] if args.type == 'all' else [args.type]
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 수집 계획 수립 ──
    plans = []  # (lawd_cd, region_name, ym, dtype)

    if args.months:
        # 갱신 모드: 최근 N개월, 전 지역
        months = get_recent_months(args.months)
        regions = ALL_REGIONS if not args.tier1_only else TIER1
        for code, name in regions.items():
            for ym in months:
                for dt in types:
                    plans.append((code, name, ym, dt))
    elif args.year:
        months = get_year_months(args.year)
        regions = ALL_REGIONS if not args.tier1_only else TIER1
        for code, name in regions.items():
            for ym in months:
                for dt in types:
                    plans.append((code, name, ym, dt))
    else:
        # 전체 수집
        # Tier1: 20년
        t1_start = today.year - TIER1_YEARS
        for code, name in TIER1.items():
            for yr in range(t1_start, today.year + 1):
                for ym in get_year_months(yr):
                    for dt in types:
                        plans.append((code, name, ym, dt))
        # Tier2: 3년
        if not args.tier1_only:
            t2_start = today.year - TIER2_YEARS
            for code, name in TIER2.items():
                for yr in range(t2_start, today.year + 1):
                    for ym in get_year_months(yr):
                        for dt in types:
                            plans.append((code, name, ym, dt))

    total = len(plans)
    if total > 10000:
        print(f'⚠️ API 콜 {total}건 > 일일한도 10,000. --tier1-only 또는 --months 로 줄이세요')
        sys.exit(1)

    est_min = total * CALL_DELAY / 60
    print(f'🏠 실거래가 수집 v2')
    print(f'   Tier1({len(TIER1)}개): {TIER1_YEARS}년 | Tier2({len(TIER2)}개): {TIER2_YEARS}년')
    print(f'   API 콜: {total}건 | 예상: {est_min:.0f}분')

    # ── 수집 ──
    year_data = defaultdict(list)  # year → items
    call_count = 0

    for i, (code, name, ym, dtype) in enumerate(plans):
        yr = ym[:4]
        pct = (i + 1) / total * 100
        if (i + 1) % 50 == 0 or i == 0:
            print(f'  [{i+1}/{total} {pct:.0f}%] {name} {ym} {dtype}...')

        xml = api_call(ENDPOINTS[dtype], code, ym)
        call_count += 1
        if not xml:
            continue

        if dtype == 'trade':
            items = parse_trade_xml(xml, name)
        else:
            items = parse_rent_xml(xml, name)

        # 취소 거래 제거
        items = [it for it in items if it.get('c') != 'O']
        for it in items:
            it.pop('c', None)

        year_data[yr].extend(items)

    # ── 연도별 저장 ──
    index = {'updated': today.isoformat(), 'regions': ALL_REGIONS, 'years': {}}

    for yr in sorted(year_data.keys()):
        items = year_data[yr]
        trades = [i for i in items if i['T'] == 'S']
        jeonse = [i for i in items if i['T'] == 'J']
        wolse = [i for i in items if i['T'] == 'W']
        region_stats, top_apts = calc_stats(items)

        yr_data = {
            'year': int(yr),
            'stats': {'total': len(items), 'trade': len(trades), 'jeonse': len(jeonse), 'wolse': len(wolse)},
            'region_stats': region_stats,
            'top_apts': top_apts,
            'items': items,
        }

        fpath = os.path.join(OUTPUT_DIR, f'{yr}.json')
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(yr_data, f, ensure_ascii=False)
        size = os.path.getsize(fpath) / 1024 / 1024
        print(f'  📁 {yr}.json — {len(items):,}건 ({size:.1f}MB)')

        index['years'][yr] = {
            'total': len(items),
            'trade': len(trades),
            'jeonse': len(jeonse),
            'wolse': len(wolse),
            'size_mb': round(size, 1),
        }

    # 인덱스 저장
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    print(f'\n✅ 완료')
    print(f'   연도 파일: {len(year_data)}개 | API 콜: {call_count}')
    total_items = sum(len(v) for v in year_data.values())
    print(f'   총 건수: {total_items:,}')


if __name__ == '__main__':
    main()
