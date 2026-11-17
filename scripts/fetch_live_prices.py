#!/usr/bin/env python3
"""
장중 준실시간 시세 수집 — KIS Open API (VM 크론 전용)
====================================================
종목 리스트(kospi200_list.csv + kosdaq_list.csv, 약 380종목)의 현재가·등락률을
1분마다 수집해서 VM 로컬 파일로 저장. API 서버(/api/prices/live)가 이 파일을 읽어서 내려줌.

  - 히트맵(/heatmap/), 담보비율·평가금액(/margin-ratio/)이 사용
  - 종목 리스트는 update_stock_list.py가 매월 자동 갱신 → 여기도 자동 반영

사용 API
  1순위: 관심종목(멀티종목) 시세조회 [국내주식-205]  — 1회 호출에 30종목
         /uapi/domestic-stock/v1/quotations/intstock-multprice  (tr_id FHKST11300006)
         → 380종목 = 약 13회 호출 (KIS 제한 초당 20회 대비 매우 여유)
  2순위(자동 대체): 주식현재가 시세 (fetch_prices.py와 동일, 종목당 1회)

호출량·차단 방지
  - 토큰은 파일에 캐시해서 만료 전까지 재사용 (하루 1회 발급 수준)
  - 토큰 발급 실패 시 70초 안에는 재시도 안 함 (KIS: 1분 1회 제한)
  - 동시 실행 방지(lock) — 앞 실행이 안 끝났으면 이번 회차는 건너뜀
  - 장 시간(평일 08:59~15:40 KST) 밖에서는 API 호출 없이 즉시 종료
  - 휴장일: 09:10 이후에도 거래량이 전부 0이면 30분간 호출 중단 후 재확인

출력: ~/sf_live/prices_live.json   (레포 밖 — git에 안 올라감)

사용법
  python3 scripts/fetch_live_prices.py           # 크론용 (장 시간에만 동작)
  python3 scripts/fetch_live_prices.py --force   # 수동 테스트 (시간 무시하고 1회 수집)

환경변수: KIS_APP_KEY, KIS_APP_SECRET (없으면 ~/.env_secrets에서 직접 읽음)
"""

import os, sys, json, time, fcntl
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def load_env():
    """~/.env_secrets 직접 로드 (크론에서 source 빠져도 동작하게)."""
    f = os.path.expanduser('~/.env_secrets')
    if not os.path.exists(f):
        return
    for line in open(f, encoding='utf-8'):
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
KIS_BASE       = os.environ.get('KIS_BASE_URL', 'https://openapi.koreainvestment.com:9443')

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
KOSPI_LIST  = os.path.join(SCRIPT_DIR, 'kospi200_list.csv')
KOSDAQ_LIST = os.path.join(SCRIPT_DIR, 'kosdaq_list.csv')

LIVE_DIR    = os.path.expanduser(os.environ.get('SF_LIVE_DIR', '~/sf_live'))
OUT_FILE    = os.path.join(LIVE_DIR, 'prices_live.json')
TOKEN_FILE  = os.path.join(LIVE_DIR, '.kis_token.json')
STATE_FILE  = os.path.join(LIVE_DIR, '.live_state.json')
LOCK_FILE   = os.path.join(LIVE_DIR, '.live.lock')

CHUNK         = 30     # 멀티 시세 1회 최대 종목 수
MULTI_DELAY   = 0.15   # 멀티 호출 간격(초)
SINGLE_DELAY  = 0.07   # 단건 호출 간격(초) — 초당 약 14회
MAX_SINGLE_FILL = 60   # 멀티에서 빠진 종목을 단건으로 메울 때 상한
RUN_START = (8, 59)    # 수집 시작 (KST)
RUN_END   = (15, 40)   # 수집 종료 (KST) — 15:30 종가 확정분까지 받고 끝
OPEN_T    = (9, 0)
CLOSE_T   = (15, 30)


# ───────────────────────── 유틸 ─────────────────────────
def log(msg):
    print(f'[{datetime.now(KST).strftime("%H:%M:%S")}] {msg}', flush=True)


def read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def write_json_atomic(path, obj, private=False):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def to_int(v):
    try:
        return int(float(str(v).replace(',', '')))
    except Exception:
        return 0


def to_float(v):
    try:
        return float(str(v).replace(',', ''))
    except Exception:
        return 0.0


def signed(value, sign_code):
    """KIS 전일대비부호(1상한 2상승 3보합 4하한 5하락) 기준으로 부호 확정."""
    a = abs(value)
    s = str(sign_code or '').strip()
    if s in ('4', '5'):
        return -a
    if s in ('1', '2'):
        return a
    if s == '3':
        return 0 if a == 0 else value
    return value


def load_stock_list():
    stocks = []
    for path, market in ((KOSPI_LIST, 'KOSPI'), (KOSDAQ_LIST, 'KOSDAQ')):
        if not os.path.exists(path):
            log(f'⚠ {path} 없음')
            continue
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(',')
                if len(parts) >= 2 and parts[0].strip():
                    stocks.append({'code': parts[0].strip(), 'name': parts[1].strip(), 'market': market})
    seen, out = set(), []
    for s in stocks:
        if s['code'] not in seen:
            seen.add(s['code'])
            out.append(s)
    return out


# ───────────────────────── 토큰 ─────────────────────────
def get_token(force_new=False):
    """캐시된 토큰 재사용. 만료 10분 전이거나 force_new면 새로 발급."""
    now = time.time()
    cache = read_json(TOKEN_FILE, {}) or {}
    if not force_new and cache.get('token') and cache.get('expires', 0) - now > 600:
        return cache['token']

    # 발급 시도 간격 제한 (KIS: 1분 1회)
    if now - cache.get('last_try', 0) < 70:
        log('⏳ 토큰 발급 대기 중 (직전 시도 후 70초 미경과) — 이번 회차 건너뜀')
        return None
    cache['last_try'] = now
    write_json_atomic(TOKEN_FILE, cache, private=True)

    body = json.dumps({
        'grant_type': 'client_credentials',
        'appkey': KIS_APP_KEY,
        'appsecret': KIS_APP_SECRET,
    }).encode('utf-8')
    req = urllib.request.Request(f'{KIS_BASE}/oauth2/tokenP', data=body,
                                 headers={'Content-Type': 'application/json; charset=UTF-8'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        log(f'❌ 토큰 발급 실패: {e}')
        return None

    token = data.get('access_token', '')
    if not token:
        log(f'❌ 토큰 발급 실패: {str(data)[:200]}')
        return None

    expires = now + 23 * 3600
    exp_str = data.get('access_token_token_expired', '')
    try:
        expires = datetime.strptime(exp_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST).timestamp()
    except Exception:
        try:
            expires = now + int(data.get('expires_in', 0)) if int(data.get('expires_in', 0)) > 0 else expires
        except Exception:
            pass

    write_json_atomic(TOKEN_FILE, {'token': token, 'expires': expires, 'last_try': now}, private=True)
    log(f'🔑 토큰 새로 발급 (만료 {exp_str or "약 23시간 후"})')
    return token


class TokenExpired(Exception):
    pass


def kis_get(path, tr_id, params, token, timeout=10):
    url = f'{KIS_BASE}{path}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, headers={
        'Content-Type': 'application/json; charset=UTF-8',
        'authorization': f'Bearer {token}',
        'appkey': KIS_APP_KEY,
        'appsecret': KIS_APP_SECRET,
        'tr_id': tr_id,
        'custtype': 'P',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode('utf-8'))
        except Exception:
            data = {'rt_cd': '9', 'msg_cd': f'HTTP{e.code}', 'msg1': str(e)}
    except Exception as e:
        return {'rt_cd': '9', 'msg_cd': 'NET', 'msg1': str(e)}

    msg_cd = str(data.get('msg_cd', ''))
    if msg_cd in ('EGW00123', 'EGW00121'):   # 토큰 만료 / 유효하지 않은 토큰
        raise TokenExpired(msg_cd)
    return data


# ───────────────────────── 시세 조회 ─────────────────────────
def fetch_multi(token, chunk):
    """멀티종목 시세 (최대 30종목). 반환: {code: row} 또는 None(호출 실패)."""
    params = {}
    for i, s in enumerate(chunk, 1):
        params[f'FID_COND_MRKT_DIV_CODE_{i}'] = 'J'
        params[f'FID_INPUT_ISCD_{i}'] = s['code']
    data = kis_get('/uapi/domestic-stock/v1/quotations/intstock-multprice', 'FHKST11300006', params, token)
    if str(data.get('rt_cd')) != '0':
        return None, f"{data.get('msg_cd','')} {data.get('msg1','')}".strip()
    rows = data.get('output') or []
    if isinstance(rows, dict):
        rows = [rows]
    out = {}
    for r in rows:
        code = str(r.get('inter_shrn_iscd', '')).strip()
        price = to_int(r.get('inter2_prpr'))
        if not code or price <= 0:
            continue
        sign = r.get('prdy_vrss_sign')
        out[code] = {
            'p': price,
            'c': int(signed(to_int(r.get('inter2_prdy_vrss')), sign)),
            'r': round(signed(to_float(r.get('prdy_ctrt')), sign), 2),
            'v': to_int(r.get('acml_vol')),
            'pc': to_int(r.get('inter2_prdy_clpr')) or to_int(r.get('inter2_sdpr')),
        }
    return out, ''


def fetch_single(token, code):
    """주식현재가 시세 (종목 1개). fetch_prices.py와 같은 API."""
    data = kis_get('/uapi/domestic-stock/v1/quotations/inquire-price', 'FHKST01010100',
                   {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code}, token)
    if str(data.get('rt_cd')) != '0':
        return None
    o = data.get('output') or {}
    price = to_int(o.get('stck_prpr'))
    if price <= 0:
        return None
    sign = o.get('prdy_vrss_sign')
    chg = int(signed(to_int(o.get('prdy_vrss')), sign))
    return {
        'p': price,
        'c': chg,
        'r': round(signed(to_float(o.get('prdy_ctrt')), sign), 2),
        'v': to_int(o.get('acml_vol')),
        'pc': to_int(o.get('stck_sdpr')) or (price - chg),
    }


def collect(token, stocks, state):
    """전 종목 수집. 반환: (quotes dict, mode 문자열)."""
    quotes = {}
    use_multi = state.get('multi_ok', True)
    # 멀티가 막혀 있던 경우 30분마다 한 번씩 다시 시도
    if not use_multi and time.time() - state.get('multi_fail_at', 0) > 1800:
        use_multi = True

    if use_multi:
        fails = 0
        for i in range(0, len(stocks), CHUNK):
            chunk = stocks[i:i + CHUNK]
            got, err = fetch_multi(token, chunk)
            if got is None:
                fails += 1
                log(f'  ⚠ 멀티 시세 실패 ({i // CHUNK + 1}번째 묶음): {err}')
                if i == 0 or fails >= 3:
                    # 첫 묶음부터 실패 = API 자체가 안 되는 상태 → 단건 방식으로 전환
                    state['multi_ok'] = False
                    state['multi_fail_at'] = time.time()
                    quotes = {}
                    use_multi = False
                    break
            else:
                quotes.update(got)
            time.sleep(MULTI_DELAY)
        if use_multi:
            state['multi_ok'] = True
            missing = [s for s in stocks if s['code'] not in quotes]
            if missing:
                log(f'  ↪ 멀티에서 빠진 {len(missing)}종목 단건 보충 (최대 {MAX_SINGLE_FILL})')
                for s in missing[:MAX_SINGLE_FILL]:
                    q = fetch_single(token, s['code'])
                    if q:
                        quotes[s['code']] = q
                    time.sleep(SINGLE_DELAY)
            return quotes, 'multi'

    # 단건 방식 (대체 경로)
    for s in stocks:
        q = fetch_single(token, s['code'])
        if q:
            quotes[s['code']] = q
        time.sleep(SINGLE_DELAY)
    return quotes, 'single'


# ───────────────────────── 메인 ─────────────────────────
def main():
    force = '--force' in sys.argv
    now = datetime.now(KST)
    hm = (now.hour, now.minute)

    if not force:
        if now.weekday() >= 5:
            return 0
        if hm < RUN_START or hm > RUN_END:
            return 0

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        log('❌ KIS_APP_KEY / KIS_APP_SECRET 없음 (~/.env_secrets 확인)')
        return 1

    os.makedirs(LIVE_DIR, exist_ok=True)

    # 동시 실행 방지
    lock = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log('⏭ 앞 실행이 아직 진행 중 — 건너뜀')
        return 0

    state = read_json(STATE_FILE, {}) or {}
    today = now.strftime('%Y-%m-%d')

    # 휴장 판정 후 대기 중이면 호출 안 함
    if not force and state.get('closed_date') == today and time.time() < state.get('closed_until', 0):
        return 0

    stocks = load_stock_list()
    if not stocks:
        log('❌ 종목 리스트 없음')
        return 1

    token = get_token()
    if not token:
        return 1

    t0 = time.time()
    try:
        quotes, mode = collect(token, stocks, state)
    except TokenExpired:
        log('🔁 토큰 만료 응답 → 재발급 후 1회 재시도')
        token = get_token(force_new=True)
        if not token:
            write_json_atomic(STATE_FILE, state)
            return 1
        try:
            quotes, mode = collect(token, stocks, state)
        except TokenExpired:
            log('❌ 재발급 후에도 토큰 오류')
            write_json_atomic(STATE_FILE, state)
            return 1

    if len(quotes) < len(stocks) * 0.5:
        log(f'❌ 수집 실패 (받은 종목 {len(quotes)}/{len(stocks)}) — 기존 파일 유지')
        write_json_atomic(STATE_FILE, state)
        return 1

    # 휴장일 판정: 09:10 이후인데 전 종목 거래량 0
    total_vol = sum(q.get('v', 0) for q in quotes.values())
    holiday = (hm >= (9, 10)) and total_vol == 0
    if holiday and not force:
        state['closed_date'] = today
        state['closed_until'] = time.time() + 1800
        log('💤 거래량 0 — 휴장으로 판단, 30분 뒤 재확인')
    else:
        state.pop('closed_date', None)
        state.pop('closed_until', None)

    market_open = (now.weekday() < 5) and (OPEN_T <= hm < CLOSE_T) and not holiday

    out_stocks = {}
    for s in stocks:
        q = quotes.get(s['code'])
        if not q:
            continue
        out_stocks[s['code']] = {'n': s['name'], 'm': s['market'], **q}

    output = {
        'updated': now.strftime('%Y-%m-%dT%H:%M:%S+09:00'),
        'date': today,
        'time': now.strftime('%H:%M'),
        'market_open': market_open,
        'holiday': holiday,
        'mode': mode,
        'count': len(out_stocks),
        'total': len(stocks),
        'stocks': out_stocks,
    }
    write_json_atomic(OUT_FILE, output)
    write_json_atomic(STATE_FILE, state)
    log(f'✅ {len(out_stocks)}/{len(stocks)}종목 저장 ({mode}, {time.time() - t0:.1f}초, 장중={market_open})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
