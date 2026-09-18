"""
종목 리스트 자동 갱신 — KRX 공개 API 기반 시총 1조↑ 필터
==========================================================
KRX data.krx.co.kr 공개 API로 전체 KOSPI 종목 시가총액을 조회하고
1조원 이상만 추려서 kospi200_list.csv를 갱신한다.

효과:
  - 동국제강 같은 이름 변경, 신규 상장, 상폐 자동 반영
  - 수동 CSV 관리 불필요
  - 추가 패키지/인증 불필요 (urllib만 사용)

사용법:
  python scripts/update_stock_list.py

출력: scripts/kospi200_list.csv (기존 파일 덮어쓰기)

# TODO [오라클 이관]
# 오라클 전환 후에도 이 스크립트는 그대로 사용 가능.
# cron으로 주 1회 실행.
"""

import os, sys, json
import urllib.request, urllib.parse
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE   = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
MIN_MCAP   = 1_000_000_000_000  # 1조원

KRX_URL = 'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'

# KRX 업종 코드 → 업종명 매핑 (KRX 분류 기준)
# KRX API가 업종 정보를 같이 주므로 이 매핑은 fallback용
SECTOR_FALLBACK = '기타'


def find_latest_trading_date():
    """최근 거래일 찾기 — KRX에 데이터 있는 날까지 최대 10일 뒤로."""
    for i in range(10):
        d = (date.today() - timedelta(days=i))
        if d.weekday() >= 5:  # 주말 스킵
            continue
        yield d.strftime('%Y%m%d')


def fetch_krx_marcap(tdate):
    """KRX에서 전체 KOSPI 시가총액 데이터 조회."""
    params = {
        'bld':    'dbms/MDC/STAT/standard/MDCSTAT01501',
        'locale': 'ko_KR',
        'mktId':  'STK',  # KOSPI
        'trdDd':  tdate,
        'share':  '1',
        'money':  '1',
        'csvxls_is498': 'false',
    }

    body = urllib.parse.urlencode(params).encode('utf-8')
    req = urllib.request.Request(
        KRX_URL,
        data=body,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': 'http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd',
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        items = data.get('OutBlock_1', [])
        return items
    except Exception as e:
        print(f'   ⚠️  {tdate} 조회 실패: {e}')
        return None


def parse_krx_number(s):
    """KRX 숫자 문자열 → int (콤마 제거)."""
    if not s:
        return 0
    return int(s.replace(',', ''))


def load_existing_sectors():
    """기존 CSV에서 {종목코드: 업종} 매핑 로드."""
    sectors = {}
    if not os.path.exists(CSV_FILE):
        return sectors
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                sectors[parts[0].strip()] = parts[2].strip()
    return sectors


def main():
    print('🔄 종목 리스트 자동 갱신 (시총 1조↑)')
    print()

    # 1) 최근 거래일에서 데이터 가져오기
    items = None
    used_date = None
    for tdate in find_latest_trading_date():
        print(f'   {tdate} 조회 시도...', end='', flush=True)
        items = fetch_krx_marcap(tdate)
        if items and len(items) > 100:  # 최소 100종목은 있어야 정상
            used_date = tdate
            print(f' ✓ ({len(items)}종목)')
            break
        print(' ✗')

    if not items:
        print('❌ KRX 데이터 조회 실패 — 네트워크 또는 공휴일 확인')
        sys.exit(1)

    # 2) 파싱 + 1조 이상 필터
    stocks = []
    for item in items:
        code = item.get('ISU_SRT_CD', '')       # 종목코드 (6자리)
        name = item.get('ISU_ABBRV', '')         # 종목명
        mcap = parse_krx_number(item.get('MKTCAP', '0'))  # 시가총액 (원)
        sector = item.get('IDX_IND_NM', '')      # 업종 (KRX 기준)

        if not code or not name:
            continue
        if len(code) != 6 or not code.isdigit():
            continue

        if mcap >= MIN_MCAP:
            stocks.append({
                'code': code,
                'name': name,
                'sector': sector if sector else SECTOR_FALLBACK,
                'mcap': mcap,
            })

    # 시총 내림차순 정렬
    stocks.sort(key=lambda x: -x['mcap'])

    print(f'   전체 KOSPI: {len(items)}종목')
    print(f'   시총 1조↑: {len(stocks)}종목')

    if not stocks:
        print('❌ 필터 결과 0 — 데이터 이상')
        sys.exit(1)

    # 3) 기존 업종 매핑 (KRX 업종이 비어있을 때 fallback)
    existing = load_existing_sectors()
    old_count = len(existing)
    old_codes = set(existing.keys())
    new_codes = set(r['code'] for r in stocks)

    for s in stocks:
        # KRX가 업종을 안 주거나 '기타'이면 기존 CSV에서 가져옴
        if s['sector'] in ('', SECTOR_FALLBACK) and s['code'] in existing:
            s['sector'] = existing[s['code']]

    # 4) CSV 저장
    d = used_date
    with open(CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        f.write(f'# KOSPI 시총 1조↑ (자동 갱신 {d[:4]}.{d[4:6]}.{d[6:]})\n')
        f.write('# 종목코드,종목명,업종\n')
        for s in stocks:
            f.write(f'{s["code"]},{s["name"]},{s["sector"]}\n')

    # 5) 변동 리포트
    added   = new_codes - old_codes
    removed = old_codes - new_codes

    print()
    print(f'{"="*50}')
    print(f'✅ {len(stocks)}종목 → {os.path.basename(CSV_FILE)}')
    print(f'   기존: {old_count}종목')

    if added:
        added_names = [s['name'] for s in stocks if s['code'] in added][:10]
        print(f'   🆕 신규 ({len(added)}): {", ".join(added_names)}')
        if len(added) > 10:
            print(f'      ... 외 {len(added)-10}종목')

    if removed:
        removed_info = [f'{c}({existing.get(c,"")})' for c in list(removed)[:10]]
        print(f'   🗑️  제외 ({len(removed)}): {", ".join(removed_info)}')

    if not added and not removed:
        print(f'   변동 없음')

    # 시총 Top 10
    print()
    print('   시총 Top 10:')
    for i, s in enumerate(stocks[:10], 1):
        mcap_jo = s['mcap'] / 1_000_000_000_000
        print(f'   {i:2d}. {s["name"]:12s} {mcap_jo:8.1f}조  [{s["sector"]}]')


if __name__ == '__main__':
    main()
