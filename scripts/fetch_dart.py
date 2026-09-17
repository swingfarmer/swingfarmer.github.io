"""
한국주식 재무 트래커 — OpenDART 데이터 수집 스크립트
====================================================
KOSPI 200 주요 종목의 재무제표 + 배당 데이터를 수집하여
data/kospi200.json 으로 출력.

사용법:
  (로컬) python scripts/fetch_dart.py
  (GitHub Actions) 자동 실행 → data/kospi200.json 커밋

환경변수:
  DART_API_KEY  — OpenDART API 키 (필수)
"""

import os
import sys
import csv
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, date

# ─── 설정 ───
DART_API_KEY = os.environ.get('DART_API_KEY', '')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
STOCK_LIST = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
OUTPUT_FILE = os.path.join(ROOT_DIR, 'data', 'kospi200.json')

# OpenDART API 베이스
DART_BASE = 'https://opendart.fss.or.kr/api'

# 올해, 작년 사업연도
THIS_YEAR = date.today().year
# 공시는 보통 3~4월에 나오므로, 1~4월이면 2년 전 데이터 사용
if date.today().month <= 4:
    FISCAL_YEAR = str(THIS_YEAR - 2)
else:
    FISCAL_YEAR = str(THIS_YEAR - 1)

PREV_YEAR = str(int(FISCAL_YEAR) - 1)

# API 호출 간격 (초) — rate limit 방지
CALL_DELAY = 0.15


def api_call(endpoint, params):
    """OpenDART API 호출. JSON 반환."""
    params['crtfc_key'] = DART_API_KEY
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    url = f'{DART_BASE}/{endpoint}?{query}'
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        time.sleep(CALL_DELAY)
        return data
    except Exception as e:
        print(f'  API 오류: {endpoint} → {e}')
        return None


def load_stock_list():
    """종목 리스트 CSV 로드."""
    stocks = []
    with open(STOCK_LIST, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].startswith('#'):
                continue
            code, name, sector = row[0].strip(), row[1].strip(), row[2].strip()
            stocks.append({'code': code, 'name': name, 'sector': sector})
    return stocks


def get_corp_code_map():
    """
    OpenDART의 고유번호(corp_code)를 종목코드(stock_code)에 매핑.
    corpCode.xml 다운로드 방식 대신, 개별 조회 API 사용.
    """
    # 기업개황 API로 corp_code를 가져오는 건 stock_code → corp_code 역방향이 안 됨.
    # 대신 fnlttSinglAcnt에서 직접 stock_code 사용 가능 (2024년부터).
    # 여기서는 corp_code가 필요한 API를 위해 기업개황을 먼저 시도.
    return {}


def fetch_financials(stock_code, year):
    """단일회사 주요계정 조회 (연간 연결)."""
    data = api_call('fnlttSinglAcnt', {
        'corp_code': '',       # stock_code 사용 시 비워두기
        'stock_code': stock_code,
        'bsns_year': year,
        'reprt_code': '11011', # 사업보고서 (연간)
        'fs_div': 'CFS'       # 연결재무제표
    })
    if not data or data.get('status') != '000':
        # 연결 실패 시 별도 재무제표 시도
        data = api_call('fnlttSinglAcnt', {
            'stock_code': stock_code,
            'bsns_year': year,
            'reprt_code': '11011',
            'fs_div': 'OFS'
        })
    if not data or data.get('status') != '000':
        return None
    return data.get('list', [])


def parse_amount(s):
    """DART 금액 문자열 → 억 단위 숫자."""
    if not s or s == '-':
        return None
    s = s.replace(',', '').replace(' ', '')
    try:
        # DART는 원 단위 → 억으로 환산
        return round(int(s) / 100_000_000)
    except (ValueError, TypeError):
        return None


def extract_account(items, account_nm):
    """계정명으로 금액 추출. 당기 데이터."""
    for item in items:
        if item.get('account_nm', '').strip() == account_nm:
            return parse_amount(item.get('thstrm_amount'))
    return None


def fetch_dividend(stock_code, year):
    """배당 정보 조회."""
    data = api_call('alotMatter', {
        'stock_code': stock_code,
        'bsns_year': year,
        'reprt_code': '11011'
    })
    if not data or data.get('status') != '000':
        return 0
    items = data.get('list', [])
    for item in items:
        # 보통주 현금배당
        se = item.get('se', '')
        if '현금' in se and '보통' in se.lower():
            try:
                return int(item.get('stock_end_dt', item.get('thstrm', '0')).replace(',', ''))
            except:
                pass
        # 주당 배당금 (원) — lwfr (전기) / thstrm (당기)
        if '주당' in item.get('se', '') and '배당' in item.get('se', ''):
            try:
                return int(str(item.get('thstrm', '0')).replace(',', ''))
            except:
                pass
    return 0


def safe_div(a, b):
    """안전 나눗셈."""
    if a is None or b is None or b == 0:
        return None
    return round(a / b * 100, 1)


def safe_yoy(cur, prev):
    """YoY 증감률."""
    if cur is None or prev is None or prev == 0:
        if cur is not None and prev is not None and prev == 0 and cur != 0:
            return 999.9  # 0 → 양수
        if cur is not None and cur < 0 and (prev is None or prev > 0):
            return -999  # 적자전환
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def process_stock(stock):
    """한 종목의 재무 데이터 추출."""
    code = stock['code']
    print(f'  처리 중: {stock["name"]} ({code})...')

    # 당기 재무제표
    items_cur = fetch_financials(code, FISCAL_YEAR)
    if not items_cur:
        print(f'    ✗ 재무제표 없음')
        return None

    # 전기 재무제표 (YoY 계산용)
    items_prev = fetch_financials(code, PREV_YEAR)

    # 계정 추출
    revenue = extract_account(items_cur, '매출액') or extract_account(items_cur, '수익(매출액)')
    op = extract_account(items_cur, '영업이익') or extract_account(items_cur, '영업이익(손실)')
    ni = extract_account(items_cur, '당기순이익') or extract_account(items_cur, '당기순이익(손실)')
    equity = extract_account(items_cur, '자본총계')
    assets = extract_account(items_cur, '자산총계')
    liabilities = extract_account(items_cur, '부채총계')

    # 전기 매출/영업이익
    revenue_prev = None
    op_prev = None
    if items_prev:
        revenue_prev = extract_account(items_prev, '매출액') or extract_account(items_prev, '수익(매출액)')
        op_prev = extract_account(items_prev, '영업이익') or extract_account(items_prev, '영업이익(손실)')

    # 배당
    dividend = fetch_dividend(code, FISCAL_YEAR)

    # 계산
    opm = safe_div(op, revenue) if revenue and revenue != 0 else None
    nim = safe_div(ni, revenue) if revenue and revenue != 0 else None
    roe = safe_div(ni, equity) if equity and equity != 0 else None
    roa = safe_div(ni, assets) if assets and assets != 0 else None
    debt_ratio = safe_div(liabilities, equity) if equity and equity != 0 else None
    revenue_yoy = safe_yoy(revenue, revenue_prev)
    op_yoy = safe_yoy(op, op_prev)

    return {
        'code': code,
        'name': stock['name'],
        'sector': stock['sector'],
        'revenue': revenue,
        'op': op,
        'ni': ni,
        'opm': opm,
        'nim': nim,
        'roe': roe,
        'roa': roa,
        'debt_ratio': debt_ratio,
        'equity': equity,
        'dividend': dividend,
        'div_yield': 0,  # 주가 연동 전에는 0
        'revenue_yoy': revenue_yoy,
        'op_yoy': op_yoy
    }


def main():
    if not DART_API_KEY:
        print('❌ DART_API_KEY 환경변수가 설정되지 않았습니다.')
        print('   로컬: set DART_API_KEY=your_key_here (Windows)')
        print('   Actions: Settings → Secrets → DART_API_KEY')
        sys.exit(1)

    print(f'📊 한국주식 재무 트래커 — 데이터 수집')
    print(f'   사업연도: {FISCAL_YEAR} / 비교: {PREV_YEAR}')
    print(f'   출력: {OUTPUT_FILE}')
    print()

    stocks = load_stock_list()
    print(f'📋 종목 수: {len(stocks)}개')
    print()

    results = []
    errors = []
    for i, stock in enumerate(stocks, 1):
        print(f'[{i}/{len(stocks)}]', end='')
        result = process_stock(stock)
        if result:
            results.append(result)
            print(f'    ✓ 완료')
        else:
            errors.append(stock['name'])

    # JSON 출력
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

    print()
    print(f'✅ 완료: {len(results)}종목 저장 → {OUTPUT_FILE}')
    if errors:
        print(f'⚠️  실패: {len(errors)}종목 — {", ".join(errors)}')


if __name__ == '__main__':
    main()
