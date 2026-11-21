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

크론: 1분마다(118에서 2분→1분). 출력: ~/sf_live/perp_est.json (레포 밖) → api_server /api/perp/est → /today/
사용법
  python3 scripts/fetch_perp_est.py          # 크론용
  python3 scripts/fetch_perp_est.py --force  # 장중이어도 1회 수집 (테스트)
주의: 실제 주식이 아니라 역외 고배율 파생상품 가격. 주말엔 거래가 얇아 한쪽으로 쏠리기 쉬움 — 참고용.
"""

import os, sys, json, time, fcntl
import urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
BASE = os.environ.get('PERP_API_BASE', 'https://fapi.binance.com')   # 테스트 때만 바꿈
HL_URL = os.environ.get('HL_API_URL', 'https://api.hyperliquid.xyz/info')
# 코스피200 — 바이낸스엔 없음 → 하이퍼리퀴드 HIP-3(xyz 거래소) 무기한 선물. 종가는 야후 ^KS200 (118)
K200 = {'code': 'K200', 'name': '코스피200', 'sym': 'xyz:KR200', 'dex': 'xyz', 'yahoo': '^KS200'}
K200_RETRY = 600   # 기준(종가·15:30 선물)을 못 받으면 10분 뒤 다시

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


def k200_item(base):
    b = base.get('k200')
    if not b:
        return None
    r = hl_post({'type': 'metaAndAssetCtxs', 'dex': K200['dex']})
    uni, ctxs = r[0]['universe'], r[1]
    i = next(j for j, u in enumerate(uni) if u.get('name') == K200['sym'])
    ctx = ctxs[i]
    last = float(ctx.get('midPx') or ctx.get('markPx') or 0)
    if last <= 0:
        raise ValueError('가격 0')
    ratio = last / b['perp']
    est = round(b['close'] * ratio, 2)
    return {'code': K200['code'], 'name': K200['name'], 'sym': K200['sym'], 'kind': 'index',
            'close': b['close'], 'est': est, 'chg': round(est - b['close'], 2), 'pct': round((ratio - 1) * 100, 2),
            'usd': round(last, 4), 'usd_base': b['perp'], 'qv': round(float(ctx.get('dayNtlVlm') or 0)),
            'tt': 0, 'src': '하이퍼리퀴드'}


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

    if in_session(now, holiday_today) and not force:
        prev = read_json(OUT_FILE, {}) or {}
        if not prev.get('session'):
            write_json_atomic(OUT_FILE, {'updated': now.strftime('%Y-%m-%dT%H:%M:%S+09:00'), 'session': True})
        return 0

    if not base:
        log('⚠ 기준(국내 종가) 없음 — prices_live.json이 15:30 뒤에 저장된 적이 있어야 함')
        write_json_atomic(STATE_FILE, state)
        return 1

    k200_base(state, base)
    items, fails = [], []
    try:
        k = k200_item(base)
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
    if not items:
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
    }
    write_json_atomic(OUT_FILE, out)
    write_json_atomic(STATE_FILE, state)
    if force or now.minute % 30 == 0:
        log('✅ ' + ' · '.join(f"{x['name']} {x['pct']:+.2f}%" for x in items) + f" (기준 {base['date']})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
