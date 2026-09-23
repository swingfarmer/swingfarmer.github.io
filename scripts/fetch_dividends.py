"""
배당 캘린더 데이터 수집
======================
OpenDART alotMatter API로 KOSPI+KOSDAQ 전 종목 배당 이력 수집.
결과: data/dividends.json

사용법:
  python scripts/fetch_dividends.py                → 최근 3년
  python scripts/fetch_dividends.py --years 5      → 최근 5년
  python scripts/fetch_dividends.py --year 2024    → 특정 연도만

환경변수: DART_API_KEY
"""

import os, sys, csv, json, time, zipfile, io, argparse
import xml.etree.ElementTree as ET
import urllib.request
from datetime import date

DART_API_KEY = os.environ.get('DART_API_KEY', '')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
KOSPI_LIST = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
KOSDAQ_LIST = os.path.join(SCRIPT_DIR, 'kosdaq_list.csv')
OUTPUT_FILE = os.path.join(ROOT_DIR, 'data', 'dividends.json')
DART_BASE = 'https://opendart.fss.or.kr/api'
CALL_DELAY = 0.2  # API 호출 간격 (초)

# alotMatter에서 추출할 항목
DIVIDEND_FIELDS = {
    '주당 현금배당금(원)': 'dps',           # Dividend Per Share
    '현금배당수익률(%)': 'yield',            # Dividend Yield
    '현금배당금총액(백만원)': 'total_div',   # Total Dividend Amount
    '현금배당성향(%)': 'payout',            # Payout Ratio
    '주당 주식배당(주)': 'stock_div',       # Stock Dividend
}

# 12월 결산 기준 배당 캘린더 (대부분 한국 상장사)
DIVIDEND_CALENDAR = {
    'annual': {
        'record_date': '12-31',   # 배당기준일
        'ex_date_approx': '12-28',  # 배당락 (기준일 2영업일 전, 근사)
        'payment_month': 4,       # 지급 예상월 (주총 후)
    },
    'interim': {
        'record_date': '06-30',
        'ex_date_approx': '06-27',
        'payment_month': 9,
    },
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--years', type=int, default=3, help='최근 N년 (기본 3)')
    p.add_argument('--year', type=int, help='특정 연도만')
    return p.parse_args()


def download_corp_codes():
    """DART 기업 고유번호 다운로드 → {종목코드: 고유번호} 매핑."""
    print('📥 기업 고유번호 다운로드...')
    url = f'{DART_BASE}/corpCode.xml?crtfc_key={DART_API_KEY}'
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=90) as resp:
            zip_data = resp.read()
    except Exception as e:
        print(f'❌ 실패: {e}'); sys.exit(1)

    mapping = {}
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        with zf.open('CORPCODE.xml') as f:
            for corp in ET.parse(f).getroot().findall('list'):
                cc = corp.findtext('corp_code', '').strip()
                sc = corp.findtext('stock_code', '').strip()
                if sc and cc:
                    mapping[sc] = cc
    print(f'   ✓ {len(mapping)}개 매핑')
    return mapping


def api_call(endpoint, params):
    """DART API 호출."""
    params['crtfc_key'] = DART_API_KEY
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    url = f'{DART_BASE}/{endpoint}.json?{query}'
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        time.sleep(CALL_DELAY)
        return data
    except Exception:
        time.sleep(CALL_DELAY)
        return None


def load_stock_list():
    """KOSPI + KOSDAQ 종목 리스트 로드."""
    stocks = []
    for fpath, market in [(KOSPI_LIST, 'KOSPI'), (KOSDAQ_LIST, 'KOSDAQ')]:
        if not os.path.exists(fpath):
            print(f'⚠️ {fpath} 없음 — {market} 건너뜀')
            continue
        with open(fpath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(',')
                if len(parts) >= 3:
                    stocks.append({
                        'code': parts[0].strip(),
                        'name': parts[1].strip(),
                        'sector': parts[2].strip(),
                        'market': market,
                    })
    return stocks


def parse_value(val_str):
    """DART 응답값 파싱 (콤마, 공백, - 처리)."""
    if not val_str:
        return None
    s = str(val_str).replace(',', '').replace(' ', '').strip()
    if s in ('', '-', '--', 'N/A', '해당없음'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_dividend_detail(corp_code, year, reprt_code):
    """alotMatter API → 배당 상세 데이터 추출."""
    data = api_call('alotMatter', {
        'corp_code': corp_code,
        'bsns_year': year,
        'reprt_code': reprt_code,
    })
    if not data or data.get('status') != '000':
        return None

    result = {'common': {}, 'preferred': {}}

    for item in data.get('list', []):
        se = item.get('se', '').strip()
        stock_knd = item.get('stock_knd', '').strip()

        # 당기(thstrm), 전기(frmtrm), 전전기(lwfr)
        val = parse_value(item.get('thstrm'))

        for keyword, field in DIVIDEND_FIELDS.items():
            if keyword in se:
                if '우선주' in stock_knd or '우선' in se:
                    result['preferred'][field] = val
                else:
                    result['common'][field] = val
                break

    # 보통주 DPS가 없으면 빈 결과
    if not result['common'].get('dps'):
        return None

    return result


def process_stock(stock, corp_code, years):
    """종목 1개의 N년치 배당 데이터 수집."""
    code = stock['code']
    name = stock['name']
    records = []

    for year in years:
        # 사업보고서 (연간 배당)
        div = fetch_dividend_detail(corp_code, str(year), '11011')
        if div:
            rec = {
                'year': year,
                'type': 'annual',
                'dps': div['common'].get('dps'),
                'yield': div['common'].get('yield'),
                'payout': div['common'].get('payout'),
                'total_div': div['common'].get('total_div'),
                'stock_div': div['common'].get('stock_div'),
                'pref_dps': div['preferred'].get('dps'),
            }
            records.append(rec)

        # 반기보고서 (중간배당 체크)
        div_h = fetch_dividend_detail(corp_code, str(year), '11012')
        if div_h:
            rec_h = {
                'year': year,
                'type': 'interim',
                'dps': div_h['common'].get('dps'),
                'yield': div_h['common'].get('yield'),
                'payout': div_h['common'].get('payout'),
                'total_div': div_h['common'].get('total_div'),
                'stock_div': div_h['common'].get('stock_div'),
                'pref_dps': div_h['preferred'].get('dps'),
            }
            records.append(rec_h)

    return records


def enrich_calendar(records, year_now):
    """배당 기록에 예상 캘린더 날짜 추가."""
    for rec in records:
        y = rec['year']
        dtype = rec['type']
        cal = DIVIDEND_CALENDAR.get(dtype, DIVIDEND_CALENDAR['annual'])

        rec['record_date'] = f"{y}-{cal['record_date']}"
        rec['ex_date_approx'] = f"{y}-{cal['ex_date_approx']}"

        # 지급월: 연간은 다음해, 중간은 같은해
        pay_year = y + 1 if dtype == 'annual' else y
        rec['payment_month'] = f"{pay_year}-{cal['payment_month']:02d}"
        rec['payment_approx'] = f"{pay_year}-{cal['payment_month']:02d}-15"


def main():
    if not DART_API_KEY:
        print('❌ DART_API_KEY 환경변수 미설정')
        sys.exit(1)

    args = parse_args()
    year_now = date.today().year

    if args.year:
        years = [args.year]
    else:
        years = list(range(year_now - args.years, year_now))

    print(f'📊 배당 데이터 수집 — {years[0]}~{years[-1]}')

    stocks = load_stock_list()
    if not stocks:
        print('❌ 종목 리스트 없음'); sys.exit(1)
    print(f'   종목 수: {len(stocks)}')

    corp_map = download_corp_codes()

    results = []
    api_calls = 0
    skip_count = 0

    for i, stock in enumerate(stocks):
        code = stock['code']
        corp_code = corp_map.get(code)
        if not corp_code:
            skip_count += 1
            continue

        pct = (i + 1) / len(stocks) * 100
        print(f'  [{i+1}/{len(stocks)} {pct:.0f}%] {stock["name"]}({code})...', end='', flush=True)

        records = process_stock(stock, corp_code, years)
        api_calls += len(years) * 2  # annual + interim per year

        if records:
            enrich_calendar(records, year_now)
            results.append({
                'code': code,
                'name': stock['name'],
                'sector': stock['sector'],
                'market': stock['market'],
                'dividends': records,
            })
            print(f' ✓ {len(records)}건')
        else:
            print(' (무배당)')

    # ── 통계 ──
    div_count = len(results)
    no_div = len(stocks) - div_count - skip_count

    # ── 배당수익률 Top 20 (최신 연간 기준) ──
    latest = []
    for r in results:
        annual = [d for d in r['dividends'] if d['type'] == 'annual']
        if annual:
            newest = max(annual, key=lambda x: x['year'])
            if newest.get('yield') and newest['yield'] > 0:
                latest.append({
                    'code': r['code'],
                    'name': r['name'],
                    'market': r['market'],
                    'year': newest['year'],
                    'dps': newest.get('dps', 0),
                    'yield': newest['yield'],
                    'payout': newest.get('payout'),
                })
    latest.sort(key=lambda x: x['yield'], reverse=True)

    # ── 월별 배당 캘린더 집계 ──
    calendar_summary = {}
    for r in results:
        for d in r['dividends']:
            pm = d.get('payment_month', '')
            if pm:
                if pm not in calendar_summary:
                    calendar_summary[pm] = []
                calendar_summary[pm].append({
                    'code': r['code'],
                    'name': r['name'],
                    'dps': d.get('dps', 0),
                    'type': d['type'],
                })

    # ── 저장 ──
    output = {
        'updated': date.today().isoformat(),
        'years': years,
        'stats': {
            'total_stocks': len(stocks),
            'dividend_stocks': div_count,
            'no_dividend': no_div,
            'skipped': skip_count,
            'api_calls': api_calls,
        },
        'top_yield': latest[:30],
        'calendar': calendar_summary,
        'stocks': results,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=1)

    print(f'\n✅ 완료 — {OUTPUT_FILE}')
    print(f'   배당 종목: {div_count}/{len(stocks)} | 무배당: {no_div} | 건너뜀: {skip_count}')
    print(f'   API 호출: ~{api_calls}건')
    print(f'   배당수익률 Top 5:')
    for r in latest[:5]:
        print(f'     {r["name"]}: {r["yield"]}% (DPS {r["dps"]:,.0f}원)')


if __name__ == '__main__':
    main()
