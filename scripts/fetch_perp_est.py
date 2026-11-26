#!/usr/bin/env python3
"""
장 마감 뒤 해외 추정가 — 바이낸스 무기한 선물 (VM 크론 전용, 118)
=================================================================
국내 장이 닫힌 뒤(평일 저녁·밤, 주말, 휴장일)에도 코스피200(118, 하이퍼리퀴드)·삼성전자·SK하이닉스·현대차의
흐름을 보려고, 바이낸스에서 24시간 거래되는 주가 연동 무기한 선물 가격을 받아
「국내 종가 × (선물 지금 가격 ÷ 국내 종가 시각(15:30) 선물 가격)」으로 원화 추정가를 만든다.

  - 환율을 곱하지 않고 비율만 쓴다 → 선물과 현물 사이 가격 차(괴리)와
    주말에 멈춘 환율 문제가 빠지고 「국내 장 마감 뒤 얼마나 움직였나」만 남는다.
  - 국내 종가는 ~/sf_live/prices_live.json(fetch_live_prices.py, 평일 15:40까지 갱신)의 마지막 값.
  - 휴장일(prices_live holiday=true)에는 기준을 바꾸지 않고 직전 거래일 기준을 그대로 쓴다.
  - 국내 장중(평일 09:00~15:35, 휴장 아님)에는 바이낸스를 부르지 않고 session=true만 적는다
    → 화면은 「장중에는 실제 시세」 안내.

사용 API (키 없음, 무료): https://fapi.binance.com
  /fapi/v1/ticker/24hr?symbol=…   지금 가격·24시간 거래대금(USDT)
  /fapi/v1/klines?symbol=…&interval=1m&startTime=…&limit=1   15:29 KST 1분봉 종가 = 15:30 가격

(124) 미국 주요 종목도 같이 — 하이퍼리퀴드 xyz 무기한 선물(엔비디아·마이크론·테슬라·스페이스X·앤트로픽·S&P500·나스닥100).
  추정가 = 미국 직전 정규장 종가(야후) × (선물 지금 ÷ 그날 16:00 ET 선물). 국내 장중에도 계속 받음(낮엔 미국이 닫혀 있어서).
  기준은 하루 한 번(미국 장 마감 뒤) 잡고, 못 잡으면 10분 뒤 다시. 출력 칸 'us'.
  종목 주식은 종가 시각 선물이 종가와 15% 넘게 다르면 다른 상품으로 보고 뺌(로그 ⚠). 지수는 선물 단위가 달라도 비율만 써서 검사 안 함.
  반일장(추수감사절 다음 날 등 13:00 마감)도 16:00 선물을 기준으로 씀 — 3시간 차이만큼 조금 어긋날 수 있음.

크론: 1분마다(118에서 2분→1분). 출력: ~/sf_live/perp_est.json (레포 밖) → api_server /api/perp/est → /today/
사용법
  python3 scripts/fetch_perp_est.py          # 크론용
  python3 scripts/fetch_perp_est.py --force  # 장중이어도 1회 수집 (테스트)
주의: 실제 주식이 아니라 역외 고배율 파생상품 가격. 주말엔 거래가 얇아 한쪽으로 쏠리기 쉬움 — 참고용.
"""

import os, sys, json, time, fcntl
import urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KST = timezone(timedelta(hours=9))
BASE = os.environ.get('PERP_API_BASE', 'https://fapi.binance.com')   # 테스트 때만 바꿈
HL_URL = os.environ.get('HL_API_URL', 'https://api.hyperliquid.xyz/info')
# 코스피200 — 바이낸스엔 없음 → 하이퍼리퀴드 HIP-3(xyz 거래소) 무기한 선물. 종가는 야후 ^KS200 (118)
K200 = {'code': 'K200', 'name': '코스피200', 'sym': 'xyz:KR200', 'dex': 'xyz', 'yahoo': '^KS200'}
K200_RETRY = 600   # 기준(종가·15:30 선물)을 못 받으면 10분 뒤 다시

# (124) 미국 주요 종목 — (코드, 이름, 하이퍼리퀴드 기호, 야후 기호, 종류). 기호는 124 VM에서 확인
ET = ZoneInfo('America/New_York')
US = [
    ('NVDA', '엔비디아',   'xyz:NVDA',   'NVDA',  'stock'),
    ('MU',   '마이크론',   'xyz:MU',     'MU',    'stock'),
    ('TSLA', '테슬라',     'xyz:TSLA',   'TSLA',  'stock'),
    ('SPCX', '스페이스X',  'xyz:SPCX',   'SPCX',  'stock'),
    ('ANT',  '앤트로픽',   'xyz:ANT',    'ANT',   'stock'),
    ('SPX',  'S&P500',     'xyz:SP500',  '^GSPC', 'index'),
    ('NDX',  '나스닥100',  'xyz:XYZ100', '^NDX',  'index'),
]
US_RETRY = 600
US_SANITY = 0.15   # 종목: 종가 시각 선물이 종가와 이만큼 넘게 다르면 다른 상품으로 봄

# (종목코드, 이름, 바이낸스 기호) — 118 VM에서 확인한 기호
ITEMS = [
    ('005930', '삼성전자',   'SAMSUNGUSDT'),
    ('000660', 'SK하이닉스', 'SKHYNIXUSDT'),
    ('005380', '현대차',     'HYUNDAIUSDT'),
]

LIVE_DIR   = os.path.expanduser(os.environ.get('SF_LIVE_DIR', '~/sf_live'))
PRICE_FILE = os.path.join(LIVE_DIR, 'prices_live.json')
OUT_FILE   = os.path.join(LIVE_DIR, 'perp_est.json')
STATE_FILE = os.path.join(LIVE_DIR, '.perp_state.json')
LOCK_FILE  = os.path.join(LIVE_DIR, '.perp.lock')
HIST_MAX   = 24 * 30   # 추이 점 최대 개수 (점 간격 2분 → 약 24시간)
HIST_STEP  = 120       # 추이 점 간격(초) — 이보다 촘촘하면 마지막 점을 덮어씀


def log(msg):
    print(f'[{datetime.now(KST).strftime("%m-%d %H:%M:%S")}] {msg}', flush=True)


def read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def write_json_atomic(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def get(path, params):
    url = BASE + path + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'swingfarmer-perp/1.0'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def hl_post(body):
    req = urllib.request.Request(HL_URL, data=json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json', 'User-Agent': 'swingfarmer-perp/1.0'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def k200_base(state, base):
    """코스피200 기준(그날 종가·15:30 선물). 못 받으면 base에 안 넣고 10분 뒤 다시."""
    if not base or base.get('k200'):
        return
    if time.time() - state.get('k200_try', 0) < K200_RETRY:
        return
    state['k200_try'] = time.time()
    d = base['date']
    try:
        import yfinance as yf
        nd = (datetime.strptime(d, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        h = yf.Ticker(K200['yahoo']).history(start=d, end=nd)
        rows = [(i.strftime('%Y-%m-%d'), float(c)) for i, c in zip(h.index, h['Close'])]
        close = next((c for dd, c in rows if dd == d and c > 0), None)
    except Exception as e:
        log(f'⚠ 코스피200 종가(야후) 실패: {e}')
        close = None
    if not close:
        log(f'⚠ 코스피200 {d} 종가 아직 없음 — 10분 뒤 다시')
        return
    ms = int(datetime.strptime(d + ' 15:29', '%Y-%m-%d %H:%M').replace(tzinfo=KST).timestamp() * 1000)
    try:
        c = hl_post({'type': 'candleSnapshot', 'req': {'coin': K200['sym'], 'interval': '1m',
                                                       'startTime': ms, 'endTime': ms + 59999}})
        perp = next((float(x['c']) for x in (c or []) if int(x.get('t', 0)) == ms), None)
    except Exception as e:
        log(f'⚠ 코스피200 15:30 선물(하이퍼리퀴드) 실패: {e}')
        perp = None
    if not perp:
        log(f'⚠ 코스피200 {d} 15:30 선물 1분봉 없음 — 10분 뒤 다시')
        return
    base['k200'] = {'close': round(close, 2), 'perp': perp}
    state['hist'] = []
    log(f'✅ 코스피200 기준 {d}: 종가 {close:.2f} / 15:30 선물 {perp}')


def xyz_ctx():
    """하이퍼리퀴드 xyz 거래소 전체 시세 한 번에 {기호: ctx}"""
    r = hl_post({'type': 'metaAndAssetCtxs', 'dex': 'xyz'})
    return {u.get('name'): c for u, c in zip(r[0]['universe'], r[1])}


def hl_px(ctx):
    return float(ctx.get('midPx') or ctx.get('markPx') or 0)


def k200_item(base, xyz):
    b = base.get('k200')
    if not b:
        return None
    ctx = xyz[K200['sym']]
    last = hl_px(ctx)
    if last <= 0:
        raise ValueError('가격 0')
    ratio = last / b['perp']
    est = round(b['close'] * ratio, 2)
    return {'code': K200['code'], 'name': K200['name'], 'sym': K200['sym'], 'kind': 'index',
            'close': b['close'], 'est': est, 'chg': round(est - b['close'], 2), 'pct': round((ratio - 1) * 100, 2),
            'usd': round(last, 4), 'usd_base': b['perp'], 'qv': round(float(ctx.get('dayNtlVlm') or 0)),
            'tt': 0, 'src': '하이퍼리퀴드'}


# ── (124) 미국 주요 종목 ──
def us_target_date(now_et):
    """정규장 마감(16:00 ET)이 지난 가장 최근 평일 (휴장일은 모름 → 야후에 그날 봉이 없으면 그 전날 종가를 씀)"""
    d = now_et.date()
    if now_et.weekday() < 5 and now_et.hour >= 16:
        return d
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def us_base(state, now):
    """미국 기준 {date, target, close:{code}, perp:{code}} — 하루 한 번, 실패·휴장이면 10분 뒤 다시"""
    now_et = now.astimezone(ET)
    target = us_target_date(now_et).isoformat()
    b = state.get('us_base')
    if b and b.get('target') == target and b.get('date') == target:
        return b
    if time.time() - state.get('us_try', 0) < US_RETRY:
        return b
    state['us_try'] = time.time()
    try:
        import yfinance as yf
        df = yf.download([y for _, _, _, y, _ in US], period='10d', interval='1d', progress=False,
                         auto_adjust=False, group_by='ticker', threads=False)
    except Exception as e:
        log(f'⚠ 미국 종가(야후) 실패: {e}')
        return b
    close, cdate = {}, {}
    for code, _, _, y, _ in US:
        try:
            ser = df[y]['Close'].dropna()
            rows = [(i.strftime('%Y-%m-%d'), float(v)) for i, v in zip(ser.index, ser) if i.strftime('%Y-%m-%d') <= target and v > 0]
            if rows:
                cdate[code], close[code] = rows[-1]
        except Exception:
            pass
    if not close:
        log('⚠ 미국 종가 하나도 못 받음 — 10분 뒤 다시')
        return b
    d = max(cdate.values())
    close = {c: v for c, v in close.items() if cdate[c] == d}
    if b and b.get('date') == d and b.get('perp'):
        b['target'] = target   # 휴장일 등 — 종가 날짜 그대로, 10분마다 다시 확인
        return b
    t = datetime.strptime(d + ' 15:59', '%Y-%m-%d %H:%M').replace(tzinfo=ET)
    ms = int(t.timestamp() * 1000)
    perp = {}
    for code, name, sym, _, kind in US:
        if code not in close:
            continue
        try:
            c = hl_post({'type': 'candleSnapshot', 'req': {'coin': sym, 'interval': '1m', 'startTime': ms, 'endTime': ms + 59999}})
            px = next((float(x['c']) for x in (c or []) if int(x.get('t', 0)) == ms), None)
        except Exception as e:
            log(f'⚠ {sym} 종가 시각 선물 실패: {e}')
            px = None
        if not px:
            log(f'⚠ {sym} {d} 16:00 ET 1분봉 없음')
            continue
        if kind == 'stock' and abs(px / close[code] - 1) > US_SANITY:
            log(f'⚠ {sym} 선물 {px} vs {name} 종가 {close[code]:.2f} — 15% 넘게 달라 뺌(다른 상품인지 기호 확인)')
            continue
        perp[code] = px
        time.sleep(0.2)
    if not perp:
        log(f'⚠ 미국 {d} 종가 시각 선물 하나도 없음 — 10분 뒤 다시')
        return b
    nb = {'date': d, 'target': target, 'close': {c: round(close[c], 4) for c in perp}, 'perp': perp}
    state['us_base'] = nb
    state['us_hist'] = []
    log(f'✅ 미국 기준 {d}: ' + ' · '.join(f'{c} {nb["close"][c]}/{perp[c]}' for c in perp))
    return nb


def us_block(state, now, xyz):
    b = us_base(state, now)
    if not b or xyz is None:
        return None
    items = []
    for code, name, sym, _, kind in US:
        if code not in b['perp'] or sym not in xyz:
            continue
        last = hl_px(xyz[sym])
        if last <= 0:
            continue
        ratio = last / b['perp'][code]
        cl = b['close'][code]
        est = round(cl * ratio, 2)
        items.append({'code': code, 'name': name, 'sym': sym, 'kind': kind, 'close': round(cl, 2), 'est': est,
                      'chg': round(est - cl, 2), 'pct': round((ratio - 1) * 100, 2), 'usd': round(last, 4),
                      'usd_base': b['perp'][code], 'qv': round(float(xyz[sym].get('dayNtlVlm') or 0))})
    if not items:
        return None
    now_et = now.astimezone(ET)
    sess = now_et.weekday() < 5 and (9, 30) <= (now_et.hour, now_et.minute) < (16, 0) and b['date'] < now_et.date().isoformat()
    hist = state.get('us_hist') or []
    ts = int(now.timestamp())
    codes = [c for c, _, _, _, _ in US]
    pt = [ts] + [next((x['pct'] for x in items if x['code'] == c), None) for c in codes]
    if hist and len(hist[-1]) != len(pt):
        hist = []
    if hist and ts - hist[-1][0] < HIST_STEP - 20:
        hist[-1] = pt
    else:
        hist.append(pt)
    state['us_hist'] = hist[-HIST_MAX:]
    return {'base_date': b['date'], 'session': sess, 'items': items, 'hist_codes': codes, 'hist': state['us_hist']}


def in_session(now, holiday_today):
    """국내 정규장(평일 09:00~15:35) 중인지. 휴장일이면 False."""
    if now.weekday() >= 5 or holiday_today:
        return False
    hm = (now.hour, now.minute)
    return (9, 0) <= hm < (15, 35)


def base_from_prices(state):
    """prices_live.json에서 최근 거래일 종가를 읽어 기준(state['base'])을 갱신. 반환: base dict 또는 None."""
    pl = read_json(PRICE_FILE)
    base = state.get('base')
    if not pl or not pl.get('date'):
        return base, False
    holiday = bool(pl.get('holiday'))
    if holiday:
        return base, (pl.get('date') == datetime.now(KST).strftime('%Y-%m-%d'))
    d = pl['date']
    # 그날 15:30 이후에 저장된 파일만 종가로 인정 (장중 값으로 기준을 잡지 않게)
    upd = str(pl.get('updated', ''))
    if upd[11:16] < '15:30':
        return base, False
    if base and base.get('date') == d and all(base.get('close', {}).get(c) for c, _, _ in ITEMS) \
            and all(base.get('perp', {}).get(s) for _, _, s in ITEMS):
        return base, False
    stocks = pl.get('stocks') or {}
    close = {c: (stocks.get(c) or {}).get('p') for c, _, _ in ITEMS}
    if not all(close.values()):
        log(f'⚠ prices_live {d}에 종가 빠짐: {close}')
        return base, False
    # 그날 15:29 KST 1분봉 종가 = 15:30 선물 가격
    t0 = datetime.strptime(d + ' 15:29', '%Y-%m-%d %H:%M').replace(tzinfo=KST)
    ms = int(t0.timestamp() * 1000)
    perp = {}
    for _, _, sym in ITEMS:
        try:
            k = get('/fapi/v1/klines', {'symbol': sym, 'interval': '1m', 'startTime': ms, 'limit': 1})
            if k and int(k[0][0]) == ms:
                perp[sym] = float(k[0][4])
        except Exception as e:
            log(f'⚠ {sym} 15:30 가격 실패: {e}')
        time.sleep(0.2)
    if len(perp) != len(ITEMS):
        log(f'⚠ 15:30 선물 가격 일부 없음 {perp} — 다음 회차에 다시')
        return base, False
    new = {'date': d, 'close': close, 'perp': perp}
    state['base'] = new
    state['hist'] = []   # 기준이 바뀌면 추이도 새로 시작
    log(f'✅ 새 기준 {d}: 종가 {close} / 15:30 선물 {perp}')
    return new, False


# (128) /today/ 지수·환율·금리 칸 — 야후 spark 1회에 8종목(+136 관심 종목 미국 티커). 야후는 비공식이라 5분에 한 번만 부름(하루 288회)
MACRO_SYMS = '^GSPC,^IXIC,^VIX,^TNX,CL=F,KRW=X,JPYKRW=X,GC=F'
# (136) /today/ ⭐ 매수 관심 종목 중 미국 티커 — 같은 야후 호출에 붙여 받고(호출 수 그대로), 결과는 공개 파일(perp_est.json)이 아니라
#       watch_us.json에만 씀(관리자 API /api/watch가 읽음). 목록은 api가 저장하는 ~/sf_live/today_watch.json
WATCH_FILE = os.path.join(os.path.expanduser(os.environ.get('SF_LIVE_DIR', '~/sf_live')), 'today_watch.json')
WATCH_US_FILE = os.path.join(os.path.expanduser(os.environ.get('SF_LIVE_DIR', '~/sf_live')), 'watch_us.json')
WATCH_US_MAX = 12   # 야후 spark 한 번에 20개까지 — 지표 8개 + 12


def watch_us_syms():
    try:
        with open(WATCH_FILE, encoding='utf-8') as f:
            lst = json.load(f)
    except Exception:
        lst = [{'c': 'DAL', 'm': 'us'}]   # 아직 저장 안 했으면 api 기본값과 같게
    out = []
    for x in lst if isinstance(lst, list) else []:
        c = str(x.get('c', ''))
        if x.get('m') == 'us' and c and c not in out and c not in MACRO_SYMS.split(','):
            out.append(c)
    return out[:WATCH_US_MAX]


MACRO_EVERY = 300


def macro_block(state, now):
    m = state.get('macro')
    if m and now.timestamp() - m.get('t', 0) < MACRO_EVERY - 20:
        return m
    wsyms = watch_us_syms()
    url = 'https://query1.finance.yahoo.com/v7/finance/spark?' + urllib.parse.urlencode(
        {'symbols': ','.join([MACRO_SYMS] + wsyms), 'range': '1d', 'interval': '5m'})
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
        items = {}
        for x in (d.get('spark') or {}).get('result') or []:
            meta = ((x.get('response') or [{}])[0].get('meta') or {})
            p, pc = meta.get('regularMarketPrice'), meta.get('chartPreviousClose') or meta.get('previousClose')
            if not p:
                continue
            items[x.get('symbol')] = {'p': p, 'pc': pc, 'r': round((p / pc - 1) * 100, 2) if pc else None,
                                      'mt': meta.get('regularMarketTime')}
        witems = {k: items.pop(k) for k in list(items) if k in wsyms}
        if items:
            m = {'t': int(now.timestamp()), 'items': items}
            state['macro'] = m
        try:   # (136) 관심 종목 미국 시세 — 공개 파일과 따로
            tmp = WATCH_US_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'t': int(now.timestamp()), 'items': witems}, f, ensure_ascii=False)
            os.replace(tmp, WATCH_US_FILE)
        except Exception as e:
            log(f'⚠ 관심 종목 미국 시세 저장 실패: {e}')
    except Exception as e:
        if not m or now.minute % 30 == 0:
            log(f'⚠ 야후 spark 실패: {str(e)[:100]}')
        if m:
            m['t'] = int(now.timestamp()) - MACRO_EVERY + 120   # 실패하면 2분 뒤 다시
    return m


def main():
    force = '--force' in sys.argv
    os.makedirs(LIVE_DIR, exist_ok=True)
    lf = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0

    now = datetime.now(KST)
    state = read_json(STATE_FILE, {}) or {}
    base, holiday_today = base_from_prices(state)

    # (124) 하이퍼리퀴드 xyz 시세는 한 번만 받아 코스피200·미국이 같이 씀
    xyz, us = None, None
    try:
        xyz = xyz_ctx()
    except Exception as e:
        log(f'⚠ 하이퍼리퀴드 시세 실패: {e}')
    try:
        us = us_block(state, now, xyz)
    except Exception as e:
        log(f'⚠ 미국 종목 실패: {e}')

    macro = macro_block(state, now)   # (128)

    if in_session(now, holiday_today) and not force:
        # 국내 장중 — 국내 종목은 안 부르고, 미국만 (124: 예전엔 session만 적고 끝)
        write_json_atomic(OUT_FILE, {'updated': now.strftime('%Y-%m-%dT%H:%M:%S+09:00'), 'session': True, 'us': us, 'macro': macro})
        write_json_atomic(STATE_FILE, state)
        return 0

    if not base:
        log('⚠ 기준(국내 종가) 없음 — prices_live.json이 15:30 뒤에 저장된 적이 있어야 함')
        write_json_atomic(STATE_FILE, state)
        return 1

    k200_base(state, base)
    items, fails = [], []
    try:
        if xyz is None:
            raise ValueError('하이퍼리퀴드 시세 없음')
        k = k200_item(base, xyz)
        if k:
            items.append(k)
    except Exception as e:
        fails.append(f"{K200['sym']}: {e}")
    for code, name, sym in ITEMS:
        try:
            t = get('/fapi/v1/ticker/24hr', {'symbol': sym})
            last = float(t['lastPrice'])
            if last <= 0:
                raise ValueError('가격 0')
        except Exception as e:
            fails.append(f'{sym}: {e}')
            continue
        b, cl = base['perp'][sym], base['close'][code]
        ratio = last / b
        est = round(cl * ratio)
        items.append({
            'code': code, 'name': name, 'sym': sym,
            'close': cl, 'est': est, 'chg': est - cl, 'pct': round((ratio - 1) * 100, 2),
            'usd': round(last, 4), 'usd_base': b,
            'qv': round(float(t.get('quoteVolume') or 0)),        # 24시간 거래대금(USDT)
            'src': '바이낸스',
            'tt': int(t.get('closeTime') or 0),                    # 마지막 체결 시각(ms)
        })
        time.sleep(0.2)
    if fails:
        log('⚠ ' + ' / '.join(fails))
    if not items and not us:
        write_json_atomic(STATE_FILE, state)
        return 1

    # 추이(변화율) — 2분 간격 점, 기준일이 바뀌면 처음부터
    hist = state.get('hist') or []
    ts = int(now.timestamp())
    codes = [K200['code']] + [c for c, _, _ in ITEMS]
    pt = [ts] + [next((x['pct'] for x in items if x['code'] == c), None) for c in codes]
    if hist and len(hist[-1]) != len(pt):
        hist = []   # (118) 칸 수가 바뀌면(코스피200 추가) 추이 새로
    if hist and ts - hist[-1][0] < HIST_STEP - 20:
        hist[-1] = pt
    else:
        hist.append(pt)
    state['hist'] = hist[-HIST_MAX:]

    out = {
        'updated': now.strftime('%Y-%m-%dT%H:%M:%S+09:00'),
        'session': False,
        'base_date': base['date'],
        'items': items,
        'hist_codes': codes,
        'hist': state['hist'],
        'source': '바이낸스·하이퍼리퀴드 무기한 선물',
        'us': us,
        'macro': macro,   # (128) 야후 지수·환율·금리·유가 (5분마다)
    }
    write_json_atomic(OUT_FILE, out)
    write_json_atomic(STATE_FILE, state)
    if force or now.minute % 30 == 0:
        log('✅ ' + ' · '.join(f"{x['name']} {x['pct']:+.2f}%" for x in items) + f" (기준 {base['date']})")
        if us:
            log('✅ 미국 ' + ' · '.join(f"{x['name']} {x['pct']:+.2f}%" for x in us['items']) + f" (기준 {us['base_date']})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
