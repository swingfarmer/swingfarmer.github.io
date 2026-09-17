"""
한국주식 재무 트래커 — OpenDART 데이터 수집 스크립트 v2
======================================================
수정: corp_code 매핑 추가 (corpCode.xml 다운로드)

사용법:
  (로컬) set DART_API_KEY=키값 && python scripts/fetch_dart.py
  (GitHub Actions) 자동 실행

환경변수:
  DART_API_KEY — OpenDART API 키 (필수)
"""

import os
import sys
import csv
import json
import time
import zipfile
import io
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from datetime import datetime, date

# --- 설정 ---
DART_API_KEY = os.environ.get('DART_API_KEY', '')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
STOCK_LIST = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
OUTPUT_FILE = os.path.join(ROOT_DIR, 'data', 'kospi200.json')
DART_BASE = 'https://opendart.fss.or.kr/api'

THIS_YEAR = date.today().year
if date.today().month <= 4:
    FISCAL_YEAR = str(THIS_YEAR - 2)
else:
    FISCAL_YEAR = str(THIS_YEAR - 1)
PREV_YEAR = str(int(FISCAL_YEAR) - 1)

CALL_DELAY = 0.2


def download_corp_codes():
    """OpenDART corpCode.xml -> stock_code:corp_code 매핑."""
    print('📥 기업 고유번호 목록 다운로드 중...')
    url = f'{DART_BASE}/corpCode.xml?crtfc_key={DART_API_KEY}'
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            zip_data = resp.read()
    except Exception as e:
        print(f'❌ corpCode.xml 다운로드 실패: {e}')
        sys.exit(1)

    mapping = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            with zf.open('CORPCODE.xml') as f:
                tree = ET.parse(f)
                root = tree.getroot()
                for corp in root.findall('list'):
                    corp_code = corp.findtext('corp_code', '').strip()
                    stock_code = corp.findtext('stock_code', '').strip()
                    if stock_code and corp_code:
                        mapping[stock_code] = corp_code
    except Exception as e:
        print(f'❌ corpCode.xml 파싱 실패: {e}')
        sys.exit(1)

    print(f'   ✓ {len(mapping)}개 기업 매핑 완료')
    return mapping


def api_call(endpoint, params):
    """OpenDART API 호출."""
    params['crtfc_key'] = DART_API_KEY
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    url = f'{DART_BASE}/{endpoint}.json?{query}'
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        time.sleep(CALL_DELAY)
        return data
    except Exception as e:
        print(f'    API 오류: {endpoint} -> {e}')
        return None


def load_stock_list():
    """종목 리스트 CSV 로드."""
    stocks = []
    with open(STOCK_LIST, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                stocks.append({
                    'code': parts[0].strip(),
                    'name': parts[1].strip(),
                    'sector': parts[2].strip()
                })
    return stocks


def fetch_financials(corp_code, year):
    """단일회사 주요계정 조회 (연간 연결)."""
    data = api_call('fnlttSinglAcnt', {
        'corp_code': corp_code,
        'bsns_year': year,
        'reprt_code': '11011',
        'fs_div': 'CFS'
    })
    if data and data.get('status') == '000':
        return data.get('list', [])

    # 연결 없으면 별도
    data = api_call('fnlttSinglAcnt', {
        'corp_code': corp_code,
        'bsns_year': year,
        'reprt_code': '11011',
        'fs_div': 'OFS'
    })
    if data and data.get('status') == '000':
        return data.get('list', [])

    if data:
        print(f'    응답: status={data.get("status")} msg={data.get("message","")}')
    return None


def parse_amount(s):
    """DART 금액 -> 억원."""
    if not s or s.strip() in ('', '-'):
        return None
    s = s.replace(',', '').replace(' ', '')
    try:
        return round(int(s) / 100_000_000)
    except (ValueError, TypeError):
        return None


def extract_account(items, *account_names):
    """계정명으로 당기 금액 추출."""
    for item in items:
        nm = item.get('account_nm', '').strip()
        for target in account_names:
            if nm == target:
                return parse_amount(item.get('thstrm_amount'))
    return None


def fetch_dividend_info(corp_code, year):
    """배당 -> 주당배당금(원)."""
    data = api_call('alotMatter', {
        'corp_code': corp_code,
        'bsns_year': year,
        'reprt_code': '11011'
    })
    if not data or data.get('status') != '000':
        return 0

    for item in data.get('list', []):
        se = item.get('se', '')
        if '주당' in se and '배당' in se:
            val = item.get('thstrm', '0')
            if val:
                val = str(val).replace(',', '').replace(' ', '').replace('-', '0')
                try:
                    return int(float(val))
                except:
                    pass
    return 0


def safe_pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return round(a / b * 100, 1)


def safe_yoy(cur, prev):
    if cur is None or prev is None:
        return None
    if prev == 0:
        return 999.9 if (cur and cur > 0) else None
    if cur < 0 and prev > 0:
        return -999
    return round((cur - prev) / abs(prev) * 100, 1)


def process_stock(stock, corp_code):
    code = stock['code']
    print(f'  처리 중: {stock["name"]} ({code}, dart:{corp_code})...', end='', flush=True)

    items_cur = fetch_financials(corp_code, FISCAL_YEAR)
    if not items_cur:
        print(' ✗')
        return None

    items_prev = fetch_financials(corp_code, PREV_YEAR)

    revenue = extract_account(items_cur, '매출액', '수익(매출액)', '영업수익', '보험료수익')
    op = extract_account(items_cur, '영업이익', '영업이익(손실)')
    ni = extract_account(items_cur, '당기순이익', '당기순이익(손실)')
    equity = extract_account(items_cur, '자본총계')
    assets = extract_account(items_cur, '자산총계')
    liabilities = extract_account(items_cur, '부채총계')

    revenue_prev = None
    op_prev = None
    if items_prev:
        revenue_prev = extract_account(items_prev, '매출액', '수익(매출액)', '영업수익', '보험료수익')
        op_prev = extract_account(items_prev, '영업이익', '영업이익(손실)')

    dividend = fetch_dividend_info(corp_code, FISCAL_YEAR)

    result = {
        'code': code,
        'name': stock['name'],
        'sector': stock['sector'],
        'revenue': revenue,
        'op': op,
        'ni': ni,
        'opm': safe_pct(op, revenue),
        'nim': safe_pct(ni, revenue),
        'roe': safe_pct(ni, equity),
        'roa': safe_pct(ni, assets),
        'debt_ratio': safe_pct(liabilities, equity),
        'equity': equity,
        'dividend': dividend or 0,
        'div_yield': 0,
        'revenue_yoy': safe_yoy(revenue, revenue_prev),
        'op_yoy': safe_yoy(op, op_prev)
    }

    print(' ✓')
    return result


def main():
    if not DART_API_KEY:
        print('❌ DART_API_KEY 환경변수가 없습니다.')
        print('   Windows: set DART_API_KEY=your_key')
        print('   GitHub Actions: Settings → Secrets → DART_API_KEY')
        sys.exit(1)

    print(f'📊 한국주식 재무 트래커 — 데이터 수집 v2')
    print(f'   사업연도: {FISCAL_YEAR} (비교: {PREV_YEAR})')
    print(f'   출력: {OUTPUT_FILE}')
    print()

    corp_map = download_corp_codes()

    stocks = load_stock_list()
    print(f'\n📋 종목 수: {len(stocks)}개\n')

    results = []
    errors = []
    skipped = []

    for i, stock in enumerate(stocks, 1):
        print(f'[{i}/{len(stocks)}]', end='')
        corp_code = corp_map.get(stock['code'])
        if not corp_code:
            print(f'  {stock["name"]} — corp_code 매핑 없음')
            skipped.append(stock['name'])
            continue

        result = process_stock(stock, corp_code)
        if result:
            results.append(result)
        else:
            errors.append(stock['name'])

    output = {
        'updated': date.today().isoformat(),
        'period': f'{FISCAL_YEAR}.12 (연간)',
        'source': 'OpenDART',
        'fiscal_year': FISCAL_YEAR,
        'stock_count': len(results),
        'stocks': results
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'\n{"="*50}')
    print(f'✅ 성공: {len(results)}종목')
    if errors:
        print(f'❌ 실패: {len(errors)}종목 — {", ".join(errors[:10])}{"..." if len(errors)>10 else ""}')
    if skipped:
        print(f'⏭️  스킵: {len(skipped)}종목 — {", ".join(skipped[:10])}{"..." if len(skipped)>10 else ""}')
    print(f'📁 저장: {OUTPUT_FILE}')


if __name__ == '__main__':
    main()
