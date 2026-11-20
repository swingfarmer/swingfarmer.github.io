#!/usr/bin/env python3
"""
대한항공 유가 요약 → sf-private/data/kal/kal_market_summary.csv (116)
====================================================================
- 원자료: Oracle OIL_INTL_PRICES(오피넷 싱가포르 등유=항공유·두바이, fetch_opinet_oil.py) + EXCHANGE_RATES(USD 매매기준율)
- 오피넷 약관(승낙 없는 복제·유통·제3자 이용 금지) → 일별 원자료는 레포에 두지 않고 「요약만」 내보낸다.
  일별이 꼭 필요하면 사이트 /kal/·/stock-tools/fuel-tracker/ (관리자 로그인)에서 본다.
- 내보내는 것 (한 파일, 「구분」 칸으로 나눔)
  · 월평균      — 2023-01부터 달마다 항공유·두바이·스프레드·원달러 평균
  · 할증료구간  — 여객 유류할증료 발권월마다 산정구간(전전월 16일 ~ 전월 15일) 항공유 평균과 계산 단계
                  단계 = (평균 ¢/gal − 150) ÷ 10 버림 + 1, 상한 33, 150¢ 미만이면 0 (공시 4·9·10·11·12월과 대조용)
  · 최근        — 최근 5거래일 (사용자 116 합의: 「최근 시세 몇 개」)
- 쓰는 곳: 대한항공 채팅(sf-private를 직접 읽음). 사이트 페이지는 안 씀.
- 바뀐 게 있을 때만 ~/sf-private에 커밋·push (VM 크론 화~토 21:40, 오피넷 수집 21:20 뒤)

사용법 (레포 루트에서, . ~/.env_secrets 먼저)
  python3 scripts/export_kal_summary.py --dry   # 화면에만 (파일·push 안 함)
  python3 scripts/export_kal_summary.py         # 파일 쓰고 바뀌었으면 sf-private push
"""
import os, sys, csv, io, subprocess, argparse
from datetime import date

WALLET_DIR = os.path.expanduser('~/wallet')
PRIV = os.path.expanduser('~/sf-private')
OUT_REL = 'data/kal/kal_market_summary.csv'
BBL_GAL = 42.0
HEAD = ['구분', '기간', '시작일', '끝일', '일수', '항공유($/bbl)', '두바이($/bbl)', '스프레드($/bbl)',
        '원달러(원)', '항공유(¢/gal)', '여객할증료_계산단계', '비고']


def load_env():
    f = os.path.expanduser('~/.env_secrets')
    if os.path.exists(f):
        for line in open(f):
            line = line.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('export '): line = line[7:]
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def read_db():
    import oracledb
    conn = oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))
    cur = conn.cursor()
    cur.execute("""SELECT o.price_date, o.kero, o.dubai,
                          (SELECT e.deal_bas_r FROM exchange_rates e WHERE e.cur_unit='USD' AND e.rate_date=o.price_date)
                   FROM oil_intl_prices o ORDER BY o.price_date""")
    oil = [(r[0].date() if hasattr(r[0], 'date') else r[0], r[1], r[2], r[3]) for r in cur.fetchall()]
    cur.execute("""SELECT TO_CHAR(rate_date,'YYYY-MM'), AVG(deal_bas_r), COUNT(*) FROM exchange_rates
                   WHERE cur_unit='USD' AND deal_bas_r > 0 GROUP BY TO_CHAR(rate_date,'YYYY-MM')""")
    fx_m = {ym: float(a) for ym, a, n in cur.fetchall()}
    cur.close(); conn.close()
    return oil, fx_m


def avg(xs):
    xs = [float(x) for x in xs if x is not None and float(x) > 0]
    return sum(xs) / len(xs) if xs else None


def step(cpg):
    if cpg is None: return None
    if cpg < 150: return 0
    return min(33, int((cpg - 150) // 10) + 1)


def f(x, d=2):
    return '' if x is None else f'{x:.{d}f}'


def add_months(y, m, k):
    m += k
    while m > 12: y, m = y + 1, m - 12
    while m < 1: y, m = y - 1, m + 12
    return y, m


def build(oil, fx_m, today=None):
    today = today or date.today()
    rows = []
    # 월평균
    by_m = {}
    for d, k, du, fx in oil:
        by_m.setdefault(d.strftime('%Y-%m'), []).append((d, k, du, fx))
    for ym in sorted(by_m):
        g = by_m[ym]
        k = avg(x[1] for x in g); du = avg(x[2] for x in g)
        sp = avg((float(x[1]) - float(x[2])) for x in g if x[1] and x[2])
        n = sum(1 for x in g if x[1])
        note = '진행중' if ym == today.strftime('%Y-%m') else ''
        rows.append(['월평균', ym, g[0][0].isoformat(), g[-1][0].isoformat(), n, f(k), f(du), f(sp),
                     f(fx_m.get(ym)), f(k * 100 / BBL_GAL if k else None, 1), '', note])
    # 할증료구간: 발권월 M = (M-2)월 16일 ~ (M-1)월 15일
    if oil:
        y, m = oil[0][0].year, oil[0][0].month
        y, m = add_months(y, m, 2)                       # 첫 구간이 다 들어 있는 발권월
        end_y, end_m = add_months(today.year, today.month, 2 if today.day >= 16 else 1)
        while (y, m) <= (end_y, end_m):
            sy, sm = add_months(y, m, -2); ey, em = add_months(y, m, -1)
            s, e = date(sy, sm, 16), date(ey, em, 15)
            g = [x for x in oil if s <= x[0] <= e]
            k = avg(x[1] for x in g); du = avg(x[2] for x in g)
            sp = avg((float(x[1]) - float(x[2])) for x in g if x[1] and x[2])
            fx = avg(x[3] for x in g)
            cpg = k * 100 / BBL_GAL if k else None
            n = sum(1 for x in g if x[1])
            note = f'진행중(~{max(x[0] for x in g):%m/%d})' if g and e > (oil[-1][0]) else ''
            rows.append(['할증료구간', f'{y}-{m:02d}', s.isoformat(), e.isoformat(), n, f(k), f(du), f(sp),
                         f(fx), f(cpg, 1), '' if step(cpg) is None else step(cpg), note])
            y, m = add_months(y, m, 1)
    # 최근 5거래일
    for d, k, du, fx in [x for x in oil if x[1]][-5:]:
        k = float(k); du = float(du) if du else None
        rows.append(['최근', d.isoformat(), d.isoformat(), d.isoformat(), 1, f(k), f(du),
                     f(k - du if du else None), f(float(fx) if fx else None), f(k * 100 / BBL_GAL, 1), '', ''])
    return rows


def to_csv(rows):
    b = io.StringIO()
    w = csv.writer(b, lineterminator='\n')
    w.writerow(HEAD); w.writerows(rows)
    return '﻿' + b.getvalue()       # 엑셀로 열 수 있게 BOM (data/kal/ 다른 CSV와 같음)


def git(*a):
    return subprocess.run(['git', '-C', PRIV] + list(a), capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser(description='대한항공 유가 요약 → sf-private')
    ap.add_argument('--dry', action='store_true', help='화면에만')
    a = ap.parse_args()
    load_env()
    oil, fx_m = read_db()
    if len(oil) < 200:
        print(f'❌ DB 행이 {len(oil)}개뿐 — 내보내지 않음'); sys.exit(1)
    rows = build(oil, fx_m)
    text = to_csv(rows)
    kinds = {}
    for r in rows: kinds[r[0]] = kinds.get(r[0], 0) + 1
    print(f'── 대한항공 유가 요약 {date.today()} : DB {len(oil)}일 ({oil[0][0]} ~ {oil[-1][0]}) → ' +
          ' · '.join(f'{k} {v}줄' for k, v in kinds.items()))
    if a.dry:
        for r in rows:
            if r[0] == '할증료구간' and r[1] >= '2026-01' or r[0] == '최근' or (r[0] == '월평균' and r[1] >= '2026-09'):
                print('  ' + ' | '.join(str(x) for x in r))
        print('(dry — 파일·push 안 함)'); return
    path = os.path.join(PRIV, OUT_REL)
    old = open(path, encoding='utf-8').read() if os.path.exists(path) else None
    if old == text:
        print('  바뀐 것 없음 — push 안 함'); return
    r = git('pull', '-q', '--rebase', '--autostash')
    if r.returncode: print('  ⚠ pull 실패:', r.stderr.strip()[-300:])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fp: fp.write(text)
    git('add', OUT_REL)
    r = git('-c', 'user.name=swingfarmer-vm', '-c', 'user.email=vm@swingfarmer.local',
            'commit', '-q', '-m', f'auto: 대한항공 유가 요약 {date.today()}')
    if r.returncode: print('  ❌ commit 실패:', (r.stderr or r.stdout).strip()[-300:]); sys.exit(1)
    r = git('push', '-q', 'origin', 'HEAD:main')
    if r.returncode:
        print('  ❌ push 실패:', r.stderr.strip()[-300:]); sys.exit(1)
    print('  ✅ sf-private push:', git('log', '--oneline', '-1').stdout.strip())


if __name__ == '__main__':
    main()
