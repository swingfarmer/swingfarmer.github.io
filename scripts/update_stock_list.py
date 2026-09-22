"""
종목 리스트 자동 갱신 — KIS API 시가총액 순위 기반
===================================================
KIS Open API 시가총액 순위 조회로 KOSPI/KOSDAQ 전체 스캔.
KRX API는 차단되므로 사용하지 않음.

오라클 VM crontab: 주 1회 (월 06:00 KST)

출력:
  scripts/kospi200_list.csv  (KOSPI 시총 1조↑)
  scripts/kosdaq_list.csv    (KOSDAQ 시총 5천억↑)

환경변수:
  KIS_APP_KEY, KIS_APP_SECRET (필수)
"""

import os, sys, json, time
import urllib.request, urllib.parse
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MARKETS = {
    'KOSPI': {
        'mkt_div':  'J',           # KIS 시장구분: J=KOSPI
        'csv_file': os.path.join(SCRIPT_DIR, 'kospi200_list.csv'),
        'min_mcap_euk': 10_000,    # 1조 = 10,000억
        'label':    'KOSPI 시총 1조↑',
    },
    'KOSDAQ': {
        'mkt_div':  'Q',           # KIS 시장구분: Q=KOSDAQ
        'csv_file': os.path.join(SCRIPT_DIR, 'kosdaq_list.csv'),
        'min_mcap_euk': 5_000,     # 5천억 = 5,000억
        'label':    'KOSDAQ 시총 5천억↑',
    },
}

KIS_APP_KEY    = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE       = os.environ.get('KIS_BASE_URL', 'https://openapi.koreainvestment.com:9443')

SECTOR_MAP = {
    # KIS 업종코드 → 한글 (주요 업종만)
}


def kis_token():
    """KIS OAuth 토큰 발급."""
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
            print('🔑 KIS 토큰 발급 완료')
        return token
    except Exception as e:
        print(f'❌ KIS 토큰 실패: {e}')
        return None


def kis_market_cap_ranking(token, mkt_div='J'):
    """
    KIS 시가총액 상위 종목 조회.
    /uapi/domestic-stock/v1/ranking/market-cap
    한 번에 최대 30종목, 연속 조회로 전체 스캔.
    """
    all_stocks = []
    ctx_area_nk = ''  # 연속 조회 키
    ctx_area_fk = ''
    page = 0
    max_pages = 50  # 최대 50*30 = 1500종목까지

    while page < max_pages:
        page += 1
        params = {
            'FID_COND_MRKT_DIV_CODE': mkt_div,
            'FID_COND_SCR_DIV_CODE':  '20174',
            'FID_INPUT_ISCD':         '',
            'FID_DIV_CLS_CODE':       '0',
            'FID_BLNG_CLS_CODE':      '0',
            'FID_TRGT_CLS_CODE':      '',
            'FID_TRGT_EXLS_CLS_CODE': '',
            'FID_INPUT_PRICE_1':      '',
            'FID_INPUT_PRICE_2':      '',
            'FID_VOL_CNT':            '',
            'FID_INPUT_DATE_1':       '',
        }
        query = urllib.parse.urlencode(params)
        url = f'{KIS_BASE}/uapi/domestic-stock/v1/ranking/market-cap?{query}'

        headers = {
            'Content-Type':  'application/json; charset=UTF-8',
            'authorization': f'Bearer {token}',
            'appkey':        KIS_APP_KEY,
            'appsecret':     KIS_APP_SECRET,
            'tr_id':         'FHPST01710000',
            'custtype':      'P',
        }
        if ctx_area_nk:
            headers['tr_cont'] = 'N'
            headers['CTX_AREA_NK'] = ctx_area_nk
            headers['CTX_AREA_FK'] = ctx_area_fk
        else:
            headers['tr_cont'] = ''

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_headers = dict(resp.headers)
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f'   ❌ API 호출 실패 (page {page}): {e}')
            break

        if data.get('rt_cd') != '0':
            print(f'   ❌ API 에러: {data.get("msg1", "")}')
            break

        items = data.get('output', [])
        if not items:
            break

        for it in items:
            code = it.get('mksc_shrn_iscd', '').strip()
            name = it.get('hts_kor_isnm', '').strip()
            mcap_str = it.get('stck_avls_scal', '0')  # 시가총액 (억원)
            sector = it.get('bstp_kor_isnm', '기타').strip()

            if not code or not name or len(code) != 6:
                continue

            mcap = int(mcap_str.replace(',', '') or '0')
            all_stocks.append({
                'code':   code,
                'name':   name,
                'sector': sector if sector else '기타',
                'mcap':   mcap,  # 억원 단위
            })

        # 연속 조회 확인
        tr_cont = resp_headers.get('tr_cont', '')
        if tr_cont in ('F', 'M'):
            ctx_area_nk = resp_headers.get('CTX_AREA_NK', data.get('ctx_area_nk', ''))
            ctx_area_fk = resp_headers.get('CTX_AREA_FK', data.get('ctx_area_fk', ''))
            if not ctx_area_nk:
                break
            time.sleep(0.2)
        else:
            break

    all_stocks.sort(key=lambda x: -x['mcap'])
    return all_stocks


def filter_by_mcap(stocks, min_mcap_euk):
    """시총 기준 필터링."""
    return [s for s in stocks if s['mcap'] >= min_mcap_euk]


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
                })
    return stocks


def save_csv(stocks, csv_file, label):
    """CSV 저장 + 변동 리포트."""
    existing = {}
    for s in load_existing_csv(csv_file):
        existing[s['code']] = s.get('sector', '기타')

    old_codes = set(existing.keys())
    new_codes = set(s['code'] for s in stocks)

    # 기존 업종 보존
    for s in stocks:
        if s.get('sector', '') in ('', '기타') and s['code'] in existing:
            s['sector'] = existing[s['code']]

    today = date.today().strftime('%Y.%m.%d')
    with open(csv_file, 'w', encoding='utf-8', newline='') as f:
        f.write(f'# {label} (자동 갱신 {today})\n')
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
        added_names = [s['name'] for s in stocks if s['code'] in added][:15]
        print(f'   🆕 신규 ({len(added)}): {", ".join(added_names)}')
        if len(added) > 15:
            print(f'      ... 외 {len(added)-15}종목')
    if removed:
        removed_info = [f'{existing.get(c,"?")}({c})' for c in list(removed)[:15]]
        print(f'   🗑️  제외 ({len(removed)}): {", ".join(removed_info)}')
    if not added and not removed:
        print(f'   변동 없음')

    print()
    print(f'   시총 Top 10:')
    for i, s in enumerate(stocks[:10], 1):
        mcap_jo = s['mcap'] / 10_000  # 억→조
        print(f'   {i:2d}. {s["name"]:12s} {mcap_jo:8.1f}조  [{s["sector"]}]')


def main():
    print('🔄 종목 리스트 자동 갱신 (KIS API)')
    print(f'   KOSPI: 시총 1조↑ → kospi200_list.csv')
    print(f'   KOSDAQ: 시총 5천억↑ → kosdaq_list.csv')

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수 없음')
        sys.exit(1)

    token = kis_token()
    if not token:
        sys.exit(1)

    ok_count = 0

    for market_name, config in MARKETS.items():
        print(f'\n{"━"*50}')
        print(f'📡 {config["label"]} 조회 중...')
        print(f'{"━"*50}')

        all_stocks = kis_market_cap_ranking(token, config['mkt_div'])
        print(f'   전체 {len(all_stocks)}종목 수집')

        filtered = filter_by_mcap(all_stocks, config['min_mcap_euk'])
        print(f'   시총 기준 통과: {len(filtered)}종목')

        if filtered:
            save_csv(filtered, config['csv_file'], config['label'])
            ok_count += 1
        else:
            print(f'   ❌ 결과 0건 — 기존 CSV 유지')

        time.sleep(1)

    print(f'\n{"="*50}')
    print(f'완료: {ok_count}/{len(MARKETS)} 시장 갱신 성공')


if __name__ == '__main__':
    main()
