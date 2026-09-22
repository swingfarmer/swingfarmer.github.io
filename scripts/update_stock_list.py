"""
종목 리스트 자동 갱신 — 네이버 증권 시가총액 순위 API
=====================================================
네이버 증권 공개 API (인증 불필요, 무료)
KOSPI 시총 1조↑ / KOSDAQ 시총 5천억↑ 필터

오라클 VM crontab: 주 1회 (월 06:00 KST)

출력:
  scripts/kospi200_list.csv  (KOSPI 시총 1조↑)
  scripts/kosdaq_list.csv    (KOSDAQ 시총 5천억↑)
"""

import os, sys, json, time, requests
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MARKETS = {
    'KOSPI': {
        'api_name':  'KOSPI',
        'csv_file':  os.path.join(SCRIPT_DIR, 'kospi200_list.csv'),
        'min_mcap':  1_000_000_000_000,      # 1조원
        'label':     'KOSPI 시총 1조↑',
    },
    'KOSDAQ': {
        'api_name':  'KOSDAQ',
        'csv_file':  os.path.join(SCRIPT_DIR, 'kosdaq_list.csv'),
        'min_mcap':  500_000_000_000,        # 5천억원
        'label':     'KOSDAQ 시총 5천억↑',
    },
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PAGE_SIZE = 50


def fetch_stocks(api_name, min_mcap):
    """네이버 증권 시가총액 순위 — 기준 이하 나올 때까지 페이징."""
    stocks = []
    page = 1
    max_pages = 30  # 안전장치 (50*30 = 1500종목)

    while page <= max_pages:
        url = f"https://m.stock.naver.com/api/stocks/marketValue/{api_name}?page={page}&pageSize={PAGE_SIZE}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f'   ❌ page {page} 실패: {e}')
            break

        items = data.get('stocks', [])
        if not items:
            break

        below_count = 0
        for it in items:
            code = it.get('itemCode', '').strip()
            name = it.get('stockName', '').strip()
            mcap_raw = int(it.get('marketValueRaw', '0') or '0')

            if not code or not name or len(code) != 6:
                continue

            # ETF/ETN/리츠 등 제외 (stockEndType이 'stock'인 것만)
            if it.get('stockEndType', '') != 'stock':
                continue

            if mcap_raw >= min_mcap:
                stocks.append({
                    'code':   code,
                    'name':   name,
                    'sector': '',  # 네이버 API에 업종 없음 — 기존 CSV에서 보존
                    'mcap':   mcap_raw,
                })
            else:
                below_count += 1

        if page % 5 == 0:
            print(f'   page {page}: 누적 {len(stocks)}종목')

        # 이 페이지에서 기준 미달이 나왔으면 → 이후는 더 작으니 종료
        if below_count > 0:
            break

        page += 1
        time.sleep(0.3)  # rate limit 방지

    stocks.sort(key=lambda x: -x['mcap'])
    return stocks


def load_existing_csv(csv_file):
    """기존 CSV → {code: sector} 매핑."""
    sectors = {}
    if not os.path.exists(csv_file):
        return sectors
    with open(csv_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                sectors[parts[0].strip()] = parts[2].strip()
    return sectors


def save_csv(stocks, csv_file, label):
    """CSV 저장 + 변동 리포트."""
    existing = load_existing_csv(csv_file)
    old_codes = set(existing.keys())
    new_codes = set(s['code'] for s in stocks)

    # 기존 업종 보존
    for s in stocks:
        if s.get('sector', '') in ('', '기타') and s['code'] in existing:
            s['sector'] = existing[s['code']]
        if not s.get('sector'):
            s['sector'] = '기타'

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
        mcap_jo = s['mcap'] / 1_000_000_000_000
        print(f'   {i:2d}. {s["name"]:12s} {mcap_jo:8.1f}조  [{s["sector"]}]')


def main():
    print('🔄 종목 리스트 자동 갱신 (네이버 증권 API)')
    print(f'   KOSPI: 시총 1조↑ → kospi200_list.csv')
    print(f'   KOSDAQ: 시총 5천억↑ → kosdaq_list.csv')

    ok_count = 0

    for market_name, config in MARKETS.items():
        print(f'\n{"━"*50}')
        print(f'📡 {config["label"]} 조회 중...')
        print(f'{"━"*50}')

        stocks = fetch_stocks(config['api_name'], config['min_mcap'])
        print(f'   총 {len(stocks)}종목 수집')

        if stocks:
            save_csv(stocks, config['csv_file'], config['label'])
            ok_count += 1
        else:
            print(f'   ❌ 결과 0건 — 기존 CSV 유지')

        time.sleep(1)

    print(f'\n{"="*50}')
    print(f'완료: {ok_count}/{len(MARKETS)} 시장 갱신 성공')


if __name__ == '__main__':
    main()
