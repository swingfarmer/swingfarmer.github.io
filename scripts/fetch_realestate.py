"""
부동산 실거래가 트래커 — 수집 스크립트
=====================================
국토교통부 실거래가 API로 아파트 매매·전월세 데이터 수집.
결과: data/realestate_trades.json

사용법:
  python scripts/fetch_realestate.py                  → 서울 25구 + 설정 지역, 최근 6개월
  python scripts/fetch_realestate.py --months 12       → 최근 12개월
  python scripts/fetch_realestate.py --regions 11560   → 영등포구만
  python scripts/fetch_realestate.py --type rent       → 전월세만

환경변수: DATA_GO_KR_KEY
"""

import os, sys, json, time, argparse
import xml.etree.ElementTree as ET
import urllib.request, urllib.parse
from datetime import date, timedelta

API_KEY = os.environ.get('DATA_GO_KR_KEY', '')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_FILE = os.path.join(ROOT_DIR, 'data', 'realestate_trades.json')
CALL_DELAY = 0.3

# 엔드포인트
ENDPOINTS = {
    'trade': 'http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev',
    'rent':  'http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent',
}

# 서울 25구 + 주요 수도권
SEOUL_GU = {
    '11110': '종로구', '11140': '중구',     '11170': '용산구',   '11200': '성동구',
    '11215': '광진구', '11230': '동대문구', '11260': '중랑구',   '11290': '성북구',
    '11305': '강북구', '11320': '도봉구',   '11350': '노원구',   '11380': '은평구',
    '11410': '서대문구','11440': '마포구',   '11470': '양천구',   '11500': '강서구',
    '11530': '구로구', '11545': '금천구',   '11560': '영등포구', '11590': '동작구',
    '11620': '관악구', '11650': '서초구',   '11680': '강남구',   '11710': '송파구',
    '11740': '강동구',
}
EXTRA_REGIONS = {
    '41450': '하남시',
    '41135': '성남분당구',
    '41131': '성남수정구',
}
ALL_REGIONS = {**SEOUL_GU, **EXTRA_REGIONS}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--months', type=int, default=6, help='최근 N개월 (기본 6)')
    p.add_argument('--regions', nargs='*', help='LAWD_CD (없으면 전체)')
    p.add_argument('--type', choices=['all', 'trade', 'rent'], default='all')
    return p.parse_args()


def get_months(n):
    """최근 N개월 YYYYMM 리스트."""
    today = date.today()
    months = []
    for i in range(n):
        d = today.replace(day=1) - timedelta(days=30 * i)
        ym = d.strftime('%Y%m')
        if ym not in months:
            months.append(ym)
    return sorted(months)


def api_call(endpoint, lawd_cd, deal_ymd):
    """API 호출 → XML 파싱 → 리스트."""
    params = {
        'serviceKey': API_KEY,
        'LAWD_CD': lawd_cd,
        'DEAL_YMD': deal_ymd,
        'pageNo': '1',
        'numOfRows': '9999',
    }
    url = endpoint + '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode('utf-8')
        time.sleep(CALL_DELAY)
        return data
    except Exception as e:
        print(f'  ❌ API 에러: {e}')
        time.sleep(CALL_DELAY)
        return None


def parse_trade_xml(xml_str, region_name):
    """매매 XML 파싱."""
    items = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter('item'):
            t = lambda tag: (item.findtext(tag) or '').strip()
            amount = t('dealAmount') or t('거래금액')
            if not amount:
                continue
            amount_clean = amount.replace(',', '').replace(' ', '')
            try:
                amount_int = int(amount_clean)
            except:
                continue

            items.append({
                'type': 'trade',
                'region': region_name,
                'dong': t('umdNm') or t('법정동') or t('umdNm'),
                'apt': t('aptNm') or t('아파트'),
                'area': float(t('excluUseAr') or t('전용면적') or '0'),
                'floor': t('floor') or t('층'),
                'amount': amount_int,  # 만원
                'year': t('dealYear') or t('년'),
                'month': t('dealMonth') or t('월'),
                'day': t('dealDay') or t('일'),
                'build_year': t('buildYear') or t('건축년도'),
                'buyer': t('buyerGbn') or t('매수자'),
                'seller': t('slerGbn') or t('매도자'),
                'cancel': t('cdealType') or t('해제여부'),
            })
    except ET.ParseError:
        pass
    return items


def parse_rent_xml(xml_str, region_name):
    """전월세 XML 파싱."""
    items = []
    try:
        root = ET.fromstring(xml_str)
        for item in root.iter('item'):
            t = lambda tag: (item.findtext(tag) or '').strip()
            deposit = t('deposit') or t('보증금액')
            if not deposit:
                continue
            deposit_clean = deposit.replace(',', '').replace(' ', '')
            try:
                dep_int = int(deposit_clean)
            except:
                continue

            monthly = t('monthlyRent') or t('월세금액') or '0'
            monthly_clean = monthly.replace(',', '').replace(' ', '')
            try:
                mon_int = int(monthly_clean)
            except:
                mon_int = 0

            items.append({
                'type': 'jeonse' if mon_int == 0 else 'wolse',
                'region': region_name,
                'dong': t('umdNm') or t('법정동'),
                'apt': t('aptNm') or t('아파트'),
                'area': float(t('excluUseAr') or t('전용면적') or '0'),
                'floor': t('floor') or t('층'),
                'deposit': dep_int,  # 만원
                'monthly': mon_int,   # 만원
                'year': t('dealYear') or t('년'),
                'month': t('dealMonth') or t('월'),
                'day': t('dealDay') or t('일'),
                'build_year': t('buildYear') or t('건축년도'),
                'contract': t('contractType') or t('계약구분'),
                'term': t('contractTerm') or t('계약기간'),
                'prev_deposit': t('preDeposit') or '',
                'prev_monthly': t('preMonthlyRent') or '',
            })
    except ET.ParseError:
        pass
    return items


def main():
    if not API_KEY:
        print('❌ DATA_GO_KR_KEY 환경변수 미설정')
        sys.exit(1)

    args = parse_args()
    months = get_months(args.months)
    regions = {k: ALL_REGIONS[k] for k in (args.regions or ALL_REGIONS.keys()) if k in ALL_REGIONS}

    if not regions:
        print('❌ 유효한 지역코드 없음')
        sys.exit(1)

    types = ['trade', 'rent'] if args.type == 'all' else [args.type]
    total_calls = len(regions) * len(months) * len(types)

    print(f'🏠 실거래가 수집')
    print(f'   지역: {len(regions)}개 | 기간: {months[0]}~{months[-1]} | 유형: {",".join(types)}')
    print(f'   예상 API 호출: {total_calls}건 (약 {total_calls * CALL_DELAY / 60:.1f}분)')

    all_items = []
    call_count = 0
    done = 0

    for lawd_cd, region_name in regions.items():
        for ym in months:
            for dtype in types:
                done += 1
                pct = done / total_calls * 100
                print(f'  [{done}/{total_calls} {pct:.0f}%] {region_name} {ym} {dtype}...', end='', flush=True)

                xml = api_call(ENDPOINTS[dtype], lawd_cd, ym)
                call_count += 1
                if not xml:
                    print(' ✕')
                    continue

                if dtype == 'trade':
                    items = parse_trade_xml(xml, region_name)
                else:
                    items = parse_rent_xml(xml, region_name)

                all_items.extend(items)
                print(f' {len(items)}건')

    # 취소 거래 제거
    trades = [i for i in all_items if i.get('cancel') != 'O']

    # 통계
    trade_items = [i for i in trades if i['type'] == 'trade']
    jeonse_items = [i for i in trades if i['type'] == 'jeonse']
    wolse_items = [i for i in trades if i['type'] == 'wolse']

    # 지역별 요약
    region_stats = {}
    for item in trade_items:
        r = item['region']
        if r not in region_stats:
            region_stats[r] = {'count': 0, 'amounts': []}
        region_stats[r]['count'] += 1
        region_stats[r]['amounts'].append(item['amount'])

    for r in region_stats:
        amts = region_stats[r]['amounts']
        region_stats[r]['avg'] = round(sum(amts) / len(amts)) if amts else 0
        region_stats[r]['median'] = sorted(amts)[len(amts) // 2] if amts else 0
        region_stats[r]['max'] = max(amts) if amts else 0
        region_stats[r]['min'] = min(amts) if amts else 0
        del region_stats[r]['amounts']

    # 인기 단지 Top
    apt_stats = {}
    for item in trade_items:
        key = f"{item['region']}|{item['apt']}"
        if key not in apt_stats:
            apt_stats[key] = {'region': item['region'], 'apt': item['apt'], 'count': 0, 'amounts': []}
        apt_stats[key]['count'] += 1
        apt_stats[key]['amounts'].append(item['amount'])

    top_apts = sorted(apt_stats.values(), key=lambda x: x['count'], reverse=True)[:30]
    for a in top_apts:
        amts = a['amounts']
        a['avg'] = round(sum(amts) / len(amts)) if amts else 0
        del a['amounts']

    # 저장
    output = {
        'updated': date.today().isoformat(),
        'period': {'from': months[0], 'to': months[-1]},
        'regions': {k: v for k, v in ALL_REGIONS.items() if k in regions},
        'stats': {
            'total': len(trades),
            'trade': len(trade_items),
            'jeonse': len(jeonse_items),
            'wolse': len(wolse_items),
            'api_calls': call_count,
        },
        'region_stats': region_stats,
        'top_apts': top_apts,
        'trades': trades,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024

    print(f'\n✅ 완료 — {OUTPUT_FILE} ({size_mb:.1f}MB)')
    print(f'   매매: {len(trade_items)} | 전세: {len(jeonse_items)} | 월세: {len(wolse_items)}')
    print(f'   API 호출: {call_count}건')
    if trade_items:
        print(f'   거래 Top 5 단지:')
        for a in top_apts[:5]:
            print(f'     {a["region"]} {a["apt"]}: {a["count"]}건 (평균 {a["avg"]:,}만원)')


if __name__ == '__main__':
    main()
