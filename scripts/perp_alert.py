#!/usr/bin/env python3
"""
[봇1] 주말 해외 추정가 알림 (118)
================================
~/sf_live/perp_est.json(fetch_perp_est.py, 1분마다)을 읽어 텔레그램 DM으로 보낸다.
크론: 토·일 09:00·21:00, 월 07:50(장 전).
  - 추정가 = 국내 종가 × (선물 지금 ÷ 종가 시각 15:30 선물) — 계산은 fetch_perp_est.py
  - 지난 알림보다 얼마나 더 움직였는지도 같이 (상태: ~/sf_live/.perp_alert_state.json)
  - 파일이 15분 넘게 안 바뀌었으면 「수집 멈춤」으로 보냄 (조용히 넘어가지 않게)

사용법
  python3 scripts/perp_alert.py          # 크론용 (보냄)
  python3 scripts/perp_alert.py --dry    # 보내지 않고 화면에만
"""

import os, sys, json, time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
KST = timezone(timedelta(hours=9))
LIVE_DIR   = os.path.expanduser(os.environ.get('SF_LIVE_DIR', '~/sf_live'))
EST_FILE   = os.path.join(LIVE_DIR, 'perp_est.json')
STATE_FILE = os.path.join(LIVE_DIR, '.perp_alert_state.json')
STALE_SEC  = 15 * 60
WD = '월화수목금토일'


def read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def won(n):
    return f'{int(round(n)):,}'


def build(now):
    D = read_json(EST_FILE)
    head = f'🌙 <b>해외 추정가</b> ({now.month}/{now.day} {WD[now.weekday()]} {now:%H:%M})'
    if not D:
        return head + '\n⚠ perp_est.json 없음 — fetch_perp_est.py 크론 확인', None
    age = time.time() - os.path.getmtime(EST_FILE)
    if D.get('session'):
        return None, None   # 국내 장중이면 보낼 필요 없음
    if age > STALE_SEC:
        return head + f'\n⚠ 수집 멈춤 — 마지막 갱신 {int(age // 60)}분 전 ({D.get("updated", "")[:16]})\n로그: tail -5 ~/logs/fetch_perp_est.log', None
    items = D.get('items') or []
    if not items:
        return head + '\n⚠ 종목 값 없음', None
    bd = D.get('base_date', '')
    bdt = datetime.strptime(bd, '%Y-%m-%d') if bd else None
    bd_s = f'{bdt.month}/{bdt.day}({WD[bdt.weekday()]})' if bdt else '-'
    prev = (read_json(STATE_FILE, {}) or {})
    prev_pct = prev.get('pct', {}) if prev.get('base_date') == bd else {}
    lines = [head, f'{bd_s} 종가 대비 · 바이낸스·하이퍼리퀴드 무기한 선물', '']
    for x in items:
        p = x['pct']
        mark = '🔺' if p > 0 else ('🔻' if p < 0 else '·')
        est = f"{x['est']:,.2f}pt" if x.get('kind') == 'index' else f"{won(x['est'])}원"
        line = f"{mark} <b>{x['name']}</b> {est} ({p:+.2f}%)"
        if x['code'] in prev_pct:
            d = p - prev_pct[x['code']]
            line += f'\n      지난 알림보다 {d:+.2f}%p'
        if (x.get('qv') or 0) < 1e6:
            line += '\n      ⚠ 24시간 거래대금 100만 달러 미만 (얇음)'
        lines.append(line)
    lines += ['', '실제 주식 아님 · 분위기 참고용', 'https://swingfarmer.github.io/today/']
    state = {'base_date': bd, 'pct': {x['code']: x['pct'] for x in items}, 'sent': now.isoformat()}
    return '\n'.join(lines), state


def main():
    dry = '--dry' in sys.argv
    now = datetime.now(KST)
    msg, state = build(now)
    if msg is None:
        print(f'[{now:%m-%d %H:%M}] 국내 장중 — 안 보냄')
        return 0
    print(f'[{now:%m-%d %H:%M}]\n' + msg)
    if dry:
        return 0
    from telegram_helper import send_dm
    ok = send_dm(msg)
    print('  봇1 DM:', '성공' if ok else '실패')
    if ok and state:
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
