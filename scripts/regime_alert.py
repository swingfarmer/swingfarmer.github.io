"""
시장 국면 바뀜 알림 [봇1] (116)
================================
- 매일 평일 21:25 (크론). 점수는 사이트와 같은 /sf-regime.js를 node로 계산 (scripts/regime_calc.js).
- 하루 = 신고가·신저가 데이터 날짜(한국 거래일). 같은 날짜로 다시 돌면 그날 기록을 덮어씀(휴장일은 하루로 안 셈).
- 새 국면이 이틀(거래일) 연속이고, 마지막으로 알린 국면과 다를 때만 DM 1통. 같으면 안 보냄.
  (경계 근처에서 매일 왔다 갔다 하는 헛알림을 막으려는 것 — 사용자 116: 하루 늦어도 큰 흐름이면 됨)
- 처음 실행하면 지금 국면을 기준으로 저장만 하고 알림 없음.
- 상태: ~/sf_state/regime.json (레포 밖 — auto_push가 매일 커밋하지 않게). healthcheck TARGETS에 있음.

옵션
  --dry   계산·판정만 화면에 (저장·전송 안 함)
  --test  지금 점수로 알림 모양 그대로 DM 1통 (제목에 🧪 테스트, 저장 안 함)
"""
import os, sys, json, subprocess
from datetime import datetime, timezone, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'scripts'))
STATE = os.path.expanduser('~/sf_state/regime.json')
KEEP = 60
MIN_N = 6              # 점수 있는 지표가 이보다 적으면 데이터가 빠진 것 → 기록 안 함
# (130) 텔레그램 DM에 사이트 링크를 넣지 않음(사용자 요청)
KST = timezone(timedelta(hours=9))


def calc():
    r = subprocess.run(['node', os.path.join(REPO, 'scripts', 'regime_calc.js'), REPO],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError('node 실패: ' + (r.stderr or r.stdout)[-500:])
    return json.loads(r.stdout)


def load():
    try:
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def sgn(x, d=2):
    if round(x, d) == 0:
        return '0' if d == 0 else f'{0:.{d}f}'
    return f'{x:+.{d}f}'.replace('-', '−')


def short(name, k):
    return name.get(k, k).split(' — ')[0]


def esc(t):
    return str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def md(d):
    return f'{int(d[5:7])}/{int(d[8:10])}' if d and len(d) >= 10 else (d or '?')


def message(prev, cur, days, name, test=False):
    """prev: 바뀌기 전 마지막 날 기록, cur: 오늘 기록, days: 새 국면이 이어진 날짜들"""
    head = ('🧪 테스트 — ' if test else '') + '🧭 시장 국면 바뀜 (이틀 연속 확인)'
    L = [head,
         f'{short(name, prev["auto"])} → <b>{short(name, cur["auto"])}</b>',
         f'평균 {sgn(prev["avg"])} → {sgn(cur["avg"])} (지표 {cur["n"]}개, {"·".join(md(d) for d in days)})']
    pv = {x['n']: x for x in prev.get('I', [])}
    ch = []
    for x in cur.get('I', []):
        p = pv.get(x['n'])
        if p and x['s'] is not None and p['s'] is not None and x['s'] != p['s']:
            ch.append((abs(x['s'] - p['s']), x, p))
    ch.sort(key=lambda t: -t[0])
    if ch:
        L.append('많이 바뀐 지표:')
        for _, x, p in ch[:5]:
            L.append(f' · {esc(x["n"])} {esc(p["v"])}→{esc(x["v"])} ({sgn(p["s"], 0)}→{sgn(x["s"], 0)})')
    else:
        L.append('점수가 바뀐 지표는 없음 (평균만 경계를 넘음)')
    return '\n'.join(L)


def step(st, res, now):
    """상태 갱신 + 보낼 메시지(없으면 None). 순수 함수 — 테스트용"""
    key = res.get('date') or now.strftime('%Y-%m-%d')
    rec = {'date': key, 'auto': res['auto'], 'avg': round(res['avg'], 4), 'n': res['n'], 'I': res['I']}
    h = st.get('history', [])
    if h and h[-1]['date'] == key:
        h[-1] = rec
    else:
        h.append(rec)
    h = h[-KEEP:]
    st['history'] = h
    st['updated'] = now.strftime('%Y-%m-%d %H:%M KST')
    msg = None
    if not st.get('confirmed'):
        st['confirmed'], st['confirmed_since'] = rec['auto'], key
        st['note'] = '처음 실행 — 기준 국면만 저장'
        return st, None
    new = h[-1]['auto']
    if len(h) >= 2 and h[-2]['auto'] == new and new != st['confirmed']:
        j = len(h) - 1
        while j >= 0 and h[j]['auto'] == new:
            j -= 1
        days = [x['date'] for x in h[j + 1:]]
        prev = h[j] if j >= 0 else {'auto': st['confirmed'], 'avg': 0, 'I': []}
        msg = message(prev, h[-1], days, res.get('name', {}))
        st['confirmed'], st['confirmed_since'] = new, days[0]
    st.pop('note', None)
    return st, msg


def main():
    dry, test = '--dry' in sys.argv, '--test' in sys.argv
    now = datetime.now(KST)
    print(f'── 국면 알림 시작 {now:%Y-%m-%d %H:%M}' + (' (dry)' if dry else ' (test)' if test else ''))
    res = calc()
    print(f'  계산: {res["date"]} {short(res["name"], res["auto"])} 평균 {sgn(res["avg"])} (점수 있는 지표 {res["n"]}/{res["total"]})'
          + (f' / 못 읽은 파일: {",".join(res["missing"])}' if res['missing'] else ''))
    if res['n'] < MIN_N:
        print(f'  ❌ 점수 있는 지표가 {res["n"]}개(<{MIN_N}) — 데이터 빠짐, 기록·알림 안 함')
        sys.exit(1)
    st = load()
    if test:
        h = st.get('history', [])
        prev = h[-2] if len(h) >= 2 else (h[-1] if h else {'auto': 'mix', 'avg': 0, 'I': []})
        cur = {'auto': res['auto'], 'avg': res['avg'], 'n': res['n'], 'I': res['I']}
        msg = message(prev, cur, [res['date']], res['name'], test=True)
        print(msg)
        from telegram_helper import send_dm
        print('  전송:', '성공' if send_dm(msg) else '실패')
        return
    st, msg = step(st, res, now)
    h = st['history']
    print(f'  최근: ' + ' '.join(f'{md(x["date"])}{short(res["name"], x["auto"])[0]}' for x in h[-5:])
          + f' / 확정 국면 {short(res["name"], st["confirmed"])} ({md(st.get("confirmed_since"))}부터)')
    if st.get('note'):
        print('  ' + st['note'])
    if msg:
        print('  📨 바뀜 → 알림\n' + msg)
    else:
        print('  알림 없음')
    if dry:
        print('  (dry — 저장·전송 안 함)')
        return
    if msg:
        from telegram_helper import send_dm
        print('  봇1 DM:', '성공' if send_dm(msg) else '실패')
    save(st)
    print('  저장:', STATE)


if __name__ == '__main__':
    main()
