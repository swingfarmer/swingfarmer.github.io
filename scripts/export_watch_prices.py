#!/usr/bin/env python3
"""
(135) 관심 종목 장중 시세 → sf-private/data/live/watch_prices.json (종목 채팅이 읽는 용)
=====================================================================================
- 새 KIS 호출 없음: fetch_live_prices.py가 1분마다 쓰는 ~/sf_live/prices_live.json에서
  관심 종목만 골라 옮긴다. 평일 장중 15분마다(크론 09:02~15:47), 바뀌었을 때만 push.
- 관심 종목 목록: ~/sf-private/data/live/watch.json {"codes": ["003490", ...]} — 종목 채팅이 고쳐도 됨.
  수집 목록(scripts/kospi200_list.csv·kosdaq_list.csv, 시총 기준) 밖 종목은 "missing"에 남는다.
- 파일 안 "today": 그날 15분마다 찍은 값(다음 거래일에 새로 시작) — 장중 흐름 보기용.
- 휴장일·그날 파일이 아니면(prices_live date ≠ 오늘) 아무것도 안 함.

사용법
  python3 scripts/export_watch_prices.py          # 크론용
  python3 scripts/export_watch_prices.py --dry    # 화면에만(파일·push 안 함)
"""
import os, sys, json, argparse, subprocess
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
LIVE = os.path.join(os.path.expanduser(os.environ.get('SF_LIVE_DIR', '~/sf_live')), 'prices_live.json')
PRIV = os.path.expanduser(os.environ.get('SF_PRIVATE_DIR', '~/sf-private'))
WATCH_REL = 'data/live/watch.json'
OUT_REL = 'data/live/watch_prices.json'
DEFAULT_CODES = ['003490', '000720', '004020']


def read_json(p, default=None):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def git(*a):
    return subprocess.run(['git', '-C', PRIV] + list(a), capture_output=True, text=True)


def build(pl, codes, old):
    stocks = pl.get('stocks') or {}
    out, missing = {}, []
    for c in codes:
        s = stocks.get(c)
        if not s:
            missing.append(c)
            continue
        out[c] = {k: s.get(k) for k in ('n', 'p', 'c', 'r', 'v', 'pc') if s.get(k) is not None}
    idx = {}
    for k, v in (pl.get('indices') or {}).items():
        if isinstance(v, dict):
            idx[k] = {kk: v.get(kk) for kk in ('p', 'c', 'r') if v.get(kk) is not None}
    t = pl.get('time') or ''
    today = []
    if old and old.get('date') == pl.get('date'):
        today = list(old.get('today') or [])
    snap = {'t': t, 'p': {c: v['p'] for c, v in out.items()}}
    for k in ('KOSPI', 'KOSDAQ'):
        if idx.get(k, {}).get('p') is not None:
            snap[k] = idx[k]['p']
    if not today or today[-1].get('t') != t:
        today.append(snap)
    return {
        '_설명': '관심 종목 장중 시세(KIS 1분 수집 중 일부, 15분마다 push). p=현재가 c=전일대비 r=등락률% v=누적거래량 pc=전일종가. '
                 'today=그날 15분 기록. 15:40 이후 값 = 그날 종가. 목록은 data/live/watch.json',
        'updated': pl.get('updated'),
        'date': pl.get('date'),
        'time': t,
        'market_open': bool(pl.get('market_open')),
        'indices': idx,
        'stocks': out,
        'missing': missing,
        'today': today,
    }


def main():
    ap = argparse.ArgumentParser(description='관심 종목 장중 시세 → sf-private')
    ap.add_argument('--dry', action='store_true', help='화면에만')
    a = ap.parse_args()
    now = datetime.now(KST)
    pl = read_json(LIVE)
    if not pl:
        print(f'[{now:%m/%d %H:%M}] ❌ {LIVE} 없음'); sys.exit(1)
    if pl.get('holiday') or pl.get('date') != now.strftime('%Y-%m-%d'):
        print(f'[{now:%m/%d %H:%M}] 오늘 장 값 아님(date={pl.get("date")}, holiday={pl.get("holiday")}) — 안 함'); return
    w = read_json(os.path.join(PRIV, WATCH_REL), {}) or {}
    codes = [str(c).zfill(6) for c in (w.get('codes') or DEFAULT_CODES)]
    path = os.path.join(PRIV, OUT_REL)
    old = read_json(path)
    obj = build(pl, codes, old)
    text = json.dumps(obj, ensure_ascii=False, indent=1) + '\n'
    line = f'[{now:%m/%d %H:%M}] {len(obj["stocks"])}/{len(codes)}종목 · 기록 {len(obj["today"])}개 · 기준 {obj["time"]}' + \
           (f' · 목록 밖 {",".join(obj["missing"])}' if obj['missing'] else '')
    if a.dry:
        print(line); print(text[:1500]); print('(dry — 파일·push 안 함)'); return
    old_text = open(path, encoding='utf-8').read() if os.path.exists(path) else None
    if old_text == text:
        print(line + ' — 바뀐 것 없음'); return
    r = git('pull', '-q', '--rebase', '--autostash')
    if r.returncode:
        print('  ⚠ pull 실패:', r.stderr.strip()[-300:])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fp:
        fp.write(text)
    git('add', OUT_REL)
    r = git('-c', 'user.name=swingfarmer-vm', '-c', 'user.email=vm@swingfarmer.local',
            'commit', '-q', '-m', 'auto: 관심 종목 시세 %s %s' % (obj['date'], obj['time']))
    if r.returncode:
        print('  ❌ commit 실패:', (r.stderr or r.stdout).strip()[-300:]); sys.exit(1)
    r = git('push', '-q', 'origin', 'HEAD:main')
    if r.returncode:
        r2 = git('pull', '-q', '--rebase', '--autostash')   # 종목 채팅 push와 겹쳤을 때 한 번 더
        r = git('push', '-q', 'origin', 'HEAD:main') if not r2.returncode else r2
        if r.returncode:
            print('  ❌ push 실패:', r.stderr.strip()[-300:]); sys.exit(1)
    print(line + ' ✅ push')


if __name__ == '__main__':
    main()
