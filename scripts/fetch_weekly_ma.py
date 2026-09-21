"""
5주선(5WMA) 돌파/이탈 스크리너
==============================
KIS Open API 주봉 데이터로 5주 이동평균선 돌파/이탈 판정.

시그널:
  - 신규 돌파: 이번 주 종가 > 5WMA, 직전 주 종가 ≤ 5WMA
  - 신규 이탈: 이번 주 종가 < 5WMA, 직전 주 종가 ≥ 5WMA
  - N주 연속 유지/이탈 추적

대상: KOSPI 시총 1조↑ + KOSDAQ 시총 5천억↑

환경변수:
  KIS_APP_KEY, KIS_APP_SECRET (필수)

출력:
  data/kr/weekly_ma/latest.json       (최신 결과)
  data/kr/weekly_ma/state.json        (연속 주수 상태 — 누적)
  data/kr/weekly_ma/YYYY-MM-DD.json   (주별 아카이브)
  data/kr/weekly_ma/index.json        (날짜 목록)

실행: 매주 금요일 20:50 (cron)
"""

import os, sys, json, time
import urllib.request
from datetime import date, datetime, timedelta

# ── 설정 ──
KIS_APP_KEY    = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE       = os.environ.get('KIS_BASE_URL',
                                'https://openapi.koreainvestment.com:9443')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '')

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR    = os.path.dirname(SCRIPT_DIR)
STOCK_LIST  = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
KOSDAQ_LIST = os.path.join(SCRIPT_DIR, 'kosdaq_list.csv')
OUT_DIR     = os.path.join(ROOT_DIR, 'data', 'kr', 'weekly_ma')
STATE_FILE  = os.path.join(OUT_DIR, 'state.json')
INDEX_FILE  = os.path.join(OUT_DIR, 'index.json')

CALL_DELAY  = 0.08
WEEKLY_BARS = 8       # 5WMA 계산에 최소 5봉 + 직전 비교 여유

os.makedirs(OUT_DIR, exist_ok=True)


# ── 유틸 ──
def safe_int(v):
    try:
        return int(str(v).replace(',', ''))
    except:
        return 0

def safe_float(v):
    try:
        return float(str(v).replace(',', ''))
    except:
        return 0.0


def load_stock_list():
    """KOSPI + KOSDAQ 종목 리스트 로드."""
    stocks = []
    for path, market in [(STOCK_LIST, 'KOSPI'), (KOSDAQ_LIST, 'KOSDAQ')]:
        if not os.path.exists(path):
            print(f'  ⚠️ {os.path.basename(path)} 없음 — {market} 건너뜀')
            continue
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(',')
                if len(parts) >= 2:
                    stocks.append({
                        'code': parts[0].strip(),
                        'name': parts[1].strip(),
                        'sector': parts[2].strip() if len(parts) > 2 else '',
                        'market': market,
                    })
    print(f'📋 종목 로드: {len(stocks)}개')
    return stocks


# ── KIS API ──
def kis_request(url, token, tr_id):
    req = urllib.request.Request(url, headers={
        'Content-Type':  'application/json; charset=UTF-8',
        'authorization': f'Bearer {token}',
        'appkey':        KIS_APP_KEY,
        'appsecret':     KIS_APP_SECRET,
        'tr_id':         tr_id,
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('rt_cd') != '0':
            return None
        return data
    except Exception as e:
        return None


def get_access_token():
    url = f'{KIS_BASE}/oauth2/tokenP'
    body = json.dumps({
        'grant_type': 'client_credentials',
        'appkey': KIS_APP_KEY,
        'appsecret': KIS_APP_SECRET,
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


def fetch_weekly(token, code, end_date):
    """종목별 주봉 OHLCV (최근 8주)."""
    start = (datetime.strptime(end_date, '%Y%m%d') -
             timedelta(days=70)).strftime('%Y%m%d')
    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/'
           f'inquire-daily-itemchartprice'
           f'?FID_COND_MRKT_DIV_CODE=J'
           f'&FID_INPUT_ISCD={code}'
           f'&FID_INPUT_DATE_1={start}'
           f'&FID_INPUT_DATE_2={end_date}'
           f'&FID_PERIOD_DIV_CODE=W'
           f'&FID_ORG_ADJ_PRC=0')
    data = kis_request(url, token, 'FHKST03010100')
    if not data:
        return []
    rows = data.get('output2', [])
    result = []
    for r in rows:
        d = r.get('stck_bsop_date', '')
        if not d:
            continue
        result.append({
            'date':  d,
            'close': safe_int(r.get('stck_clpr')),
        })
    result.sort(key=lambda x: x['date'])
    return result


def calc_5wma(weekly_bars):
    """5주 이동평균 계산. 최소 5봉 필요."""
    if len(weekly_bars) < 5:
        return None, None, None
    # 최신 5봉으로 현재 5WMA
    recent5 = weekly_bars[-5:]
    wma_now = sum(b['close'] for b in recent5) / 5
    close_now = weekly_bars[-1]['close']

    # 직전 주 5WMA (있으면)
    if len(weekly_bars) >= 6:
        prev5 = weekly_bars[-6:-1]
        wma_prev = sum(b['close'] for b in prev5) / 5
        close_prev = weekly_bars[-2]['close']
    else:
        wma_prev = None
        close_prev = None

    return {
        'close': close_now,
        'wma5': round(wma_now),
        'above': close_now >= wma_now,
        'close_prev': close_prev,
        'wma5_prev': round(wma_prev) if wma_prev else None,
        'above_prev': close_prev >= wma_prev if wma_prev and close_prev else None,
        'week_date': weekly_bars[-1]['date'],
    }


# ── 텔레그램 ──
def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print('  ⚠️ 텔레그램 미설정 — 알림 생략')
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    body = json.dumps({
        'chat_id': TELEGRAM_CHAT,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
    })
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f'  ⚠️ 텔레그램 전송 실패: {e}')


# ── 메인 ──
def main():
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수 필요')
        sys.exit(1)

    today = date.today()
    today_str = today.strftime('%Y%m%d')
    date_label = today.strftime('%Y-%m-%d')

    print(f'📊 5주선 스크리너 시작: {date_label}')

    token = get_access_token()
    stocks = load_stock_list()
    if not stocks:
        print('❌ 종목 리스트 없음')
        sys.exit(1)

    # 이전 상태 로드 (연속 주수 추적)
    prev_state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            prev_state = json.load(f)

    results = []
    new_breakouts = []    # 신규 돌파
    new_breakdowns = []   # 신규 이탈
    consecutive_up = []   # 연속 돌파 유지
    consecutive_dn = []   # 연속 이탈 유지
    errors = 0

    for i, stock in enumerate(stocks):
        code = stock['code']
        name = stock['name']

        bars = fetch_weekly(token, code, today_str)
        time.sleep(CALL_DELAY)

        if len(bars) < 5:
            errors += 1
            continue

        calc = calc_5wma(bars)
        if not calc:
            errors += 1
            continue

        above_now  = calc['above']
        above_prev = calc['above_prev']

        # 연속 주수 계산
        prev = prev_state.get(code, {})
        prev_weeks = prev.get('weeks', 0)
        prev_dir   = prev.get('direction', None)  # 'up' or 'down'

        if above_now:
            direction = 'up'
            if prev_dir == 'up':
                weeks = prev_weeks + 1
            else:
                weeks = 1
        else:
            direction = 'down'
            if prev_dir == 'down':
                weeks = prev_weeks + 1
            else:
                weeks = 1

        # 시그널 분류
        signal = None
        if above_prev is not None:
            if above_now and not above_prev:
                signal = 'new_breakout'
                new_breakouts.append({'code': code, 'name': name,
                    'market': stock['market'], 'sector': stock.get('sector',''),
                    'close': calc['close'], 'wma5': calc['wma5']})
            elif not above_now and above_prev:
                signal = 'new_breakdown'
                new_breakdowns.append({'code': code, 'name': name,
                    'market': stock['market'], 'sector': stock.get('sector',''),
                    'close': calc['close'], 'wma5': calc['wma5']})
            elif above_now and above_prev and weeks >= 2:
                signal = 'hold_above'
                consecutive_up.append({'code': code, 'name': name,
                    'market': stock['market'], 'weeks': weeks,
                    'close': calc['close'], 'wma5': calc['wma5']})
            elif not above_now and not above_prev and weeks >= 2:
                signal = 'hold_below'
                consecutive_dn.append({'code': code, 'name': name,
                    'market': stock['market'], 'weeks': weeks,
                    'close': calc['close'], 'wma5': calc['wma5']})

        entry = {
            'code': code,
            'name': name,
            'market': stock['market'],
            'sector': stock.get('sector', ''),
            'close': calc['close'],
            'wma5': calc['wma5'],
            'above': above_now,
            'direction': direction,
            'weeks': weeks,
            'signal': signal,
            'week_date': calc['week_date'],
        }
        results.append(entry)

        # 진행률
        if (i + 1) % 30 == 0:
            print(f'  진행: {i+1}/{len(stocks)}')

    print(f'\n📈 처리 완료: {len(results)}개 (에러 {errors})')
    print(f'  🟢 신규 돌파: {len(new_breakouts)}')
    print(f'  🔴 신규 이탈: {len(new_breakdowns)}')
    print(f'  📊 연속 유지: {len(consecutive_up)}')
    print(f'  📉 연속 이탈: {len(consecutive_dn)}')

    # ── 상태 저장 (연속 주수 누적) ──
    new_state = {}
    for r in results:
        new_state[r['code']] = {
            'direction': r['direction'],
            'weeks': r['weeks'],
            'close': r['close'],
            'wma5': r['wma5'],
        }
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(new_state, f, ensure_ascii=False, indent=1)

    # ── 결과 JSON ──
    output = {
        'date': date_label,
        'total': len(results),
        'new_breakouts': sorted(new_breakouts, key=lambda x: x['name']),
        'new_breakdowns': sorted(new_breakdowns, key=lambda x: x['name']),
        'consecutive_above': sorted(consecutive_up, key=lambda x: -x['weeks']),
        'consecutive_below': sorted(consecutive_dn, key=lambda x: -x['weeks']),
        'all': results,
    }

    # latest.json
    latest_path = os.path.join(OUT_DIR, 'latest.json')
    with open(latest_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=1)

    # 날짜별 아카이브
    archive_path = os.path.join(OUT_DIR, f'{date_label}.json')
    with open(archive_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=1)

    # index.json 갱신
    index = []
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            index = json.load(f)
    if date_label not in index:
        index.append(date_label)
        index.sort(reverse=True)
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False)

    # ── 텔레그램 알림 ──
    lines = [f'📊 <b>5주선 스크리너 — {date_label}</b>\n']

    if new_breakouts:
        lines.append(f'🟢 <b>신규 돌파 ({len(new_breakouts)})</b>')
        for s in new_breakouts[:15]:
            gap = round((s['close']/s['wma5']-1)*100, 1)
            lines.append(f"  {s['name']}({s['market']}) {s['close']:,}원 ({gap:+.1f}%)")
        lines.append('')

    if new_breakdowns:
        lines.append(f'🔴 <b>신규 이탈 ({len(new_breakdowns)})</b>')
        for s in new_breakdowns[:15]:
            gap = round((s['close']/s['wma5']-1)*100, 1)
            lines.append(f"  {s['name']}({s['market']}) {s['close']:,}원 ({gap:+.1f}%)")
        lines.append('')

    if consecutive_up:
        top5 = consecutive_up[:5]
        lines.append(f'📈 <b>연속 유지 Top5</b>')
        for s in top5:
            lines.append(f"  {s['name']} — {s['weeks']}주 연속")
        lines.append('')

    if not new_breakouts and not new_breakdowns:
        lines.append('변동 없음 — 신규 돌파/이탈 종목 없음')

    msg = '\n'.join(lines)
    send_telegram(msg)
    print(f'\n✅ 저장 완료: {date_label}')


if __name__ == '__main__':
    main()
