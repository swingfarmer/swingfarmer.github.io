#!/usr/bin/env python3
"""
국내 ETF 구성종목(PDF) 수집 (082 2단계) — VM 크론 전용, 주 1회
================================================================
pykrx get_etf_portfolio_deposit_file(티커, 날짜) 로 ETF별 구성종목을 받아
비중 상위 TOP_N개만 저장. 종목 목록은 data/kr/etf/latest.json (fetch_kr_etf.py 결과).

출력
  data/kr/etf/holdings.json
  {date, updated, count, top_n,
   h: {ETF코드: [전체구성종목수, [[종목코드, 종목명, 비중%], ...]]}}
  - 국내: 비중 상위 TOP_N. 비중 칸이 비면 금액(원) 비율로 계산
  - 해외: KRX가 비중·금액을 안 줌(계약수만). 구성 30개 이하면 이름 전체(비중 null), 초과면 빈 목록

  (083) pykrx 래퍼 대신 KRX 원본(PDF().fetch)을 직접 불러 해외 종목의 전체 ISIN(12자리)을 받음.
        holdings.json 형식·값은 예전과 같음(pykrx와 같은 방식으로 6자리로 줄여 저장).
        해외 종목이 하나라도 있는 ETF는 전체 행을 VM 로컬에 따로 저장 → 해외 비중 계산용
          ~/sf_data/etf_pdf_foreign.json
          {date, updated, e: {ETF코드: [[ISIN또는코드, 이름, CU당 계약수, 금액(원)], ...]}}

사용법
  python3 scripts/fetch_kr_etf_holdings.py --limit 20             # 테스트: 20개만, 저장 안 함, 시간·모양 출력
  python3 scripts/fetch_kr_etf_holdings.py --limit 60 --compare   # 테스트 + 기존 holdings.json과 같은지 비교
  python3 scripts/fetch_kr_etf_holdings.py                        # 전체 (약 16분)

크론 (토 10:00, 아래 줄에 붙임: fetch_kr_etf.py 18:40 줄 아래)
0 10 * * 6 . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/fetch_kr_etf_holdings.py >> ~/logs/fetch_kr_etf_holdings.log 2>&1
"""
import os, sys, json, re, time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETF_DIR = os.path.join(ROOT, 'data', 'kr', 'etf')
LATEST = os.path.join(ETF_DIR, 'latest.json')
OUT = os.path.join(ETF_DIR, 'holdings.json')
RAW_DIR = os.path.expanduser('~/sf_data')
RAW_OUT = os.path.join(RAW_DIR, 'etf_pdf_foreign.json')   # 레포 밖 (083)
BOND_OUT = os.path.join(RAW_DIR, 'etf_pdf_bond.json')     # 채권·금리·혼합형 ETF 전체 행 (083, 채권 ETF 분석용)
BOND_RE = re.compile('국고채|국채|회사채|채권|크레딧|국공채|통안채|금융채|미국채|장기채|단기채|물가채|하이일드|은행채|'
                     '머니마켓|CD금리|CD1년|KOFR|SOFR|금리|혼합|TDF|TRF|만기|단기자금|달러단기|국고|특수채|전단채|커버드콜채')
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


NOW_MAX = 30   # 비중 없는(해외) ETF는 구성 이 개수 이하일 때만 이름 전체 저장


def raw_num(v):
    """KRX 원본 숫자 문자열 → float. '-'·빈칸은 0 (pykrx와 같은 처리)."""
    s = str(v if v is not None else '').replace(',', '').strip()
    if s in ('', '-'):
        return 0.0
    try:
        f = float(s)
        return 0.0 if f != f else f
    except Exception:
        return 0.0


def fetch_pdf(code, day):
    """KRX PDF 원본 → (pykrx 형식 DataFrame, 원본 행 [[전체코드, 이름, 계약수, 금액], ...]).
    pykrx get_etf_portfolio_deposit_file 과 같은 DataFrame을 만들되, 잘리기 전 전체 ISIN도 같이 돌려줌."""
    import pandas as pd
    from pykrx.website.krx.etx.core import PDF
    from pykrx.website.krx.etx.ticker import get_etx_isin
    raw = PDF().fetch(day, get_etx_isin(code))
    if raw is None or len(raw) == 0:
        return None, []
    idx, data, full = [], [], []
    for _, r in raw.iterrows():
        cd = str(r.get('COMPST_ISU_CD', '') or '').strip()
        nm = str(r.get('COMPST_ISU_NM', '') or '').strip()
        sh = raw_num(r.get('COMPST_ISU_CU1_SHRS'))
        amt = raw_num(r.get('VALU_AMT'))
        idx.append(cd[3:9] if len(cd) > 6 else cd)      # pykrx와 같은 6자리 축약
        data.append({'구성종목명': nm, '계약수': sh, '금액': int(amt),
                     '시가총액': int(raw_num(r.get('COMPST_AMT'))), '비중': raw_num(r.get('COMPST_RTO'))})
        full.append([cd, nm, sh, int(amt)])
    df = pd.DataFrame(data, index=idx)
    return df, full


def is_foreign(cd):
    return len(cd) == 12 and cd[:2].isalpha() and not cd.startswith('KR')


def parse(df):
    """DataFrame → (전체수, [[코드,이름,비중],...], 비중출처)
    비중출처: 'w' 비중 칸 / 'amt' 금액 비율 / 'names' 비중 없음·이름만 / None 저장 안 함
    해외 종목은 KRX가 비중·금액을 0으로 줌(계약수만 있음) → 비중 계산 불가"""
    if df is None or len(df) == 0:
        return 0, [], None
    rows = []
    for code, r in df.iterrows():
        rows.append([str(code), str(r.get('구성종목명', '') or '').strip(), num(r.get('비중')), num(r.get('금액'))])
    n = len(rows)
    src = 'w'
    if not any(x[2] for x in rows):          # 비중이 전부 비었으면 금액 비율
        tot = sum(x[3] or 0 for x in rows)
        if tot > 0:
            for x in rows:
                x[2] = (x[3] or 0) / tot * 100
            src = 'amt'
        else:
            src = 'names' if n <= NOW_MAX else None
    if src == 'names':
        return n, [[x[0], x[1], None] for x in rows], src
    if src is None:
        return n, [], None
    rows.sort(key=lambda x: -(x[2] or 0))
    top = [[x[0], x[1], round(x[2], 2)] for x in rows[:TOP_N] if (x[2] or 0) > 0]
    return n, top, src


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

    compare = '--compare' in sys.argv
    out, fail, amt_cnt, empty, names_cnt, none_cnt = {}, [], 0, 0, 0, 0
    foreign, bond = {}, {}
    t0 = time.time()
    for i, (code, name, aum) in enumerate(etfs, 1):
        try:
            df, full = fetch_pdf(code, day)
            n, top, src = parse(df)
            if any(is_foreign(x[0]) for x in full):
                foreign[code] = full
            if BOND_RE.search(name or '') and df is not None:
                ws = [round(float(x or 0), 4) for x in df['비중'].tolist()]
                bond[code] = [x + [w] for x, w in zip(full, ws)]   # [코드, 이름, 계약수, 금액, 비중%]
            if n == 0:
                empty += 1
            if src == 'amt':
                amt_cnt += 1
            elif src == 'names':
                names_cnt += 1
            elif src is None and n:
                none_cnt += 1
            out[code] = [n, top]
            if limit:
                t = ' / '.join(f'{x[1][:10]} {x[2]}%' if x[2] is not None else x[1][:12] for x in top[:3])
                log(f'  {code} {name[:18]} 구성 {n}개 [{src}] {t}')
        except Exception as e:
            fail.append(code)
            log(f'  ❌ {code} {name[:18]} {repr(e)[:100]}')
        if i % 100 == 0:
            el = time.time() - t0
            log(f'  진행 {i}/{len(etfs)} ({el/60:.1f}분, 남은 약 {el/i*(len(etfs)-i)/60:.0f}분)')
        time.sleep(SLEEP)

    el = time.time() - t0
    log(f'완료 {len(out)}개 / 실패 {len(fail)} / 구성 0개 {empty} / 금액비율 {amt_cnt} / '
        f'해외 이름만 {names_cnt} / 해외 개수만 {none_cnt} / {el/60:.1f}분')
    # 해외 종목 통계 (083)
    isins = {}
    for rows in foreign.values():
        for x in rows:
            if is_foreign(x[0]):
                isins[x[0]] = x[1]
    by_cty = {}
    for i in isins:
        by_cty[i[:2]] = by_cty.get(i[:2], 0) + 1
    log(f'해외 종목 든 ETF {len(foreign)}개 / 고유 해외 ISIN {len(isins)}개 / 국가별 '
        + ', '.join(f'{k} {v}' for k, v in sorted(by_cty.items(), key=lambda x: -x[1])))

    if limit:
        log(f'  → 전체 1,190개 예상 약 {el/len(etfs)*1190/60:.0f}분')
        if compare:
            try:
                old = json.load(open(OUT, encoding='utf-8'))
            except Exception:
                old = None
            if not old or old.get('date') != d['date']:
                log(f"  비교 불가: 기존 holdings.json 기준일 {old and old.get('date')} ≠ {d['date']}")
            else:
                same = sum(1 for c in out if old['h'].get(c) == out[c])
                diff = [c for c in out if old['h'].get(c) != out[c]]
                log(f'  기존 holdings.json과 비교: 같음 {same} / 다름 {len(diff)}')
                for c in diff[:5]:
                    log(f'    다름 {c}: 기존 {str(old["h"].get(c))[:150]}')
                    log(f'           새것 {str(out[c])[:150]}')
        return
    if len(out) < len(etfs) * 0.8:
        log('❌ 80% 미만 성공 — 기존 파일 유지')
        sys.exit(1)
    res = {'date': d['date'], 'updated': datetime.now(KST).strftime('%Y-%m-%d %H:%M'),
           'count': len(out), 'top_n': TOP_N, 'h': out}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, separators=(',', ':'))
    log(f'✅ holdings.json {len(out)}개 ({os.path.getsize(OUT)//1024}KB)')

    # 해외 종목 원본 — VM 로컬 (083, 해외 비중 계산용)
    os.makedirs(RAW_DIR, exist_ok=True)
    tmp = RAW_OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'date': d['date'], 'updated': res['updated'], 'e': foreign}, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, RAW_OUT)
    log(f'💾 {RAW_OUT} ETF {len(foreign)}개 ({os.path.getsize(RAW_OUT)//1024}KB)')
    tmp = BOND_OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'date': d['date'], 'updated': res['updated'], 'e': bond}, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, BOND_OUT)
    log(f'💾 {BOND_OUT} 채권·금리·혼합형 ETF {len(bond)}개 ({os.path.getsize(BOND_OUT)//1024}KB)')


if __name__ == '__main__':
    main()
