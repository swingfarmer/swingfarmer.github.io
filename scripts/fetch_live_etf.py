#!/usr/bin/env python3
"""
국내 ETF 장중 준실시간 시세 — KIS Open API (VM 크론 전용, 083)
==============================================================
data/kr/etf/latest.json 의 ETF 전종목(약 1,190개) 현재가·등락률·거래량을 1분마다 수집.
주식용 fetch_live_prices.py 와 따로 돈다 (ETF가 느려져도 히트맵·담보비율은 영향 없게).

  - 토큰·멀티조회 함수는 fetch_live_prices.py 것을 그대로 씀 (토큰 캐시 공유)
  - 크론은 주식 수집과 30초 엇갈려서 실행 (같은 순간 동시 호출·토큰 발급 겹침 방지)
  - 멀티조회(30종목/1회)가 막히면 단건으로 바꾸지 않고 그 회차는 건너뜀
    (1,190개 단건은 1분 안에 못 끝남)
  - 장 시간(평일 08:59~15:40) 밖에서는 호출 없이 바로 종료

출력: ~/sf_live/etf_live.json (레포 밖) → API GET /api/etf/live → /etf/ 페이지

사용법
  python3 scripts/fetch_live_etf.py              # 크론용
  python3 scripts/fetch_live_etf.py --test 60    # 순자산 상위 60개만, 시간 무시, 저장 안 하고 결과만 출력
  python3 scripts/fetch_live_etf.py --force      # 시간 무시하고 전체 1회 수집·저장
"""

import os, sys, json, time, fcntl
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_live_prices as flp   # load_env, 토큰, fetch_multi, 경로 상수

KST = flp.KST
REPO_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETF_LIST   = os.path.join(REPO_DIR, 'data', 'kr', 'etf', 'latest.json')
OUT_FILE   = os.path.join(flp.LIVE_DIR, 'etf_live.json')
STATE_FILE = os.path.join(flp.LIVE_DIR, '.live_etf_state.json')
LOCK_FILE  = os.path.join(flp.LIVE_DIR, '.live_etf.lock')

CHUNK        = flp.CHUNK        # 30
MULTI_DELAY  = flp.MULTI_DELAY  # 0.15초
SINGLE_DELAY = flp.SINGLE_DELAY
MAX_SINGLE_FILL = 30            # 멀티에서 빠진 것 단건 보충 상한
SLOW_WARN    = 45               # 이보다 오래 걸리면 경고 (다음 회차와 겹칠 위험)

log = flp.log


def load_etf_list():
    """latest.json → [{code, name}] 순자산 큰 순."""
    d = flp.read_json(ETF_LIST, {}) or {}
    cols = d.get('cols') or []
    rows = d.get('rows') or []
    try:
        ic, iname, iaum = cols.index('code'), cols.index('name'), cols.index('aum_eok')
    except ValueError:
        log(f'❌ {ETF_LIST} 형식이 예상과 다름 (cols={cols[:5]})')
        return []
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: -(r[iaum] or 0)):
        code = str(r[ic]).strip()
        if code and code not in seen:
            seen.add(code)
            out.append({'code': code, 'name': r[iname]})
    return out


def collect(token, items):
    """멀티조회로 전체 수집. 반환 (quotes, 실패 묶음 수, 호출 수)."""
    quotes, fails, calls = {}, 0, 0
    for i in range(0, len(items), CHUNK):
        chunk = items[i:i + CHUNK]
        got, err = flp.fetch_multi(token, chunk)
        calls += 1
        if got is None:
            fails += 1
            log(f'  ⚠ 멀티 시세 실패 ({i // CHUNK + 1}번째 묶음): {err}')
            if i == 0 or fails >= 3:
                return None, fails, calls      # API 자체 문제 → 이번 회차 포기
        else:
            quotes.update(got)
        time.sleep(MULTI_DELAY)

    missing = [s for s in items if s['code'] not in quotes]
    if missing:
        log(f'  ↪ 멀티에서 빠진 {len(missing)}개 단건 보충 (최대 {MAX_SINGLE_FILL}): '
            + ', '.join(s['code'] for s in missing[:8]) + (' …' if len(missing) > 8 else ''))
        for s in missing[:MAX_SINGLE_FILL]:
            q = flp.fetch_single(token, s['code'])
            calls += 1
            if q:
                quotes[s['code']] = q
            time.sleep(SINGLE_DELAY)
    return quotes, fails, calls


def main():
    args = sys.argv[1:]
    test_n = 0
    if '--test' in args:
        try:
            test_n = int(args[args.index('--test') + 1])
        except (IndexError, ValueError):
            test_n = 60
    force = '--force' in args or test_n > 0

    now = datetime.now(KST)
    hm = (now.hour, now.minute)
    if not force:
        if now.weekday() >= 5 or hm < flp.RUN_START or hm > flp.RUN_END:
            return 0

    if not flp.KIS_APP_KEY or not flp.KIS_APP_SECRET:
        log('❌ KIS_APP_KEY / KIS_APP_SECRET 없음 (~/.env_secrets 확인)')
        return 1
    os.makedirs(flp.LIVE_DIR, exist_ok=True)

    lock = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log('⏭ ETF: 앞 실행이 아직 진행 중 — 건너뜀')
        return 0

    state = flp.read_json(STATE_FILE, {}) or {}
    today = now.strftime('%Y-%m-%d')
    if not force and state.get('closed_date') == today and time.time() < state.get('closed_until', 0):
        return 0

    items = load_etf_list()
    if not items:
        log('❌ ETF 목록 없음')
        return 1
    if test_n:
        items = items[:test_n]

    token = flp.get_token()
    if not token:
        return 1

    t0 = time.time()
    try:
        quotes, fails, calls = collect(token, items)
    except flp.TokenExpired:
        log('🔁 토큰 만료 응답 → 재발급 후 1회 재시도')
        token = flp.get_token(force_new=True)
        if not token:
            return 1
        try:
            quotes, fails, calls = collect(token, items)
        except flp.TokenExpired:
            log('❌ 재발급 후에도 토큰 오류')
            return 1
    el = time.time() - t0

    if quotes is None or len(quotes) < len(items) * 0.5:
        got = 0 if quotes is None else len(quotes)
        log(f'❌ ETF 수집 실패 (받은 {got}/{len(items)}, 호출 {calls}회, {el:.1f}초) — 기존 파일 유지')
        return 1

    # ---- 테스트: 저장 없이 결과만 ----
    if test_n:
        per_call = el / max(calls, 1)
        est_full = per_call * (-(-1190 // CHUNK))
        log(f'🧪 테스트 {len(quotes)}/{len(items)}개 받음, 호출 {calls}회, {el:.1f}초 '
            f'(호출당 {per_call:.2f}초 → 1,190개 추정 {est_full:.0f}초)')
        names = {s['code']: s['name'] for s in items}
        for code in list(quotes)[:5]:
            q = quotes[code]
            print(f'   {code} {names.get(code, "")[:22]:<22} {q["p"]:>9,}원 {q["r"]:+.2f}% 거래량 {q["v"]:,}')
        alnum = [s for s in items if not s['code'].isdigit()]
        ok_alnum = [s for s in alnum if s['code'] in quotes]
        print(f'   영문 섞인 코드(예: 0000D0): {len(ok_alnum)}/{len(alnum)}개 받음')
        return 0

    total_vol = sum(q.get('v', 0) for q in quotes.values())
    holiday = hm >= (9, 10) and total_vol == 0
    if holiday and not force:
        state['closed_date'] = today
        state['closed_until'] = time.time() + 1800
        log('💤 ETF 거래량 0 — 휴장으로 판단, 30분 뒤 재확인')
    else:
        state.pop('closed_date', None)
        state.pop('closed_until', None)

    market_open = now.weekday() < 5 and flp.OPEN_T <= hm < flp.CLOSE_T and not holiday
    etfs = {c: {'p': q['p'], 'r': q['r'], 'v': q['v']} for c, q in quotes.items()}
    flp.write_json_atomic(OUT_FILE, {
        'updated': now.strftime('%Y-%m-%dT%H:%M:%S+09:00'),
        'date': today,
        'time': now.strftime('%H:%M'),
        'market_open': market_open,
        'holiday': holiday,
        'count': len(etfs),
        'total': len(items),
        'etfs': etfs,
    })
    flp.write_json_atomic(STATE_FILE, state)
    warn = f' ⚠ {SLOW_WARN}초 초과' if el > SLOW_WARN else ''
    log(f'✅ ETF {len(etfs)}/{len(items)}개 저장 (호출 {calls}회, {el:.1f}초, 장중={market_open}){warn}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
