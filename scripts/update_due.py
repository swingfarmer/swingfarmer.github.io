#!/usr/bin/env python3
"""
정기 갱신 알림 (133) — [봇1] 매월 1·16일 09:10
================================================
목록 원본: ~/sf-private/handoff/update_list.json (비공개 — 리포트 이름이 들어 있어서)
  manual  : 손으로 고쳐야 하는 것. next 날짜가 오늘 이전이면 「할 때 됨」
  auto    : 자동인데 헬스체크(TARGETS) 밖이라 따로 보는 데이터 파일. 파일 안 가장 늦은 날짜가 max_days보다 오래되면 「멈춤」
            (헬스체크 TARGETS에 있는 파일은 「헬스체크가 봄」으로만 표시하고 알림엔 안 넣음)
  reports : sf-private research·asset-notes 목록(ARTICLES)의 date가 rule 일수보다 오래되면 「2편·갱신 권유」
            도구 페이지(href가 /로 시작)·강연(talk)은 뺌. snooze {href: 날짜}로 미룸
알림: 할 때 된 것·멈춘 것·권유가 하나라도 있을 때만 봇1 DM (사이트 링크 없음 — 130 규칙). 없으면 조용히 끝.

사용법:
  python3 scripts/update_due.py            # 계산 + 있으면 DM
  python3 scripts/update_due.py --list     # 화면에 전체 목록(다가오는 것까지), DM 안 함
  python3 scripts/update_due.py --dry      # DM으로 보낼 글만 화면에
  --priv DIR  비공개 레포 위치(기본 ~/sf-private) · --pub DIR 공개 레포 위치(기본 이 파일의 상위 폴더)
Claude 작업 공간에서도 돈다(인수 때 --list): 날짜는 파일 수정 시각이 아니라 파일 안 날짜로 봐서 clone해도 같음.
"""
import os, re, sys, json, argparse
from datetime import datetime, timedelta, timezone, date

KST = timezone(timedelta(hours=9))
DATE_RE = re.compile(r'(?<!\d)(20[123]\d)[-./]?(0[1-9]|1[0-2])[-./]?(0[1-9]|[12]\d|3[01])(?!\d)')


def today():
    return datetime.now(KST).date()


def latest_date_in(path, t0):
    """파일 안 YYYY-MM-DD / YYYYMMDD 중 오늘 이하 가장 늦은 날짜. 없으면 파일 수정일."""
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            txt = f.read()
    except OSError:
        return None
    best = None
    for y, m, d in DATE_RE.findall(txt):
        try:
            x = date(int(y), int(m), int(d))
        except ValueError:
            continue
        if x <= t0 and (best is None or x > best):
            best = x
    if best is None:
        best = datetime.fromtimestamp(os.path.getmtime(path), KST).date()
    return best


def hc_targets(pub):
    try:
        txt = open(os.path.join(pub, 'scripts', 'healthcheck.py'), encoding='utf-8').read()
    except OSError:
        return set()
    return set(re.findall(r'\(\s*"([^"]+)"\s*,', txt))


def read_articles(path):
    try:
        t = open(path, encoding='utf-8').read()
    except OSError:
        return []
    out = []
    for m in re.finditer(r"\{\s*title:\s*'((?:[^'\\]|\\.)*)'(.*?)\n\s*\}", t, re.S):
        body = m.group(2)
        g = lambda k: (re.search(k + r":\s*'([^']*)'", body) or [None, ''])[1]
        out.append({'title': m.group(1).replace("\\'", "'"), 'cat': g('cat'), 'date': g('date'), 'href': g('href')})
    return out


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--priv', default=os.path.expanduser('~/sf-private'))
    ap.add_argument('--pub', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    t0 = today()

    try:
        cfg = json.load(open(os.path.join(a.priv, 'handoff', 'update_list.json'), encoding='utf-8'))
    except Exception as e:
        print('❌ 목록을 못 읽음: %s' % e)
        sys.exit(1)

    # ── 손으로 할 것
    due, soon = [], []
    for it in cfg.get('manual', []):
        try:
            nx = date.fromisoformat(it.get('next', ''))
        except ValueError:
            nx = None
        if nx is None:
            continue
        if nx <= t0:
            due.append((nx, it))
        elif (nx - t0).days <= 45:
            soon.append((nx, it))
    due.sort(key=lambda x: x[0]); soon.sort(key=lambda x: x[0])

    # ── 자동인데 헬스체크 밖
    hc = hc_targets(a.pub)
    stale, auto_ok, auto_hc = [], [], []
    for it in cfg.get('auto', []):
        f = it['file']
        if f in hc:
            auto_hc.append(it)
            continue
        p = os.path.expanduser(f) if f.startswith('~') else os.path.join(a.pub, f)
        d = latest_date_in(p, t0)
        if d is None:
            stale.append((it, None, None))
            continue
        age = (t0 - d).days
        (stale if age > it.get('max_days', 4) else auto_ok).append((it, d, age))

    # ── 오래된 리포트
    rule = cfg.get('reports', {}).get('rule', {})
    snooze = cfg.get('reports', {}).get('snooze', {})
    old = []
    for idx, base in (('research/index.html', '/research/'), ('asset-notes/index.html', '/asset-notes/')):
        for r in read_articles(os.path.join(a.priv, idx)):
            if r['href'].startswith('/') or r['cat'] not in rule:
                continue
            try:
                d = date.fromisoformat(r['date'])
            except ValueError:
                continue
            key = r['href']
            sz = snooze.get(key) or snooze.get(base + key.lstrip('./'))
            if sz and sz >= t0.isoformat():
                continue
            age = (t0 - d).days
            if age >= rule[r['cat']]:
                old.append((age, r, base))
    old.sort(key=lambda x: -x[0])

    if a.list:
        print('정기 갱신 목록 — %s 기준' % t0)
        print('\n[손으로 할 것 — 할 때 됨 %d]' % len(due))
        for nx, it in due:
            print('  ⏰ %s  %s  (%s)\n      → %s' % (nx, it['what'], it.get('page', ''), it.get('how', '')))
        print('\n[45일 안에 다가오는 것 %d]' % len(soon))
        for nx, it in soon:
            print('  · %s  %s  (%s)' % (nx, it['what'], it.get('page', '')))
        print('\n[자동 — 헬스체크 밖 %d개]' % (len(stale) + len(auto_ok)))
        for it, d, age in stale:
            print('  ⚠ 멈춤  %s  마지막 %s (%s일)  %s' % (it['file'], d, age, it['what']))
        for it, d, age in auto_ok:
            print('  ✅ %s  마지막 %s (%s일)  %s' % (it['file'], d, age, it['what']))
        for it in auto_hc:
            print('  ✅ 헬스체크가 봄  %s  %s' % (it['file'], it['what']))
        print('\n[2편·갱신 권유 리포트 %d]' % len(old))
        for age, r, base in old:
            print('  📄 %d일 전 [%s] %s (%s%s)' % (age, r['cat'], r['title'][:60], base, r['href'].lstrip('./')))
        return

    if not (due or stale or old):
        print('[%s] 알릴 것 없음' % datetime.now(KST).strftime('%m/%d %H:%M'))
        return

    L = ['📌 <b>정기 갱신</b> — %d/%d' % (t0.month, t0.day)]
    if due:
        L.append('\n⏰ 손으로 할 때 됨 (%d)' % len(due))
        for nx, it in due[:12]:
            L.append(' · %s — %s' % (esc(it['what']), esc(it.get('page', ''))))
        if len(due) > 12:
            L.append(' · 외 %d개' % (len(due) - 12))
    if stale:
        L.append('\n⚠ 자동인데 멈춘 것 (헬스체크 밖)')
        for it, d, age in stale:
            L.append(' · %s — 마지막 %s' % (esc(it['what']), d.strftime('%m/%d') if d else '파일 없음'))
    if old:
        L.append('\n📄 만든 지 오래된 리포트 — 2편·갱신 할지')
        for age, r, base in old[:8]:
            L.append(' · %s (%d일 전)' % (esc(r['title'][:40]), age))
    L.append('\n채팅에서 「정기 갱신 보자」 하면 Claude가 목록 열어서 같이 봄')
    msg = '\n'.join(L)
    if a.dry:
        print(msg)
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from telegram_helper import send_dm
    ok = send_dm(msg)
    print('[%s] %s — 할 때 됨 %d · 멈춤 %d · 권유 %d' % (datetime.now(KST).strftime('%m/%d %H:%M'), '✅ 보냄' if ok else '❌ 전송 실패', len(due), len(stale), len(old)))


if __name__ == '__main__':
    main()
