"""
종목 리스트 자동 갱신 — 시총 1조↑ 필터
=========================================
1차: KRX 공개 API로 전체 KOSPI 시가총액 조회 → 1조↑ 필터 (신규 종목 포함)
2차: KRX 실패 시 KIS API fallback — 기존 CSV 종목만 시총 재검증

사용법:
  python scripts/update_stock_list.py

출력: scripts/kospi200_list.csv (기존 파일 덮어쓰기)

환경변수 (KIS fallback용, 선택):
  KIS_APP_KEY     — 한투 Open API 앱 키
  KIS_APP_SECRET  — 한투 Open API 앱 시크릿

# TODO [오라클 이관]
# 오라클 전환 후에도 이 스크립트는 그대로 사용 가능.
# cron으로 주 1회 실행.
"""

import os, sys, json, time, ssl
import urllib.request, urllib.parse
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE   = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
MIN_MCAP   = 1_000_000_000_000  # 1조원
MIN_MCAP_EUK = 10_000           # 1조 = 10,000억 (KIS hts_avls 단위: 억원)

KIS_APP_KEY    = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE       = os.environ.get('KIS_BASE_URL', 'https://openapi.koreainvestment.com:9443')


# ──────────────────────────────────────────────
# 방법 1: KRX 공개 API (인증 불필요)
# ──────────────────────────────────────────────

def try_krx_api():
    """KRX data.krx.co.kr 공개 API — 전체 KOSPI 시가총액."""
    print('\n📡 [방법 1] KRX 공개 API 시도')

    # 최근 거래일 탐색 (최대 10일)
    for i in range(10):
        d = date.today() - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        tdate = d.strftime('%Y%m%d')
        result = _fetch_krx(tdate)
        if result and len(result) > 100:
            print(f'   ✅ {tdate}: {len(result)}종목')
            return result, tdate
        print(f'   {tdate}: 실패')
    return None, None


def _fetch_krx(tdate):
    """KRX에서 전체 KOSPI 종목 시세 조회."""

    # KRX API 파라미터 — 여러 조합 시도
    param_sets = [
        # 조합 1: 표준 (HTTPS)
        {
            'url':  'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd',
            'data': {
                'bld':          'dbms/MDC/STAT/standard/MDCSTAT01501',
                'locale':       'ko_KR',
                'mktId':        'STK',
                'trdDd':        tdate,
                'share':        '1',
                'money':        '1',
                'csvxls_isNo':  'false',
            },
        },
        # 조합 2: HTTP
        {
            'url':  'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd',
            'data': {
                'bld':          'dbms/MDC/STAT/standard/MDCSTAT01501',
                'locale':       'ko_KR',
                'mktId':        'STK',
                'trdDd':        tdate,
                'share':        '1',
                'money':        '1',
                'csvxls_isNo':  'false',
            },
        },
        # 조합 3: OTP 방식
        {
            'url':   'https://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd',
            'data':  {
                'locale':       'ko_KR',
                'mktId':        'STK',
                'trdDd':        tdate,
                'share':        '1',
                'money':        '1',
                'csvxls_isNo':  'false',
                'name':         'fileDown',
                'url':          'dbms/MDC/STAT/standard/MDCSTAT01501',
            },
            'otp': True,
        },
    ]

    ctx = ssl.create_default_context()

    for i, ps in enumerate(param_sets):
        try:
            body = urllib.parse.urlencode(ps['data']).encode('utf-8')
            req = urllib.request.Request(ps['url'], data=body, headers={
                'User-Agent':   'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer':      'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020101',
                'Accept':       'application/json, text/javascript, */*',
            })
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                raw = resp.read().decode('utf-8')

            if ps.get('otp'):
                # OTP 방식: 토큰 받아서 2차 요청
                items = _fetch_krx_with_otp(raw.strip(), ctx)
                if items:
                    return items
                continue

            data = json.loads(raw)
            items = data.get('OutBlock_1', [])
            if items:
                return items
        except Exception as e:
            pass  # 다음 조합 시도

    return None


def _fetch_krx_with_otp(otp_code, ctx):
    """OTP 코드로 KRX CSV 다운로드 후 파싱."""
    if not otp_code or len(otp_code) > 200:
        return None
    try:
        body = urllib.parse.urlencode({'code': otp_code}).encode('utf-8')
        req = urllib.request.Request(
            'https://data.krx.co.kr/comm/fileDn/download_csv/download.cmd',
            data=body,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Referer':    'https://data.krx.co.kr/',
            }
        )
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            raw = resp.read()

        # CSV 파싱 (BOM 제거)
        text = raw.decode('euc-kr', errors='replace')
        if text.startswith('\ufeff'):
            text = text[1:]
        lines = text.strip().split('\n')
        if len(lines) < 2:
            return None

        headers = [h.strip().strip('"') for h in lines[0].split(',')]
        items = []
        for line in lines[1:]:
            vals = [v.strip().strip('"') for v in line.split(',')]
            if len(vals) >= len(headers):
                item = dict(zip(headers, vals))
                items.append(item)
        return items if len(items) > 50 else None
    except:
        return None


def parse_krx_stocks(items):
    """KRX 응답 파싱 → 종목 리스트."""
    stocks = []

    # 필드명 매핑 (KRX API vs CSV 다운로드 차이 대응)
    code_keys  = ['ISU_SRT_CD', '종목코드', '단축코드']
    name_keys  = ['ISU_ABBRV', '종목명']
    mcap_keys  = ['MKTCAP', '시가총액']
    sector_keys = ['IDX_IND_NM', '업종명', '소속부']

    for item in items:
        code = _find_val(item, code_keys, '')
        name = _find_val(item, name_keys, '')
        mcap_str = _find_val(item, mcap_keys, '0')
        sector = _find_val(item, sector_keys, '기타')

        if not code or not name:
            continue
        code = code.strip()
        if len(code) != 6 or not code.isdigit():
            continue

        mcap = int(mcap_str.replace(',', '').replace(' ', '') or '0')
        if mcap >= MIN_MCAP:
            stocks.append({
                'code':   code,
                'name':   name.strip(),
                'sector': sector.strip() if sector.strip() else '기타',
                'mcap':   mcap,
            })

    stocks.sort(key=lambda x: -x['mcap'])
    return stocks


def _find_val(d, keys, default=''):
    for k in keys:
        if k in d and d[k]:
            return d[k]
    return default


# ──────────────────────────────────────────────
# 방법 2: KIS API fallback (기존 종목 시총 재검증)
# ──────────────────────────────────────────────

def try_kis_fallback():
    """KIS API로 기존 CSV 종목의 시총 재검증."""
    print('\n📡 [방법 2] KIS API fallback')

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('   ⚠️  KIS_APP_KEY / KIS_APP_SECRET 없음 — fallback 불가')
        return None

    existing = load_existing_csv()
    if not existing:
        print('   ⚠️  기존 CSV 없음 — fallback 불가')
        return None

    # 토큰 발급
    token = _kis_token()
    if not token:
        return None

    print(f'   기존 {len(existing)}종목 시총 확인 중...')
    stocks = []
    for i, s in enumerate(existing, 1):
        if i % 50 == 0:
            print(f'   [{i}/{len(existing)}]...')
        mcap = _kis_market_cap(token, s['code'])
        if mcap is not None and mcap >= MIN_MCAP_EUK:
            s['mcap'] = mcap * 100_000_000  # 억→원 변환
            stocks.append(s)
        time.sleep(0.06)

    stocks.sort(key=lambda x: -x['mcap'])
    print(f'   ✅ {len(stocks)}종목 통과 (시총 1조↑)')
    print(f'   ⚠️  신규 상장은 감지 불가 — KRX API 복구 후 전체 갱신 필요')
    return stocks


def _kis_token():
    url = f'{KIS_BASE}/oauth2/tokenP'
    body = json.dumps({
        'grant_type': 'client_credentials',
        'appkey':     KIS_APP_KEY,
        'appsecret':  KIS_APP_SECRET,
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json; charset=UTF-8',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        token = data.get('access_token', '')
        if token:
            print('   🔑 KIS 토큰 발급 완료')
        return token
    except Exception as e:
        print(f'   ❌ KIS 토큰 실패: {e}')
        return None


def _kis_market_cap(token, code):
    """KIS 현재가 조회 → 시총(억원) 반환."""
    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/inquire-price'
           f'?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD={code}')
    req = urllib.request.Request(url, headers={
        'Content-Type':  'application/json; charset=UTF-8',
        'authorization': f'Bearer {token}',
        'appkey':        KIS_APP_KEY,
        'appsecret':     KIS_APP_SECRET,
        'tr_id':         'FHKST01010100',
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('rt_cd') != '0':
            return None
        out = data.get('output', {})
        return int(out.get('hts_avls', '0') or '0')
    except:
        return None


# ──────────────────────────────────────────────
# 공통
# ──────────────────────────────────────────────

def load_existing_csv():
    """기존 CSV → [{code, name, sector}]."""
    if not os.path.exists(CSV_FILE):
        return []
    stocks = []
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                stocks.append({
                    'code':   parts[0].strip(),
                    'name':   parts[1].strip(),
                    'sector': parts[2].strip(),
                    'mcap':   0,
                })
    return stocks


def load_existing_sectors():
    """기존 CSV → {code: sector} 매핑."""
    sectors = {}
    for s in load_existing_csv():
        sectors[s['code']] = s['sector']
    return sectors


def save_csv(stocks, source_date):
    """CSV 저장."""
    existing = load_existing_sectors()
    old_codes = set(existing.keys())
    new_codes = set(s['code'] for s in stocks)

    # KRX 업종이 비어있으면 기존 CSV에서 가져옴
    for s in stocks:
        if s.get('sector', '') in ('', '기타') and s['code'] in existing:
            s['sector'] = existing[s['code']]

    with open(CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        f.write(f'# KOSPI 시총 1조↑ (자동 갱신 {source_date})\n')
        f.write('# 종목코드,종목명,업종\n')
        for s in stocks:
            f.write(f'{s["code"]},{s["name"]},{s["sector"]}\n')

    # 변동 리포트
    added   = new_codes - old_codes
    removed = old_codes - new_codes

    print()
    print(f'{"="*50}')
    print(f'✅ {len(stocks)}종목 → {os.path.basename(CSV_FILE)}')
    print(f'   기존: {len(old_codes)}종목')

    if added:
        added_names = [s['name'] for s in stocks if s['code'] in added][:10]
        print(f'   🆕 신규 ({len(added)}): {", ".join(added_names)}')
        if len(added) > 10:
            print(f'      ... 외 {len(added)-10}종목')

    if removed:
        removed_info = [f'{existing.get(c,"?")}({c})' for c in list(removed)[:10]]
        print(f'   🗑️  제외 ({len(removed)}): {", ".join(removed_info)}')

    if not added and not removed:
        print(f'   변동 없음')

    # 시총 Top 10
    print()
    print('   시총 Top 10:')
    for i, s in enumerate(stocks[:10], 1):
        mcap_jo = s['mcap'] / 1_000_000_000_000
        print(f'   {i:2d}. {s["name"]:12s} {mcap_jo:8.1f}조  [{s["sector"]}]')


def main():
    print('🔄 종목 리스트 자동 갱신 (시총 1조↑)')

    # 방법 1: KRX 공개 API
    items, tdate = try_krx_api()
    if items:
        stocks = parse_krx_stocks(items)
        if stocks:
            save_csv(stocks, f'{tdate[:4]}.{tdate[4:6]}.{tdate[6:]}')
            return

    # 방법 2: KIS API fallback
    stocks = try_kis_fallback()
    if stocks:
        save_csv(stocks, date.today().strftime('%Y.%m.%d'))
        return

    # 둘 다 실패
    print()
    print('❌ KRX · KIS 모두 실패')
    print('   가능한 원인:')
    print('   - KRX API 일시 장애 (주말·공휴일)')
    print('   - KIS 환경변수 미설정')
    print('   - 네트워크 문제')
    print()
    print('   → 기존 kospi200_list.csv를 그대로 유지합니다.')
    # exit 0으로 — 기존 CSV 유지, workflow 실패로 처리 안 함
    sys.exit(0)


if __name__ == '__main__':
    main()
