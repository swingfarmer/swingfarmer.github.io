"""
한국주식 재무 트래커 — OpenDART 수집 v3
========================================
변경: 기간별 파일 분리 저장 + 분기 보고서 지원

사용법:
  python scripts/fetch_dart.py               → 최신 연간
  python scripts/fetch_dart.py --period q1    → 1분기
  python scripts/fetch_dart.py --period q2    → 반기(2분기)
  python scripts/fetch_dart.py --period q3    → 3분기
  python scripts/fetch_dart.py --period annual → 연간 (기본)
  python scripts/fetch_dart.py --year 2024    → 특정 연도

환경변수: DART_API_KEY
"""

import os, sys, csv, json, time, zipfile, io, argparse
import xml.etree.ElementTree as ET
import urllib.request
from datetime import date

DART_API_KEY = os.environ.get('DART_API_KEY', '')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
STOCK_LIST = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
DATA_DIR = os.path.join(ROOT_DIR, 'data', 'kr')
INDEX_FILE = os.path.join(DATA_DIR, 'index.json')
# 하위호환: 기존 kospi200.json도 최신으로 덮어쓰기
LEGACY_FILE = os.path.join(ROOT_DIR, 'data', 'kospi200.json')
DART_BASE = 'https://opendart.fss.or.kr/api'
CALL_DELAY = 0.2

# 보고서 코드
REPORT_CODES = {
    'annual': ('11011', '사업보고서'),
    'q1':     ('11014', '1분기보고서'),
    'q2':     ('11012', '반기보고서'),
    'q3':     ('11013', '3분기보고서'),
}

PERIOD_LABELS = {
    'annual': '연간',
    'q1': '1분기',
    'q2': '반기(2Q)',
    'q3': '3분기',
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--period', default='annual', choices=['annual','q1','q2','q3'])
    p.add_argument('--year', type=int, default=None)
    return p.parse_args()


def download_corp_codes():
    print('📥 기업 고유번호 다운로드...')
    url = f'{DART_BASE}/corpCode.xml?crtfc_key={DART_API_KEY}'
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as resp:
            zip_data = resp.read()
    except Exception as e:
        print(f'❌ 실패: {e}'); sys.exit(1)

    mapping = {}
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        with zf.open('CORPCODE.xml') as f:
            for corp in ET.parse(f).getroot().findall('list'):
                cc = corp.findtext('corp_code','').strip()
                sc = corp.findtext('stock_code','').strip()
                if sc and cc: mapping[sc] = cc
    print(f'   ✓ {len(mapping)}개 매핑')
    return mapping


def api_call(endpoint, params):
    params['crtfc_key'] = DART_API_KEY
    query = '&'.join(f'{k}={v}' for k,v in params.items())
    url = f'{DART_BASE}/{endpoint}.json?{query}'
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        time.sleep(CALL_DELAY)
        return data
    except Exception as e:
        return None


def load_stock_list():
    stocks = []
    with open(STOCK_LIST, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            parts = line.split(',')
            if len(parts) >= 3:
                stocks.append({'code':parts[0].strip(),'name':parts[1].strip(),'sector':parts[2].strip()})
    return stocks


def fetch_financials(corp_code, year, reprt_code):
    for fs_div in ['CFS', 'OFS']:
        data = api_call('fnlttSinglAcnt', {
            'corp_code': corp_code,
            'bsns_year': year,
            'reprt_code': reprt_code,
            'fs_div': fs_div
        })
        if data and data.get('status') == '000':
            return data.get('list', [])
    return None


def parse_amount(s):
    if not s or s.strip() in ('','-'): return None
    try: return round(int(s.replace(',','').replace(' ','')) / 100_000_000)
    except: return None


def extract_account(items, *names):
    for item in items:
        nm = item.get('account_nm','').strip()
        if nm in names:
            return parse_amount(item.get('thstrm_amount'))
    return None


def fetch_dividend(corp_code, year, reprt_code):
    data = api_call('alotMatter', {
        'corp_code': corp_code,
        'bsns_year': year,
        'reprt_code': reprt_code
    })
    if not data or data.get('status') != '000': return 0
    for item in data.get('list', []):
        se = item.get('se','')
        if '주당' in se and '배당' in se:
            val = str(item.get('thstrm','0')).replace(',','').replace(' ','').replace('-','0')
            try: return int(float(val))
            except: pass
    return 0


def safe_pct(a, b):
    if a is None or b is None or b == 0: return None
    return round(a / b * 100, 1)

def safe_yoy(cur, prev):
    if cur is None or prev is None: return None
    if prev == 0: return 999.9 if cur and cur > 0 else None
    if cur < 0 and prev > 0: return -999
    return round((cur - prev) / abs(prev) * 100, 1)


def process_stock(stock, corp_code, year, reprt_code):
    code = stock['code']
    print(f'  {stock["name"]} ({code})...', end='', flush=True)

    items = fetch_financials(corp_code, year, reprt_code)
    if not items:
        print(' ✗'); return None

    rev = extract_account(items, '매출액','수익(매출액)','영업수익','보험료수익')
    op  = extract_account(items, '영업이익','영업이익(손실)')
    ni  = extract_account(items, '당기순이익','당기순이익(손실)')
    eq  = extract_account(items, '자본총계')
    ast = extract_account(items, '자산총계')
    lib = extract_account(items, '부채총계')
    div = fetch_dividend(corp_code, year, reprt_code)

    print(' ✓')
    return {
        'code': code, 'name': stock['name'], 'sector': stock['sector'],
        'revenue': rev, 'op': op, 'ni': ni,
        'opm': safe_pct(op, rev), 'nim': safe_pct(ni, rev),
        'roe': safe_pct(ni, eq), 'roa': safe_pct(ni, ast),
        'debt_ratio': safe_pct(lib, eq), 'equity': eq,
        'dividend': div or 0, 'div_yield': 0,
    }


def load_period_data(filepath):
    """기존 기간 데이터 로드 (비교용)."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return {s['code']: s for s in json.load(f).get('stocks',[])}
        except: pass
    return {}


def add_comparisons(results, prev_q_data, prev_y_data):
    """전분기·전년 대비 추가."""
    for s in results:
        code = s['code']
        pq = prev_q_data.get(code, {})
        py = prev_y_data.get(code, {})

        # 전분기 대비 (QoQ)
        s['revenue_qoq'] = safe_yoy(s['revenue'], pq.get('revenue'))
        s['op_qoq'] = safe_yoy(s['op'], pq.get('op'))

        # 전년 동기 대비 (YoY)
        s['revenue_yoy'] = safe_yoy(s['revenue'], py.get('revenue'))
        s['op_yoy'] = safe_yoy(s['op'], py.get('op'))
    return results


def get_prev_period_key(year, period):
    """전분기 파일명."""
    seq = ['annual','q1','q2','q3']
    idx = seq.index(period)
    if idx == 0:  # annual → 전년 q3
        return f'{int(year)-1}-q3'
    else:
        prev = seq[idx-1]
        return f'{year}-{prev}'

def get_prev_year_key(year, period):
    """전년 동기 파일명."""
    return f'{int(year)-1}-{period}'


def update_index(data_dir):
    """data/kr/ 안의 JSON 파일 목록으로 index.json 갱신."""
    periods = []
    for fn in sorted(os.listdir(data_dir)):
        if fn.endswith('.json') and fn != 'index.json':
            stem = fn.replace('.json','')
            parts = stem.split('-')
            if len(parts) == 2:
                year, period = parts
                filepath = os.path.join(data_dir, fn)
                try:
                    with open(filepath,'r',encoding='utf-8') as f:
                        meta = json.load(f)
                    periods.append({
                        'file': fn,
                        'year': year,
                        'period': period,
                        'label': f'{year} {PERIOD_LABELS.get(period, period)}',
                        'updated': meta.get('updated',''),
                        'count': meta.get('stock_count', 0)
                    })
                except: pass

    with open(os.path.join(data_dir, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump({'periods': periods}, f, ensure_ascii=False, indent=2)
    print(f'📋 index.json 갱신: {len(periods)}개 기간')


def main():
    args = parse_args()

    if not DART_API_KEY:
        print('❌ DART_API_KEY 없음'); sys.exit(1)

    year = str(args.year) if args.year else None
    period = args.period
    reprt_code, reprt_name = REPORT_CODES[period]

    # 연도 자동 결정
    if not year:
        y = date.today().year
        m = date.today().month
        if period == 'annual':
            year = str(y-1) if m > 4 else str(y-2)
        elif period == 'q1':
            year = str(y) if m > 5 else str(y-1)
        elif period == 'q2':
            year = str(y) if m > 8 else str(y-1)
        elif period == 'q3':
            year = str(y) if m > 11 else str(y-1)

    file_key = f'{year}-{period}'
    out_file = os.path.join(DATA_DIR, f'{file_key}.json')

    print(f'📊 한국주식 재무 트래커 v3')
    print(f'   {year}년 {reprt_name} ({reprt_code})')
    print(f'   출력: {out_file}')
    print()

    corp_map = download_corp_codes()
    stocks = load_stock_list()
    print(f'\n📋 종목: {len(stocks)}개\n')

    results, errors, skipped = [], [], []
    for i, stock in enumerate(stocks, 1):
        print(f'[{i}/{len(stocks)}]', end='')
        cc = corp_map.get(stock['code'])
        if not cc:
            print(f'  {stock["name"]} — 매핑 없음')
            skipped.append(stock['name']); continue
        r = process_stock(stock, cc, year, reprt_code)
        if r: results.append(r)
        else: errors.append(stock['name'])

    # 비교 데이터 로드
    prev_q_key = get_prev_period_key(year, period)
    prev_y_key = get_prev_year_key(year, period)
    prev_q_file = os.path.join(DATA_DIR, f'{prev_q_key}.json')
    prev_y_file = os.path.join(DATA_DIR, f'{prev_y_key}.json')

    prev_q_data = load_period_data(prev_q_file)
    prev_y_data = load_period_data(prev_y_file)

    if prev_q_data:
        print(f'📈 전분기 비교: {prev_q_key} ({len(prev_q_data)}종목)')
    if prev_y_data:
        print(f'📈 전년동기 비교: {prev_y_key} ({len(prev_y_data)}종목)')

    results = add_comparisons(results, prev_q_data, prev_y_data)

    # 저장
    output = {
        'updated': date.today().isoformat(),
        'year': year,
        'period': period,
        'period_label': f'{year} {PERIOD_LABELS.get(period, period)}',
        'report_name': reprt_name,
        'source': 'OpenDART',
        'stock_count': len(results),
        'compare_qoq': prev_q_key if prev_q_data else None,
        'compare_yoy': prev_y_key if prev_y_data else None,
        'stocks': results
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 하위호환: 최신 데이터를 kospi200.json에도 복사
    os.makedirs(os.path.dirname(LEGACY_FILE), exist_ok=True)
    with open(LEGACY_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # index.json 갱신
    update_index(DATA_DIR)

    print(f'\n{"="*50}')
    print(f'✅ 성공: {len(results)}종목 → {out_file}')
    if errors: print(f'❌ 실패: {len(errors)} — {", ".join(errors[:10])}')
    if skipped: print(f'⏭️  스킵: {len(skipped)} — {", ".join(skipped[:10])}')


if __name__ == '__main__':
    main()
