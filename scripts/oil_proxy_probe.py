#!/usr/bin/env python3
"""
(135 임시 조회 — 끝나면 git rm) 장중 대용 지표가 오피넷 값을 얼마나 따라가나
  싱가포르 등유(항공유, 오피넷 DB) ↔ 난방유 선물 HO=F (야후, $/gal ×42 = $/bbl)
  두바이(오피넷 DB)               ↔ 브렌트 선물 BZ=F · WTI CL=F (야후)
읽기만 함. 화면에는 통계만(오피넷 원값은 출력하지 않음 — 약관).

lag0 = 같은 날짜끼리, lag1 = 야후 전날(싱가포르 마감 16:30이 미국 장 전이라 전날 미국 장이 더 맞을 수 있음)
적중 = 하루 변화 방향(+/−)이 같은 비율, 추정오차 = 야후 변화율×β로 오피넷 하루 변화를 맞힐 때 평균 오차(%p)

  . ~/.env_secrets && python3 scripts/oil_proxy_probe.py
"""
import os, sys, math
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_opinet_oil import db_connect, load_env


def rets(series):
    """{date: value} → {date: 전 값 대비 %} (빈 값 건너뜀, 연속된 관측끼리)"""
    ks = sorted(k for k, v in series.items() if v)
    return {ks[i]: (series[ks[i]] / series[ks[i - 1]] - 1) * 100 for i in range(1, len(ks))}


def corr(x, y):
    n = len(x)
    if n < 10:
        return float('nan')
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else float('nan')


def beta(x, y):
    mx, my = sum(x) / len(x), sum(y) / len(y)
    v = sum((a - mx) ** 2 for a in x)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / v if v else 0


def pair(op, yf_ret, lag):
    """op: 오피넷 변화율 {date:%}, yf_ret: 야후 변화율 {date:%}. lag1이면 오피넷 날짜보다 앞선 가장 가까운 야후 날짜"""
    yd = sorted(yf_ret)
    xs, ys = [], []
    for d, v in sorted(op.items()):
        if lag == 0:
            if d in yf_ret:
                xs.append(yf_ret[d]); ys.append(v)
        else:
            prev = [k for k in yd if k < d]
            if prev:
                xs.append(yf_ret[prev[-1]]); ys.append(v)
    return xs, ys


def report(name, op, yf_ret, since):
    op = {d: v for d, v in op.items() if d >= since}
    out = []
    for lag in (0, 1):
        x, y = pair(op, yf_ret, lag)
        if len(x) < 10:
            out.append(f'lag{lag} 표본 부족({len(x)})'); continue
        b = beta(x, y)
        hit = sum(1 for a, c in zip(x, y) if (a > 0) == (c > 0)) / len(x) * 100
        err = sum(abs(c - b * a) for a, c in zip(x, y)) / len(x)
        naive = sum(abs(c) for c in y) / len(y)
        out.append(f'lag{lag}: 상관 {corr(x, y):+.2f} · β {b:.2f} · 방향 적중 {hit:.0f}% · 추정오차 {err:.2f}%p (안 맞힐 때 {naive:.2f}%p) · n={len(x)}')
    print(f'  {name} [{since}~]')
    for o in out:
        print('     ' + o)


def weekly(series):
    """금요일(또는 그 주 마지막 관측) 값 → 주간 변화율"""
    wk = {}
    for d in sorted(k for k, v in series.items() if v):
        wk[d.isocalendar()[:2]] = (d, series[d])
    ks = sorted(wk)
    return {wk[ks[i]][0].isocalendar()[:2]: (wk[ks[i]][1] / wk[ks[i - 1]][1] - 1) * 100 for i in range(1, len(ks))}


def main():
    load_env()
    import yfinance as yf
    conn = db_connect(); cur = conn.cursor()
    cur.execute("SELECT price_date, kero, dubai FROM oil_intl_prices WHERE price_date >= DATE '2023-01-01' ORDER BY price_date")
    kero, dubai = {}, {}
    for d, k, du in cur:
        d = d.date() if hasattr(d, 'date') else d
        if k: kero[d] = float(k)
        if du: dubai[d] = float(du)
    cur.close(); conn.close()
    print(f'오피넷 DB: 등유 {len(kero)}일 · 두바이 {len(dubai)}일 ({min(kero)} ~ {max(kero)})')

    yfd = {}
    for t in ('HO=F', 'BZ=F', 'CL=F'):
        h = yf.Ticker(t).history(start='2022-12-20', auto_adjust=False)
        yfd[t] = {i.date(): float(v) for i, v in h['Close'].items() if v == v and v > 0}
        print(f'야후 {t}: {len(yfd[t])}일 ({min(yfd[t])} ~ {max(yfd[t])})')

    kr, dr = rets(kero), rets(dubai)
    yr = {t: rets(v) for t, v in yfd.items()}
    for since in (date(2023, 1, 1), date(2026, 1, 1), date(2026, 7, 1)):
        print(f'\n── {since} 이후 ──')
        report('항공유(등유) ↔ 난방유 HO', kr, yr['HO=F'], since)
        report('두바이 ↔ 브렌트 BZ', dr, yr['BZ=F'], since)
        report('두바이 ↔ WTI CL', dr, yr['CL=F'], since)

    print('\n── 주간 변화(2023~) ──')
    kw, hw, dw, bw = weekly(kero), weekly(yfd['HO=F']), weekly(dubai), weekly(yfd['BZ=F'])
    for nm, a, b in (('항공유 ↔ 난방유', kw, hw), ('두바이 ↔ 브렌트', dw, bw)):
        ks = sorted(set(a) & set(b))
        x, y = [b[k] for k in ks], [a[k] for k in ks]
        hit = sum(1 for p, q in zip(x, y) if (p > 0) == (q > 0)) / len(x) * 100
        print(f'  {nm}: 상관 {corr(x, y):+.2f} · β {beta(x, y):.2f} · 방향 적중 {hit:.0f}% · n={len(x)}')

    # 수준 차(값 아님, 차이의 통계만): 항공유 − 난방유×42
    sp = [kero[d] - yfd['HO=F'][d] * 42 for d in kero if d in yfd['HO=F'] and d >= date(2026, 1, 1)]
    if sp:
        m = sum(sp) / len(sp); s = math.sqrt(sum((v - m) ** 2 for v in sp) / len(sp))
        print(f'\n항공유 − 난방유×42 (2026~): 평균 {m:+.1f} · 표준편차 {s:.1f} $/bbl · n={len(sp)}  ← 차이가 크게 흔들리면 수준 대용으로는 못 씀')


if __name__ == '__main__':
    main()
