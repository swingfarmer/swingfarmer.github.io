"""
이평선 시그널 스크리너 (10WMA 비율 + 5WMA 이탈)
================================================
1. 10WMA/종가 비율 구간 알림
   - ≤80%: 재매수 관점 (상승장 정상)
   - ≤70%: 반환점 — 기세 확인
   - ≤60%: 매도 구간
2. 5WMA 30%+ 상승 후 이탈 알림
   - 1차 이탈: 분할매도 1차
   - 2차 이탈: 매도 고려

대상: KOSPI 시총 1조↑ + KOSDAQ 5천억↑ (전 종목)
크론: 매주 금요일 21:05

환경변수: KIS_APP_KEY, KIS_APP_SECRET, ORACLE_DB_PASSWORD,
          ORACLE_WALLET_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
          TELEGRAM_CHANNEL_ID

출력:
  data/kr/ma_signal/latest.json   (최신 전체 결과)
  data/kr/ma_signal/state.json    (라이드 상태 누적)
  Oracle MA_SIGNALS 테이블         (시그널 이력)
"""

import os, sys, json, time
import urllib.request
from datetime import date, datetime, timedelta

# ── 환경 ──
def load_env():
    f = os.path.expanduser('~/.env_secrets')
    if os.path.exists(f):
        for line in open(f):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:]
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
load_env()

KIS_APP_KEY    = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
KIS_BASE       = os.environ.get('KIS_BASE_URL',
                                'https://openapi.koreainvestment.com:9443')
WALLET_DIR     = os.path.expanduser('~/wallet')

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR    = os.path.dirname(SCRIPT_DIR)
STOCK_LIST  = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
KOSDAQ_LIST = os.path.join(SCRIPT_DIR, 'kosdaq_list.csv')
OUT_DIR     = os.path.join(ROOT_DIR, 'data', 'kr', 'ma_signal')
STATE_FILE  = os.path.join(OUT_DIR, 'state.json')
LATEST_FILE = os.path.join(OUT_DIR, 'latest.json')

CALL_DELAY  = 0.08
DAYS_BACK   = 500    # ~71주 주봉

os.makedirs(OUT_DIR, exist_ok=True)

# telegram
sys.path.insert(0, SCRIPT_DIR)
from telegram_helper import send_all


# ── 종목 로드 ──
def load_stock_list():
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
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    token = data.get('access_token', '')
    if not token:
        print(f'❌ 토큰 발급 실패: {data}')
        sys.exit(1)
    print('🔑 토큰 발급 완료')
    return token


def fetch_weekly_bars(token, code):
    """주봉 데이터 (~71주)."""
    end_date = date.today().strftime('%Y%m%d')
    start_date = (date.today() - timedelta(days=DAYS_BACK)).strftime('%Y%m%d')

    url = (f'{KIS_BASE}/uapi/domestic-stock/v1/quotations/'
           f'inquire-daily-itemchartprice'
           f'?FID_COND_MRKT_DIV_CODE=J'
           f'&FID_INPUT_ISCD={code}'
           f'&FID_INPUT_DATE_1={start_date}'
           f'&FID_INPUT_DATE_2={end_date}'
           f'&FID_PERIOD_DIV_CODE=W'
           f'&FID_ORG_ADJ_PRC=0')

    req = urllib.request.Request(url, headers={
        'Content-Type':  'application/json; charset=UTF-8',
        'authorization': f'Bearer {token}',
        'appkey':        KIS_APP_KEY,
        'appsecret':     KIS_APP_SECRET,
        'tr_id':         'FHKST03010100',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('rt_cd') != '0':
            return []
        rows = data.get('output2', [])
        result = []
        for r in rows:
            d = r.get('stck_bsop_date', '')
            if not d:
                continue
            c = int(r.get('stck_clpr', 0))
            if c <= 0:
                continue
            result.append({
                'date':  d,
                'close': c,
                'high':  int(r.get('stck_hgpr', 0)),
                'low':   int(r.get('stck_lwpr', 0)),
            })
        result.sort(key=lambda x: x['date'])
        return result
    except Exception as e:
        return []


# ── 이동평균 ──
def add_ma(bars):
    for i, bar in enumerate(bars):
        bar['wma5']  = round(sum(bars[j]['close'] for j in range(i-4, i+1)) / 5) if i >= 4 else None
        bar['wma10'] = round(sum(bars[j]['close'] for j in range(i-9, i+1)) / 10) if i >= 9 else None
    return bars


# ── Oracle DB ──
def get_db():
    import oracledb
    return oracledb.connect(
        user='ADMIN',
        password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium',
        config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))


def ensure_table(conn):
    """MA_SIGNALS 테이블 없으면 생성."""
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM user_tables WHERE table_name = 'MA_SIGNALS'
    """)
    if cur.fetchone()[0] == 0:
        print('📦 MA_SIGNALS 테이블 생성...')
        cur.execute("""
            CREATE TABLE MA_SIGNALS (
                id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                stock_code    VARCHAR2(10)  NOT NULL,
                stock_name    VARCHAR2(50),
                signal_date   VARCHAR2(10)  NOT NULL,
                signal_type   VARCHAR2(20)  NOT NULL,
                close_price   NUMBER,
                wma5          NUMBER,
                wma10         NUMBER,
                wma10_ratio   NUMBER(5,1),
                ride_start_price NUMBER,
                ride_peak_price  NUMBER,
                ride_gain_pct    NUMBER(6,2),
                peak_drop_pct    NUMBER(6,2),
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_ma_signal UNIQUE (stock_code, signal_date, signal_type)
            )
        """)
        conn.commit()
        print('  ✅ 테이블 생성 완료')


def save_signal(conn, sig):
    """시그널 1건 DB 저장 (중복 무시)."""
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO MA_SIGNALS
                (stock_code, stock_name, signal_date, signal_type,
                 close_price, wma5, wma10, wma10_ratio,
                 ride_start_price, ride_peak_price, ride_gain_pct, peak_drop_pct)
            VALUES
                (:code, :name, :sdate, :stype,
                 :close, :wma5, :wma10, :ratio,
                 :rstart, :rpeak, :rgain, :pdrop)
        """, {
            'code':   sig.get('code'),
            'name':   sig.get('name'),
            'sdate':  sig.get('signal_date'),
            'stype':  sig.get('signal_type'),
            'close':  sig.get('close'),
            'wma5':   sig.get('wma5'),
            'wma10':  sig.get('wma10'),
            'ratio':  sig.get('ratio'),
            'rstart': sig.get('ride_start_price'),
            'rpeak':  sig.get('ride_peak_price'),
            'rgain':  sig.get('ride_gain_pct'),
            'pdrop':  sig.get('peak_drop_pct'),
        })
        conn.commit()
        return True
    except Exception as e:
        if 'ORA-00001' in str(e):  # unique constraint
            return False
        print(f'  ⚠️ DB 저장 실패 ({sig.get("name")}): {e}')
        conn.rollback()
        return False


# ── 분석 엔진 ──
def get_ratio_bucket(ratio):
    """10WMA/종가 비율 구간."""
    if ratio > 80:
        return 'above_80'
    elif ratio > 70:
        return '70_80'
    elif ratio > 60:
        return '60_70'
    else:
        return 'below_60'


def analyze_stock(bars, prev_state):
    """
    종목 1개 분석.
    Returns: (current_state, signals[])
    """
    if len(bars) < 10:
        return None, []

    bars = add_ma(bars)
    latest = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else None

    if latest['wma5'] is None or latest['wma10'] is None:
        return None, []

    close = latest['close']
    wma5  = latest['wma5']
    wma10 = latest['wma10']
    above_5  = close >= wma5
    above_10 = close > wma10

    signals = []
    date_label = f'{latest["date"][:4]}-{latest["date"][4:6]}-{latest["date"][6:]}'

    # ── 10WMA/종가 비율 (상승장만) ──
    ratio = round(wma10 / close * 100, 1) if close > 0 else 100
    ratio_bucket = get_ratio_bucket(ratio) if above_10 else 'downtrend'

    prev_bucket = prev_state.get('ratio_bucket', 'above_80')

    # 새로 진입한 구간만 알림 (이전보다 악화된 경우)
    bucket_rank = {'above_80': 0, '70_80': 1, '60_70': 2, 'below_60': 3, 'downtrend': -1}
    curr_rank = bucket_rank.get(ratio_bucket, -1)
    prev_rank = bucket_rank.get(prev_bucket, -1)

    if above_10 and curr_rank > prev_rank and curr_rank >= 1:
        if ratio_bucket == 'below_60':
            signals.append({
                'signal_type': 'ratio_60',
                'signal_date': date_label,
                'ratio': ratio,
            })
        elif ratio_bucket == '60_70':
            signals.append({
                'signal_type': 'ratio_70',
                'signal_date': date_label,
                'ratio': ratio,
            })
        elif ratio_bucket == '70_80':
            signals.append({
                'signal_type': 'ratio_80',
                'signal_date': date_label,
                'ratio': ratio,
            })

    # ── 5WMA 라이드 추적 ──
    prev_above_5 = prev_state.get('above_5wma', False)
    ride_start   = prev_state.get('ride_start_price')
    ride_peak    = prev_state.get('ride_peak', 0)
    threshold_hit = prev_state.get('threshold_hit', False)
    break_count  = prev_state.get('break_count', 0)

    # 새 돌파 → 라이드 시작
    if above_5 and not prev_above_5 and ride_start is None:
        ride_start = close
        ride_peak = close
        threshold_hit = False
        break_count = 0

    # 라이드 중 고점 갱신
    if above_5 and ride_start is not None:
        if close > ride_peak:
            ride_peak = close
        gain = (close / ride_start - 1) * 100 if ride_start > 0 else 0
        if gain >= 30:
            threshold_hit = True

    # 이탈 감지
    if not above_5 and prev_above_5 and ride_start is not None and threshold_hit:
        break_count += 1
        gain_now  = round((close / ride_start - 1) * 100, 2) if ride_start > 0 else 0
        peak_drop = round((close / ride_peak - 1) * 100, 2) if ride_peak > 0 else 0

        if break_count == 1:
            signals.append({
                'signal_type': 'break_1st',
                'signal_date': date_label,
                'ride_start_price': ride_start,
                'ride_peak_price': ride_peak,
                'ride_gain_pct': gain_now,
                'peak_drop_pct': peak_drop,
            })
        elif break_count == 2:
            signals.append({
                'signal_type': 'break_2nd',
                'signal_date': date_label,
                'ride_start_price': ride_start,
                'ride_peak_price': ride_peak,
                'ride_gain_pct': gain_now,
                'peak_drop_pct': peak_drop,
            })

    # 재돌파 (이탈 후 복귀) — 라이드 이어감
    if above_5 and not prev_above_5 and ride_start is not None:
        pass  # 유지

    # 라이드 완전 종료: 10주선 하회 or 3차 이탈
    if ride_start is not None:
        if (wma10 and close < wma10) or break_count >= 3:
            ride_start = None
            ride_peak = 0
            threshold_hit = False
            break_count = 0

    # 현재 상태
    new_state = {
        'above_5wma':      above_5,
        'close':           close,
        'wma5':            wma5,
        'wma10':           wma10,
        'ratio':           ratio,
        'ratio_bucket':    ratio_bucket,
        'ride_start_price': ride_start,
        'ride_peak':       ride_peak,
        'threshold_hit':   threshold_hit,
        'break_count':     break_count,
    }

    return new_state, signals


# ── 텔레그램 메시지 구성 ──
def build_telegram_msg(date_label, all_signals, summary):
    lines = [f'📊 <b>이평선 시그널 — {date_label}</b>\n']

    # 10WMA 비율 알림 (위험한 순)
    r60 = [s for s in all_signals if s['signal_type'] == 'ratio_60']
    r70 = [s for s in all_signals if s['signal_type'] == 'ratio_70']
    r80 = [s for s in all_signals if s['signal_type'] == 'ratio_80']
    b1  = [s for s in all_signals if s['signal_type'] == 'break_1st']
    b2  = [s for s in all_signals if s['signal_type'] == 'break_2nd']

    if r60:
        lines.append(f'🔴 <b>10WMA 비율 ≤60% — 매도 구간 ({len(r60)})</b>')
        for s in r60:
            lines.append(f"  {s['name']} {s['ratio']:.1f}% (종가 {s['close']:,})")
        lines.append('')

    if r70:
        lines.append(f'⚠️ <b>10WMA 비율 ≤70% — 반환점 ({len(r70)})</b>')
        for s in r70:
            lines.append(f"  {s['name']} {s['ratio']:.1f}% (종가 {s['close']:,})")
        lines.append('')

    if r80:
        lines.append(f'🟢 <b>10WMA 비율 ≤80% — 재매수 관점 ({len(r80)})</b>')
        for s in r80[:10]:
            lines.append(f"  {s['name']} {s['ratio']:.1f}%")
        if len(r80) > 10:
            lines.append(f'  ... 외 {len(r80)-10}종목')
        lines.append('')

    if b1:
        lines.append(f'⚡ <b>5WMA 1차 이탈 — 분할매도 고려 ({len(b1)})</b>')
        for s in b1:
            lines.append(f"  {s['name']} 누적{s['ride_gain_pct']:+.1f}% 고점대비{s['peak_drop_pct']:.1f}%")
        lines.append('')

    if b2:
        lines.append(f'💥 <b>5WMA 2차 이탈 — 매도 고려 ({len(b2)})</b>')
        for s in b2:
            lines.append(f"  {s['name']} 누적{s['ride_gain_pct']:+.1f}% 고점대비{s['peak_drop_pct']:.1f}%")
        lines.append('')

    if not any([r60, r70, r80, b1, b2]):
        lines.append('변동 없음 — 신규 시그널 없음')
        lines.append('')

    # 요약
    lines.append(f"📈 상승장 {summary['uptrend']}종목 / 전체 {summary['total']}")
    active_rides = summary.get('active_rides', 0)
    if active_rides:
        lines.append(f"🚀 30%+ 라이드 진행 중: {active_rides}종목")

    return '\n'.join(lines)


# ── 메인 ──
def main():
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수 필요')
        sys.exit(1)

    today = date.today()
    date_label = today.strftime('%Y-%m-%d')

    print(f'📊 이평선 시그널 스크리너 시작: {date_label}')

    token = get_access_token()
    stocks = load_stock_list()
    if not stocks:
        print('❌ 종목 리스트 없음')
        sys.exit(1)

    # DB 연결 & 테이블 확인
    conn = None
    try:
        conn = get_db()
        ensure_table(conn)
        print('🗄️ Oracle 연결 완료')
    except Exception as e:
        print(f'⚠️ Oracle 연결 실패 — DB 저장 없이 진행: {e}')

    # 이전 상태 로드
    prev_states = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            prev_states = json.load(f)

    new_states = {}
    all_signals = []
    errors = 0
    summary = {'total': 0, 'uptrend': 0, 'active_rides': 0}

    for i, stock in enumerate(stocks):
        code = stock['code']
        name = stock['name']

        bars = fetch_weekly_bars(token, code)
        time.sleep(CALL_DELAY)

        if len(bars) < 10:
            errors += 1
            continue

        prev_st = prev_states.get(code, {})
        new_st, signals = analyze_stock(bars, prev_st)

        if new_st is None:
            errors += 1
            continue

        new_states[code] = new_st
        summary['total'] += 1

        if new_st['ratio_bucket'] != 'downtrend':
            summary['uptrend'] += 1

        if new_st.get('threshold_hit'):
            summary['active_rides'] += 1

        # 시그널에 종목 정보 추가
        for sig in signals:
            sig['code'] = code
            sig['name'] = name
            sig['close'] = new_st['close']
            sig['wma5'] = new_st['wma5']
            sig['wma10'] = new_st['wma10']
            if 'ratio' not in sig:
                sig['ratio'] = new_st['ratio']
            all_signals.append(sig)

            # DB 저장
            if conn:
                save_signal(conn, sig)

        # 진행률
        if (i + 1) % 50 == 0:
            print(f'  진행: {i+1}/{len(stocks)} (시그널 {len(all_signals)}건)')

    print(f'\n📊 처리 완료: {summary["total"]}개 (에러 {errors})')
    print(f'   상승장: {summary["uptrend"]}개')
    print(f'   30%+ 라이드: {summary["active_rides"]}개')
    print(f'   신규 시그널: {len(all_signals)}건')

    # ── 상태 저장 ──
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(new_states, f, ensure_ascii=False, indent=1)

    # ── latest.json ──
    output = {
        'date': date_label,
        'summary': summary,
        'signals': all_signals,
        'all_states': {code: {
            'name': next((s['name'] for s in stocks if s['code'] == code), code),
            **st
        } for code, st in new_states.items()},
    }
    with open(LATEST_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=1)

    # ── 시그널 상세 출력 ──
    if all_signals:
        print('\n── 시그널 상세 ──')
        for s in all_signals:
            print(f"  [{s['signal_type']}] {s['name']} ratio={s.get('ratio','')} "
                  f"gain={s.get('ride_gain_pct','')} peak_drop={s.get('peak_drop_pct','')}")

    # ── 텔레그램 ──
    msg = build_telegram_msg(date_label, all_signals, summary)
    send_all(msg)
    print(f'\n✅ 완료: {date_label}')

    if conn:
        conn.close()


if __name__ == '__main__':
    main()
