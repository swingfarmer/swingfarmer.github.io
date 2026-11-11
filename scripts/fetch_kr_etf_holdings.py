#!/usr/bin/env python3
"""
국내 ETF 구성종목(PDF) 수집 (082 2단계) — VM 크론 전용, 주 1회
================================================================
pykrx get_etf_portfolio_deposit_file(티커, 날짜) 로 ETF별 구성종목을 받아
비중 상위 TOP_N개만 저장. 종목 목록은 data/kr/etf/latest.json (fetch_kr_etf.py 결과).

출력
  data/kr/etf/holdings.json
  {date, updated, count, top_n,
   h: {ETF코드: [전체구성종목수, [[종목코드, 종목명, 비중%], ...상위 TOP_N]]}}
  ※ 비중이 비어 있는 ETF는 금액(원) 비율로 계산해서 채움 (w_src="amt" 표시)

사용법
  python3 scripts/fetch_kr_etf_holdings.py --limit 20   # 테스트: 20개만, 저장 안 함, 시간·모양 출력
  python3 scripts/fetch_kr_etf_holdings.py              # 전체 (약 20~30분)

크론 (토 10:00, 아래 줄에 붙임: fetch_kr_etf.py 18:40 줄 아래)
0 10 * * 6 . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/fetch_kr_etf_holdings.py >> ~/logs/fetch_kr_etf_holdings.log 2>&1
"""
import os, sys, json, time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETF_DIR = os.path.join(ROOT, 'data', 'kr', 'etf')
LATEST = os.path.join(ETF_DIR, 'latest.json')
OUT = os.path.join(ETF_DIR, 'holdings.json')
TOP_N = 10
SLEEP = 0.4


def log(*a):
    print(datetime.now(KST).strftime('%H:%M:%S'), *a, flush=True)


def num(v):
    try:
        f = float(v)
        return None if f != f else f
    except Exception:
        return None


def parse(df):
    """DataFrame → (전체수, [[코드,이름,비중],...], 비중출처)"""
    if df is None or len(df) == 0:
        return 0, [], None
    rows = []
    for code, r in df.iterrows():
        rows.append([str(code), str(r.get('구성종목명', '') or ''), num(r.get('비중')), num(r.get('금액'))])
    src = 'w'
    if not any(x[2] for x in rows):          # 비중이 전부 비었으면 금액 비율
        tot = sum(x[3] or 0 for x in rows)
        if tot > 0:
            for x in rows:
                x[2] = (x[3] or 0) / tot * 100
            src = 'amt'
        else:
            src = None
    rows.sort(key=lambda x: -(x[2] or 0))
    top = [[x[0], x[1], round(x[2], 2) if x[2] is not None else None] for x in rows[:TOP_N]]
    return len(rows), top, src


def main():
    limit = None
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])

    d = json.load(open(LATEST, encoding='utf-8'))
    day = d['date'].replace('-', '')
    ci = d['cols'].index('code'); ni = d['cols'].index('name'); ai = d['cols'].index('aum_eok')
    etfs = [(r[ci], r[ni], r[ai] or 0) for r in d['rows']]
    if limit:
        # 테스트: 순자산 큰 것 + 해외·채권·원자재 섞어서
        etfs.sort(key=lambda x: -x[2])
        etfs = etfs[:limit]
    log(f'기준일 {day} / 대상 {len(etfs)}개' + (' (테스트, 저장 안 함)' if limit else ''))

    from pykrx import stock
    out, fail, amt_cnt, empty = {}, [], 0, 0
    t0 = time.time()
    for i, (code, name, aum) in enumerate(etfs, 1):
        try:
            df = stock.get_etf_portfolio_deposit_file(code, day)
            n, top, src = parse(df)
            if n == 0:
                empty += 1
            if src == 'amt':
                amt_cnt += 1
            out[code] = [n, top]
            if limit:
                t = ' / '.join(f'{x[1][:10]} {x[2]}%' for x in top[:3])
                log(f'  {code} {name[:18]} 구성 {n}개 [{src}] {t}')
        except Exception as e:
            fail.append(code)
            log(f'  ❌ {code} {name[:18]} {repr(e)[:100]}')
        if i % 100 == 0:
            el = time.time() - t0
            log(f'  진행 {i}/{len(etfs)} ({el/60:.1f}분, 남은 약 {el/i*(len(etfs)-i)/60:.0f}분)')
        time.sleep(SLEEP)

    el = time.time() - t0
    log(f'완료 {len(out)}개 / 실패 {len(fail)} / 구성 0개 {empty} / 금액비율로 계산 {amt_cnt} / {el/60:.1f}분')
    if limit:
        log(f'  → 전체 1,190개 예상 약 {el/len(etfs)*1190/60:.0f}분')
        return
    if len(out) < len(etfs) * 0.8:
        log('❌ 80% 미만 성공 — 기존 파일 유지')
        sys.exit(1)
    res = {'date': d['date'], 'updated': datetime.now(KST).strftime('%Y-%m-%d %H:%M'),
           'count': len(out), 'top_n': TOP_N, 'h': out}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, separators=(',', ':'))
    log(f'✅ holdings.json {len(out)}개 ({os.path.getsize(OUT)//1024}KB)')


if __name__ == '__main__':
    main()
