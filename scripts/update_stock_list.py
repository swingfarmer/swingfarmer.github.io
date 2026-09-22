"""
종목 리스트 자동 갱신 — KOSPI 시총 1조↑ + KOSDAQ 시총 5천억↑
================================================================
1차: KRX 공개 API로 전체 시가총액 조회 → 필터
2차: KRX 실패 시 KIS API fallback — 기존 CSV 종목만 시총 재검증

오라클 VM crontab: 주 1회 (월 06:00 KST)

출력:
  scripts/kospi200_list.csv  (KOSPI 시총 1조↑)
  scripts/kosdaq_list.csv    (KOSDAQ 시총 5천억↑)

환경변수 (KIS fallback용, 선택):
  KIS_APP_KEY, KIS_APP_SECRET
"""

import os, sys, json, time, ssl
import urllib.request, urllib.parse
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 시장별 설정
MARKETS = {
    'KOSPI': {
        'mktId':    'STK',
        'csv_file': os.path.join(SCRIPT_DIR, 'kospi200_list.csv'),
        'min_mcap': 1_000_000_000_000,      # 1조원
        'min_mcap_euk': 10_000,              # 1조 = 10,000억 (KIS 단위)
        'label':    'KOSPI 시총 1조↑',
    },
    'KOSDAQ': {
        'mktId':    'KSQ',
        'csv_file': os.path.join(SCRIPT_DIR, 'kosdaq_list.csv'),
        'min_mcap': 500_000_000_000,         # 5천억원
        'min_mcap_euk': 5_000,               # 5천억 = 5,000억 (KIS 단위)
        'label':    'KOSDAQ 시총 5천억↑',
    },
}

KIS_APP_KEY    = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE       = os.environ.get('KIS_BASE_URL', 'https://openapi.koreainvestment.com:9443')


# ──────────────────────────────────────────────
# 방법 1: KRX 공개 API (인증 불필요)
# ──────────────────────────────────────────────

def try_krx_api(mkt_id):
    """KRX data.krx.co.kr 공개 API — 전체 시가총액."""
    print(f'\n📡 [방법 1] KRX 공개 API 시도 ({mkt_id})')

    for i in range(10):
        d = date.today() - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        tdate = d.strftime('%Y%m%d')
        result = _fetch_krx(tdate, mkt_id)
        if result and len(result) > 50:
            print(f'   ✅ {tdate}: {len(result)}종목')
            return result, tdate
        print(f'   {tdate}: 실패')
    return None, None


def _fetch_krx(tdate, mkt_id):
    """KRX에서 전체 종목 시세 조회."""
    param_sets = [
        {
            'url':  'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd',
            'data': {
                'bld':          'dbms/MDC/STAT/standard/MDCSTAT01501',
                'locale':       'ko_KR',
                'mktId':        mkt_id,
                'trdDd':        tdate,
                'share':        '1',
                'money':        '1',
                'csvxls_isNo':  'false',
            },
        },
        {
            'url':  'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd',
            'data': {
                'bld':          'dbms/MDC/STAT/standard/MDCSTAT01501',
                'locale':       'ko_KR',
                'mktId':        mkt_id,
                'trdDd':        tdate,
                'share':        '1',
                'money':        '1',
                'csvxls_isNo':  'false',
            },
        },
        {
            'url':   'https://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd',
            'data':  {
                'locale':       'ko_KR',
                'mktId':        mkt_id,
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

    for ps in param_sets:
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
                items = _fetch_krx_with_otp(raw.strip(), ctx)
                if items:
                    return items
                continue

            data = json.loads(raw)
            items = data.get('OutBlock_1', [])
            if items:
                return items
        except:
            pass
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


def parse_krx_stocks(items, min_mcap):
    """KRX 응답 파싱 → 종목 리스트."""
    stocks = []
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
        if mcap >= min_mcap:
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

def try_kis_fallback(csv_file, min_mcap_euk, mkt_div='J'):
    """KIS API로 기존 CSV 종목의 시총 재검증."""
    print(f'\n📡 [방법 2] KIS API fallback')

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('   ⚠️  KIS_APP_KEY / KIS_APP_SECRET 없음 — fallback 불가')
        return None

    existing = load_existing_csv(csv_file)
    if not existing:
        print('   ⚠️  기존 CSV 없음 — fallback 불가')
        return None

    token = _kis_token()
    if not token:
        return None

    print(f'   기존 {len(existing)}종목 시총 확인 중...')
    stocks = []
    kept_no_data = []
    removed = []
    for i, s in enumerate(existing, 1):
        if i % 50 == 0:
            print(f'   [{i}/{len(existing)}]...')
        mcap = _kis_market_cap(token, s['code'], mkt_div)

        if mcap is None or mcap == 0:
            time.sleep(0.3)
            mcap = _kis_market_cap(token, s['code'], mkt_div)

        if mcap is None or mcap == 0:
            s['mcap'] = 0
            stocks.append(s)
            kept_no_data.append(s['name'])
        elif mcap >= min_mcap_euk:
            s['mcap'] = mcap * 100_000_000
            stocks.append(s)
        else:
            removed.append(f'{s["name"]}({mcap}억)')

        time.sleep(0.15)

    stocks.sort(key=lambda x: -(x['mcap'] or 0))
    print(f'   ✅ {len(stocks)}종목 유지')
    if kept_no_data:
        print(f'   ⚠️  시총 미확인 {len(kept_no_data)}종목 (기존 유지): {", ".join(kept_no_data[:10])}')
    if removed:
        print(f'   🗑️  제외 {len(removed)}종목: {", ".join(removed[:10])}')
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


def _kis_market_cap(token, code, mkt_div='J'):
    """KIS 현재가 조회 → 시총(억원) 반환."""
    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/inquire-price'
           f'?FID_COND_MRKT_DIV_CODE={mkt_div}&FID_INPUT_ISCD={code}')
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

def load_existing_csv(csv_file):
    """기존 CSV → [{code, name, sector}]."""
    if not os.path.exists(csv_file):
        return []
    stocks = []
    with open(csv_file, 'r', encoding='utf-8') as f:
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


def save_csv(stocks, source_date, csv_file, label):
    """CSV 저장."""
    existing = {}
    for s in load_existing_csv(csv_file):
        existing[s['code']] = s['sector']

    old_codes = set(existing.keys())
    new_codes = set(s['code'] for s in stocks)

    for s in stocks:
        if s.get('sector', '') in ('', '기타') and s['code'] in existing:
            s['sector'] = existing[s['code']]

    with open(csv_file, 'w', encoding='utf-8', newline='') as f:
        f.write(f'# {label} (자동 갱신 {source_date})\n')
        f.write('# 종목코드,종목명,업종\n')
        for s in stocks:
            f.write(f'{s["code"]},{s["name"]},{s["sector"]}\n')

    added   = new_codes - old_codes
    removed = old_codes - new_codes

    print()
    print(f'{"="*50}')
    print(f'✅ {len(stocks)}종목 → {os.path.basename(csv_file)}')
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

    print()
    print(f'   시총 Top 10:')
    for i, s in enumerate(stocks[:10], 1):
        mcap_jo = s['mcap'] / 1_000_000_000_000
        print(f'   {i:2d}. {s["name"]:12s} {mcap_jo:8.1f}조  [{s["sector"]}]')


def process_market(market_name, config):
    """시장 하나 처리."""
    print(f'\n{"━"*50}')
    print(f'🔄 {config["label"]} 갱신')
    print(f'{"━"*50}')

    # 방법 1: KRX
    items, tdate = try_krx_api(config['mktId'])
    if items:
        stocks = parse_krx_stocks(items, config['min_mcap'])
        if stocks:
            save_csv(stocks, f'{tdate[:4]}.{tdate[4:6]}.{tdate[6:]}',
                     config['csv_file'], config['label'])
            return True

    # 방법 2: KIS fallback
    mkt_div = 'J' if market_name == 'KOSPI' else 'J'  # KIS는 둘 다 'J'
    stocks = try_kis_fallback(config['csv_file'], config['min_mcap_euk'], mkt_div)
    if stocks:
        save_csv(stocks, date.today().strftime('%Y.%m.%d'),
                 config['csv_file'], config['label'])
        return True

    print(f'\n❌ {market_name} KRX · KIS 모두 실패 — 기존 CSV 유지')
    return False


def main():
    print('🔄 종목 리스트 자동 갱신')
    print(f'   KOSPI: 시총 1조↑ → kospi200_list.csv')
    print(f'   KOSDAQ: 시총 5천억↑ → kosdaq_list.csv')

    ok_count = 0
    for market_name, config in MARKETS.items():
        if process_market(market_name, config):
            ok_count += 1

    print(f'\n{"="*50}')
    print(f'완료: {ok_count}/{len(MARKETS)} 시장 갱신 성공')


if __name__ == '__main__':
    main()
