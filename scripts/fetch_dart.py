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
    'q1':     ('11013', '1분기보고서'),
    'q2':     ('11012', '반기보고서'),
    'q3':     ('11014', '3분기보고서'),
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
        with urllib.request.urlopen(urllib.request.Request(url), timeout=90) as resp:
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
        elif data:
            print(f' [{fs_div}:{data.get("status")}:{data.get("message","")}]', end='')
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


def fetch_full_accounts(corp_code, year, reprt_code):
    """전체 재무제표 항목 (fnlttSinglAcntAll) — 감가상각비, 현금 등 추출용."""
    for fs_div in ['CFS', 'OFS']:
        data = api_call('fnlttSinglAcntAll', {
            'corp_code': corp_code,
            'bsns_year': year,
            'reprt_code': reprt_code,
            'fs_div': fs_div
        })
        if data and data.get('status') == '000':
            lst = data.get('list', [])
            for it in lst: it.setdefault('_fs', fs_div)   # (104) 연결(CFS)인지 별도(OFS)인지
            return lst
    return []


def full_is_cfs(full_items):
    return bool(full_items) and full_items[0].get('_fs') == 'CFS'


def extract_da(full_items):
    """현금흐름표에서 감가상각비 추출 (억원)."""
    da_names = [
        '감가상각비', '감가상각비및무형자산상각비',
        '감가상각비 및 무형자산상각비',
        '유형자산감가상각비', '무형자산상각비',
        '유·무형자산상각비',
    ]
    # (104) 표준계정 ID도 봄 (이름이 달라도). 단 삼성전자·하이닉스처럼 현금흐름표에 상각비를 따로 안 적고 주석에만 둔 회사는 이 API로 못 구함
    da_ids = {'ifrs-full_AdjustmentsForDepreciationExpense', 'ifrs-full_AdjustmentsForAmortisationExpense',
              'ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense',
              'dart_AdjustmentsForDepreciationRightofuseAssets', 'dart_AdjustmentsForDepreciationLeasedAssets'}
    total_da = 0
    found = set()
    for item in full_items:
        if item.get('sj_div') == 'CF' and item.get('account_id', '').strip() in da_ids:
            amt = parse_amount(item.get('thstrm_amount'))
            nm = item.get('account_nm', '').strip().replace(' ', '')
            if amt is not None and nm not in found:
                total_da += abs(amt); found.add(nm)
    for item in full_items:
        sj = item.get('sj_div', '')  # BS/IS/CF 등
        nm = item.get('account_nm', '').strip().replace(' ', '')
        if sj != 'CF':
            continue
        for da_nm in da_names:
            if da_nm.replace(' ', '') in nm and nm not in found:
                amt = parse_amount(item.get('thstrm_amount'))
                if amt is not None:
                    total_da += abs(amt)  # 감가상각비는 양수로
                    found.add(nm)
                break
    return total_da if total_da > 0 else None


def extract_cash(full_items):
    """BS에서 현금 및 현금성자산 추출 (억원)."""
    cash_names = ['현금및현금성자산', '현금 및 현금성자산',
                  '현금및현금등가물', '현금및예치금']
    for item in full_items:
        if item.get('sj_div') != 'BS':
            continue
        nm = item.get('account_nm', '').strip()
        if nm in cash_names:
            return parse_amount(item.get('thstrm_amount'))
    return None


# (104) 차입금 — 표준계정 ID 우선, ID 없는 줄(-표준계정코드 미사용-, dart_)만 이름으로. 리스부채·합계 줄(Borrowings)은 뺌
DEBT_IDS = {
    'ifrs-full_ShorttermBorrowings', 'ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings',
    'ifrs-full_CurrentPortionOfLongtermBorrowings', 'ifrs-full_CurrentPortionOfNoncurrentBorrowings',
    'ifrs-full_LongtermBorrowings', 'ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived',
    'ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued', 'ifrs-full_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued',
    'ifrs-full_BondsIssued', 'ifrs-full_OtherBorrowings', 'ifrs-full_CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived',
    'ifrs-full_NoncurrentLoansReceived', 'ifrs-full_CurrentLoansReceived',
}
DEBT_NAMES = {'단기차입금', '유동성장기부채', '유동성장기차입금', '유동성사채', '사채', '장기차입금',
              '차입금', '단기사채', '장기사채', '유동차입금', '비유동차입금'}


def extract_short_debt(full_items):
    """BS 총차입금(단기·장기 차입금 + 사채, 유동성 포함) 억원. 이름은 옛 그대로(net_debt 계산용)."""
    total, hit = 0, False
    for item in full_items:
        if item.get('sj_div') != 'BS':
            continue
        aid = item.get('account_id', '').strip()
        nm = item.get('account_nm', '').strip().replace(' ', '')
        std = aid.startswith('ifrs-full_')
        if (std and aid in DEBT_IDS) or (not std and nm in DEBT_NAMES):
            amt = parse_amount(item.get('thstrm_amount'))
            if amt is not None:
                total += amt; hit = True
    return total if hit and total > 0 else None


def extract_ni_owner(full_items):
    """(104) 연결 손익계산서의 「지배기업 소유주 귀속 당기순이익」 (억원).
    법 기준 배당성향(조특법 104조의27 시행령) 분모. 연결이 없는 회사(OFS만)는 None → 페이지가 ni를 씀.
    1) 표준계정 ID 2) 이름(지배기업·지배주주·지배회사, 비지배·포괄 제외). IS 먼저, 없으면 CIS. 첫 번째 것(총포괄 귀속보다 앞에 나옴)."""
    if not full_items:
        return None
    for sj in ('IS', 'CIS'):
        rows = [it for it in full_items if it.get('sj_div') == sj]
        for it in rows:
            if it.get('account_id', '').strip() == 'ifrs-full_ProfitLossAttributableToOwnersOfParent':
                v = parse_amount(it.get('thstrm_amount'))
                if v is not None: return v
        for it in rows:
            nm = it.get('account_nm', '').replace(' ', '')
            if '비지배' in nm or '포괄' in nm: continue
            if '지배기업' in nm or '지배주주' in nm or '지배회사' in nm:   # 지배기업지분·지배기업소유주지분 등 (104_02 넓힘)
                v = parse_amount(it.get('thstrm_amount'))
                if v is not None: return v
    # (104) 연결인데 손익계산서에 비지배 줄이 아예 없으면 비지배지분이 없는 회사 → 지배 = 당기순이익
    is_rows = [it for it in full_items if it.get('sj_div') in ('IS', 'CIS')]
    if is_rows and not any('비지배' in it.get('account_nm', '') or 'NoncontrollingInterest' in it.get('account_id', '') for it in is_rows):
        for it in is_rows:
            if it.get('account_id', '').strip() == 'ifrs-full_ProfitLoss':
                v = parse_amount(it.get('thstrm_amount'))
                if v is not None: return v
    return None


def fetch_dividend(corp_code, year, reprt_code):
    """DART 배당 API (alotMatter) — 주당 배당금 + 현금배당총액 추출."""
    data = api_call('alotMatter', {
        'corp_code': corp_code,
        'bsns_year': year,
        'reprt_code': reprt_code
    })
    if not data or data.get('status') != '000': return 0, None, None
    dps = 0
    total_div_amt = None  # 백만원 → 억원 변환
    payout_rep = None     # (104) 회사가 공시한 (연결)현금배당성향 % — 검산용
    def num(item):
        v = str(item.get('thstrm', '')).replace(',', '').replace(' ', '')
        if v in ('', '-'): return None
        try: return float(v)
        except: return None
    for item in data.get('list', []):
        se = item.get('se','').replace(' ', '')
        stock_knd = item.get('stock_knd', '') or ''
        # DPS (보통주) — (104) 우선주·종류주 줄과 '-' 줄이 뒤에 와서 0으로 덮던 버그 수정: 보통주 줄 우선, 0으로 덮지 않음
        if '주당' in se and '현금배당' in se:
            if '우선' in stock_knd or '종류' in stock_knd: continue
            v = num(item)
            if v and v > 0 and (dps == 0 or '보통' in stock_knd): dps = int(v)
        # 현금배당금총액 (백만원)
        elif '현금배당금총액' in se:
            v = num(item)
            if v is not None: total_div_amt = round(v / 100)  # 백만원 → 억원
        # 현금배당성향(%) — 연결 우선, 없으면 별도
        elif '현금배당성향' in se:
            v = num(item)
            if v is not None and ('연결' in se or payout_rep is None): payout_rep = v
    return dps, total_div_amt, payout_rep


def fetch_buyback_cancel(corp_code, year, reprt_code):
    """DART 자기주식 취득/처분 현황 — 소각 수량 추출.
    총계 행만 사용 (대/중/소분류가 모두 '총계'인 행) → 중복 합산 방지.
    총계 행이 없으면 개별 행 합산 fallback.
    """
    data = api_call('tesstkAcqsDspsSttus', {
        'corp_code': corp_code,
        'bsns_year': year,
        'reprt_code': reprt_code
    })
    if not data or data.get('status') != '000': return 0

    total_from_summary = 0
    total_from_detail = 0
    found_summary = False

    for item in data.get('list', []):
        stock_knd = item.get('stock_knd', '')
        # 보통주만 (우선주 제외)
        if '우선' in stock_knd:
            continue

        cancel_str = str(item.get('change_qy_incnr', '0')).replace(',', '').replace(' ', '').replace('-', '0')
        try:
            cancel = int(float(cancel_str))
        except:
            cancel = 0

        if cancel <= 0:
            continue

        mth1 = item.get('acqs_mth1', '')
        mth3 = item.get('acqs_mth3', '')
        # 총계 행 확인
        if '총계' in mth1 or '총계' in mth3:
            total_from_summary += cancel
            found_summary = True
        else:
            total_from_detail += cancel

    return total_from_summary if found_summary else total_from_detail


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

    rev = extract_account(items,
        '매출액','수익(매출액)','영업수익',
        '이자수익','순이자이익',
        '보험수익','보험료수익',
        '순영업수익',
        '영업이익수익',
    )
    op  = extract_account(items,
        '영업이익','영업이익(손실)',
        '영업손익',
    )
    ni  = extract_account(items, '당기순이익','당기순이익(손실)',
        '당기순이익(손실)의 귀속 지배기업의 소유주에게 귀속되는 당기순이익(손실)',
    )
    eq  = extract_account(items, '자본총계')
    ast = extract_account(items, '자산총계')
    lib = extract_account(items, '부채총계')
    div, total_div_amt, payout_rep = fetch_dividend(corp_code, year, reprt_code)
    buyback_cancel_qty = fetch_buyback_cancel(corp_code, year, reprt_code)

    # 전체계정에서 EBITDA 관련 항목 추출
    full = fetch_full_accounts(corp_code, year, reprt_code)
    da = extract_da(full) if full else None
    cash = extract_cash(full) if full else None
    total_debt = extract_short_debt(full) if full else None
    ni_owner = extract_ni_owner(full) if full_is_cfs(full) else None

    ebitda = None
    if op is not None and da is not None:
        ebitda = op + da

    net_debt = None
    if total_debt is not None and cash is not None:
        net_debt = total_debt - cash

    # (104) 재무제표 통화 — 두산밥캣처럼 USD로 공시하는 회사는 금액이 달러(억 달러). 배당(alotMatter)은 원화
    cur = (items[0].get('currency') or 'KRW').strip() if items else 'KRW'

    print(' ✓' if cur == 'KRW' else f' ✓ ({cur})')
    rec = {
        'code': code, 'name': stock['name'], 'sector': stock['sector'],
        'revenue': rev, 'op': op, 'ni': ni,
        'ni_owner': ni_owner,  # (104) 지배기업 소유주 귀속 순이익 (억원, 연결 없으면 None)
        'opm': safe_pct(op, rev), 'nim': safe_pct(ni, rev),
        'roe': safe_pct(ni, eq), 'roa': safe_pct(ni, ast),
        'debt_ratio': safe_pct(lib, eq), 'equity': eq,
        'dividend': div or 0, 'div_yield': 0,
        'total_div_amt': total_div_amt,  # 현금배당총액 (억원)
        'payout_rep': payout_rep,  # (104) 회사 공시 (연결)현금배당성향 % — 연간 보고서에만 의미 있음
        'buyback_cancel_qty': buyback_cancel_qty or 0,  # 자사주 소각 수량 (주)
        'da': da, 'ebitda': ebitda, 'cash': cash,
        'total_debt': total_debt, 'net_debt': net_debt,
    }
    if cur != 'KRW': rec['currency'] = cur   # 원화면 칸 안 넣음
    return rec


def load_period_data(filepath):
    """기존 기간 데이터 로드 (비교용)."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return {s['code']: s for s in json.load(f).get('stocks',[])}
        except: pass
    return {}


def add_comparisons(results, prev_y_data):
    """전년 동기 대비(YoY) 추가. QoQ는 누적 분기라 의미 없어서 제거."""
    for s in results:
        code = s['code']
        py = prev_y_data.get(code, {})
        s['revenue_yoy'] = safe_yoy(s['revenue'], py.get('revenue'))
        s['op_yoy'] = safe_yoy(s['op'], py.get('op'))
    return results


PREV_Q = {'q2': 'q1', 'q3': 'q2'}

def quarterize_da(results, prev_q_data, period):
    """(108) 분기 D&A를 3개월치로. 현금흐름표 상각비는 연초부터 누적이고 영업이익은 3개월치라
    그냥 더하면 EBITDA가 부풀었음(LS ELECTRIC 3Q: 2,335 + 9개월 누적 1,088).
    da_ytd = 누적값(원천 그대로), da = 이번 누적 − 직전 분기 누적. 직전 분기 값이 없으면 da·ebitda 비움.
    1분기·연간은 누적 = 그 기간이라 그대로."""
    for s in results:
        ytd = s.get('da')
        s['da_ytd'] = ytd
        if period not in PREV_Q or ytd is None:
            continue
        p = prev_q_data.get(s['code'], {})
        pytd = p.get('da_ytd', p.get('da') if PREV_Q[period] == 'q1' else None)
        if pytd is None:
            s['da'] = None
        else:
            s['da'] = ytd - pytd
        s['ebitda'] = (s['op'] + s['da']) if (s.get('op') is not None and s['da'] is not None) else None
    return results


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
        # (104) > → >= : 크론이 제출기한 직후 그 달(4/5·5/20·8/20·11/20)에 도는데 >면 1년 전 것을 받았음
        if period == 'annual':
            year = str(y-1) if m >= 4 else str(y-2)
        elif period == 'q1':
            year = str(y) if m >= 5 else str(y-1)
        elif period == 'q2':
            year = str(y) if m >= 8 else str(y-1)
        elif period == 'q3':
            year = str(y) if m >= 11 else str(y-1)

    file_key = f'{year}-{period}'
    out_file = os.path.join(DATA_DIR, f'{file_key}.json')

    print(f'📊 한국주식 재무 트래커 v3 (104)')
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

    # YoY 비교 데이터 로드
    prev_y_key = get_prev_year_key(year, period)
    prev_y_file = os.path.join(DATA_DIR, f'{prev_y_key}.json')
    prev_y_data = load_period_data(prev_y_file)

    if prev_y_data:
        print(f'📈 전년동기 비교: {prev_y_key} ({len(prev_y_data)}종목)')

    results = add_comparisons(results, prev_y_data)

    # (108) 분기 D&A 3개월치로 (직전 분기 파일의 누적값 기준)
    prev_q_data = load_period_data(os.path.join(DATA_DIR, f'{year}-{PREV_Q[period]}.json')) if period in PREV_Q else {}
    if period in PREV_Q and not prev_q_data:
        print(f'⚠️ 직전 분기 파일 {year}-{PREV_Q[period]} 없음 — 분기 D&A·EBITDA 비움')
    results = quarterize_da(results, prev_q_data, period)

    # 저장
    output = {
        'updated': date.today().isoformat(),
        'year': year,
        'period': period,
        'period_label': f'{year} {PERIOD_LABELS.get(period, period)}',
        'report_name': reprt_name,
        'source': 'OpenDART',
        'stock_count': len(results),
        'compare_yoy': prev_y_key if prev_y_data else None,
        'stocks': results
    }

    # (104) 안전장치: 기존 파일보다 종목이 크게 줄면(API 한도 초과·장애) 덮어쓰지 않음
    old_cnt = len(load_period_data(out_file))
    if old_cnt and len(results) < old_cnt * 0.8:
        print(f'❌ 저장 안 함: 성공 {len(results)}종목 < 기존 {old_cnt}종목의 80% (API 한도·장애 의심, 기존 파일 유지)')
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 하위호환: 최신 데이터를 kospi200.json에도 복사
    os.makedirs(os.path.dirname(LEGACY_FILE), exist_ok=True)
    with open(LEGACY_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # index.json 갱신
    update_index(DATA_DIR)

    n_own = sum(1 for r in results if r.get('ni_owner') is not None)
    n_diff = sum(1 for r in results if r.get('ni_owner') is not None and r.get('ni') is not None and r['ni_owner'] != r['ni'])
    print(f'\n{"="*50}')
    print(f'✅ 성공: {len(results)}종목 → {out_file}')
    print(f'   지배주주 순이익: {n_own}종목 (연결 순이익과 다름 {n_diff})')
    if errors: print(f'❌ 실패: {len(errors)} — {", ".join(errors[:10])}')
    if skipped: print(f'⏭️  스킵: {len(skipped)} — {", ".join(skipped[:10])}')


if __name__ == '__main__':
    main()
