"""
업종·종목 모멘텀 분석 — KIS Open API
======================================
주간/월간/장중 수익률 기반 업종·종목 강세 랭킹.

출력:
  data/kr/momentum/weekly.json   (주간 — 5거래일)
  data/kr/momentum/monthly.json  (월간 — 22거래일)
  data/kr/momentum/intraday.json (장중 — 전일 종가 대비)

사용법:
  python scripts/fetch_momentum.py              ← 주간+월간 모두
  python scripts/fetch_momentum.py --weekly      ← 주간만
  python scripts/fetch_momentum.py --monthly     ← 월간만
  python scripts/fetch_momentum.py --intraday    ← 장중만 (오라클 cron 10:05)

환경변수 (필수):
  KIS_APP_KEY, KIS_APP_SECRET
"""

import os, sys, json, time
import urllib.request
from datetime import date, datetime, timedelta
from collections import defaultdict

# ── 설정 ──
KIS_APP_KEY    = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE       = os.environ.get('KIS_BASE_URL',
                                'https://openapi.koreainvestment.com:9443')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)
STOCK_LIST = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
OUT_DIR    = os.path.join(ROOT_DIR, 'data', 'kr', 'momentum')

CALL_DELAY = 0.08  # ~12 req/s


# ── 유틸 ──
def load_stock_list():
    stocks = []
    with open(STOCK_LIST, 'r', encoding='utf-8') as f:
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


def safe_int(v):
    try: return int(v)
    except: return 0


def safe_float(v):
    try: return float(v)
    except: return 0.0


# ── KIS API ──
def get_access_token():
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
        if not token:
            print(f'❌ 토큰 발급 실패: {data}')
            sys.exit(1)
        print('🔑 토큰 발급 완료')
        return token
    except Exception as e:
        print(f'❌ 토큰 발급 실패: {e}')
        sys.exit(1)


def fetch_daily_prices(token, code, days=50):
    """종목 일자별 시세 (최근 N거래일). FHKST01010400."""
    end_date = date.today().strftime('%Y%m%d')
    start_date = (date.today() - timedelta(days=days + 20)).strftime('%Y%m%d')  # 여유

    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-price'
           f'?FID_COND_MRKT_DIV_CODE=J'
           f'&FID_INPUT_ISCD={code}'
           f'&FID_INPUT_DATE_1={start_date}'
           f'&FID_INPUT_DATE_2={end_date}'
           f'&FID_PERIOD_DIV_CODE=D'
           f'&FID_ORG_ADJ_PRC=0')

    req = urllib.request.Request(url, headers={
        'Content-Type':  'application/json; charset=UTF-8',
        'authorization': f'Bearer {token}',
        'appkey':        KIS_APP_KEY,
        'appsecret':     KIS_APP_SECRET,
        'tr_id':         'FHKST01010400',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('rt_cd') != '0':
            return []
        output = data.get('output', [])
        # [{stck_bsop_date, stck_clpr, ...}, ...] 최신→과거 순
        prices = []
        for row in output:
            d = row.get('stck_bsop_date', '')
            c = safe_int(row.get('stck_clpr', '0'))
            v = safe_int(row.get('acml_vol', '0'))
            if d and c:
                prices.append({'date': d, 'close': c, 'volume': v})
        return prices  # 최신순
    except:
        return []


def fetch_current_price(token, code):
    """현재가 조회 (FHKST01010100) — 실제 거래 가격."""
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
        return safe_int(out.get('stck_prpr', '0')) or None
    except:
        return None


# ── 모멘텀 계산 ──
def calc_momentum(stocks_data, n_days):
    """n거래일 수익률 계산."""
    results = []
    for s in stocks_data:
        prices = s.get('daily', [])
        cur = s.get('current_price') or (prices[0]['close'] if prices else None)
        if not cur or len(prices) < n_days:
            continue

        past = prices[min(n_days - 1, len(prices) - 1)]['close']
        if not past:
            continue

        ret = round((cur - past) / past * 100, 2)
        results.append({
            'code':       s['code'],
            'name':       s['name'],
            'sector':     s['sector'],
            'price':      cur,
            'prev_price': past,
            'return_pct': ret,
            'volume_avg': _avg_volume(prices, min(n_days, len(prices))),
        })
    return results


def _avg_volume(prices, n):
    vols = [p['volume'] for p in prices[:n] if p['volume']]
    return round(sum(vols) / len(vols)) if vols else 0


def build_sector_ranking(stock_results):
    """종목 결과를 업종별로 집계."""
    sector_map = defaultdict(list)
    for s in stock_results:
        sector_map[s['sector']].append(s)

    sectors = []
    for name, stocks in sector_map.items():
        rets = [s['return_pct'] for s in stocks]
        avg_ret = round(sum(rets) / len(rets), 2)
        # 업종 내 종목을 수익률 내림차순 정렬
        stocks_sorted = sorted(stocks, key=lambda x: -x['return_pct'])
        sectors.append({
            'sector':       name,
            'return_pct':   avg_ret,
            'stock_count':  len(stocks),
            'top_stocks':   stocks_sorted[:5],   # 상위 5종목
            'worst_stocks': stocks_sorted[-3:],   # 하위 3종목
        })

    sectors.sort(key=lambda x: -x['return_pct'])
    return sectors


def build_output(stock_results, period_label, n_days):
    """최종 JSON 구조."""
    sectors = build_sector_ranking(stock_results)
    sorted_all = sorted(stock_results, key=lambda x: -x['return_pct'])

    return {
        'updated':      date.today().isoformat(),
        'period':       period_label,
        'trading_days': n_days,
        'total_stocks': len(stock_results),
        'sectors':      sectors,
        'top_gainers':  sorted_all[:15],
        'top_losers':   sorted_all[-15:][::-1],  # 최악→차선 순
        'stats': {
            'avg_return': round(sum(s['return_pct'] for s in stock_results) / max(len(stock_results), 1), 2),
            'positive':   sum(1 for s in stock_results if s['return_pct'] > 0),
            'negative':   sum(1 for s in stock_results if s['return_pct'] < 0),
            'unchanged':  sum(1 for s in stock_results if s['return_pct'] == 0),
        },
    }


# ── 장중 모멘텀 (전일 종가 대비 현재가) ──
def fetch_intraday(token, stocks):
    """전 종목 현재가만 수집 → 전일 종가 대비 등락률 계산."""
    results = []
    errors = []
    for i, s in enumerate(stocks, 1):
        code = s['code']
        if i % 30 == 0 or i == 1:
            print(f'   [{i}/{len(stocks)}] {s["name"]}...')

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
                errors.append(s['name'])
                time.sleep(CALL_DELAY)
                continue
            out = data.get('output', {})
            price    = safe_int(out.get('stck_prpr', '0'))
            prev_cls = safe_int(out.get('stck_sdpr', '0'))  # 전일 종가
            open_prc = safe_int(out.get('stck_oprc', '0'))  # 당일 시가
            high     = safe_int(out.get('stck_hgpr', '0'))
            low      = safe_int(out.get('stck_lwpr', '0'))
            volume   = safe_int(out.get('acml_vol', '0'))

            if not price or not prev_cls:
                errors.append(s['name'])
                time.sleep(CALL_DELAY)
                continue

            ret = round((price - prev_cls) / prev_cls * 100, 2)
            open_ret = round((price - open_prc) / open_prc * 100, 2) if open_prc else 0

            results.append({
                'code':       code,
                'name':       s['name'],
                'sector':     s['sector'],
                'price':      price,
                'prev_price': prev_cls,
                'open_price': open_prc,
                'high':       high,
                'low':        low,
                'volume':     volume,
                'return_pct': ret,         # 전일 종가 대비
                'open_ret':   open_ret,    # 시가 대비
            })
        except:
            errors.append(s['name'])
        time.sleep(CALL_DELAY)

    return results, errors


def build_intraday_output(results):
    """장중 모멘텀 JSON 구조."""
    now = datetime.now()
    sectors = build_sector_ranking(results)
    sorted_all = sorted(results, key=lambda x: -x['return_pct'])

    return {
        'updated':      now.strftime('%Y-%m-%d %H:%M'),
        'period':       'intraday',
        'label':        '장중 모멘텀 (전일 종가 대비)',
        'total_stocks': len(results),
        'sectors':      sectors,
        'top_gainers':  sorted_all[:15],
        'top_losers':   sorted_all[-15:][::-1],
        'stats': {
            'avg_return': round(sum(s['return_pct'] for s in results) / max(len(results), 1), 2),
            'positive':   sum(1 for s in results if s['return_pct'] > 0),
            'negative':   sum(1 for s in results if s['return_pct'] < 0),
            'unchanged':  sum(1 for s in results if s['return_pct'] == 0),
        },
    }


# ── 메인 ──
def main():
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수 필요')
        sys.exit(1)

    # 모드 결정
    args = sys.argv[1:]
    do_weekly   = '--weekly' in args or (not args)
    do_monthly  = '--monthly' in args or (not args)
    do_intraday = '--intraday' in args

    # --intraday 단독 실행 시 weekly/monthly 끄기
    if do_intraday and '--weekly' not in args and '--monthly' not in args:
        do_weekly = False
        do_monthly = False

    os.makedirs(OUT_DIR, exist_ok=True)

    stocks = load_stock_list()
    mode_str = ' '.join(filter(None, [
        '주간' if do_weekly else '',
        '월간' if do_monthly else '',
        '장중' if do_intraday else '',
    ]))
    print(f'📊 모멘텀 분석 (KIS Open API)')
    print(f'   종목: {len(stocks)}개')
    print(f'   모드: {mode_str}')
    print()

    token = get_access_token()

    # ── 장중 모멘텀 (현재가만 수집, 빠름) ──
    if do_intraday:
        print('\n── 장중 모멘텀 (전일 종가 대비) ──')
        results, errs = fetch_intraday(token, stocks)
        if errs:
            print(f'   ❌ 실패 ({len(errs)}): {", ".join(errs[:10])}')
        output = build_intraday_output(results)
        fpath = os.path.join(OUT_DIR, 'intraday.json')
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        _print_summary(output)

    # ── 주간/월간은 일봉 데이터 필요 ──
    if do_weekly or do_monthly:
        print(f'\n📈 일봉 데이터 수집 ({len(stocks)}종목)...')
        stocks_data = []
        errors = []
        for i, s in enumerate(stocks, 1):
            code = s['code']
            if i % 20 == 0 or i == 1:
                print(f'   [{i}/{len(stocks)}] {s["name"]}...')

            daily = fetch_daily_prices(token, code, days=30)
            cur_price = None

            # 실제 현재가도 가져오기 (수정주가 vs 실제 가격 차이 보정)
            if daily:
                cur_price = fetch_current_price(token, code)
                time.sleep(CALL_DELAY)

            if not daily or len(daily) < 3:
                errors.append(s['name'])
                time.sleep(CALL_DELAY)
                continue

            stocks_data.append({
                'code':          code,
                'name':          s['name'],
                'sector':        s['sector'],
                'daily':         daily,
                'current_price': cur_price,
            })
            time.sleep(CALL_DELAY)

        print(f'\n   수집 완료: {len(stocks_data)}/{len(stocks)}')
        if errors:
            print(f'   ❌ 실패 ({len(errors)}): {", ".join(errors[:10])}')

        # 주간 모멘텀 (5거래일)
        if do_weekly:
            print('\n── 주간 모멘텀 (5거래일) ──')
            weekly = calc_momentum(stocks_data, 5)
            output = build_output(weekly, 'weekly', 5)
            fpath = os.path.join(OUT_DIR, 'weekly.json')
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            _print_summary(output)

        # 월간 모멘텀 (22거래일)
        if do_monthly:
            print('\n── 월간 모멘텀 (22거래일) ──')
            monthly = calc_momentum(stocks_data, 22)
            output = build_output(monthly, 'monthly', 22)
            fpath = os.path.join(OUT_DIR, 'monthly.json')
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            _print_summary(output)

    print(f'\n{"="*50}')
    print(f'✅ 모멘텀 분석 완료 → {OUT_DIR}/')


def _print_summary(out):
    stats = out['stats']
    print(f'   종목: {out["total_stocks"]}  상승: {stats["positive"]}  하락: {stats["negative"]}  평균: {stats["avg_return"]:+.1f}%')
    print(f'\n   🔥 강세 업종 Top 5:')
    for i, sec in enumerate(out['sectors'][:5], 1):
        print(f'      {i}. {sec["sector"]:8s} {sec["return_pct"]:+6.1f}% ({sec["stock_count"]}종목)')
    print(f'\n   📈 강세 종목 Top 5:')
    for i, s in enumerate(out['top_gainers'][:5], 1):
        print(f'      {i}. {s["name"]:10s} {s["return_pct"]:+6.1f}%  [{s["sector"]}]')
    print(f'\n   📉 약세 종목 Top 3:')
    for i, s in enumerate(out['top_losers'][:3], 1):
        print(f'      {i}. {s["name"]:10s} {s["return_pct"]:+6.1f}%  [{s["sector"]}]')


if __name__ == '__main__':
    main()
