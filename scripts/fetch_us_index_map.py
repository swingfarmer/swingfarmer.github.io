#!/usr/bin/env python3
"""
미국 S&P500 · 나스닥100 히트맵 데이터 (088) — VM 크론 전용, 월~토 07:20 (미장 마감 후. 월요일은 금요일 종가를 다시 저장 — 헬스체크 월요일 경고 방지)
==========================================================================
구성종목은 따로 안 모으고, 이미 주 1회 받고 있는 국내 ETF PDF를 쓴다.
  S&P500   = TIGER 미국S&P500 (360750) 구성 전체 (약 505종목)
  나스닥100 = TIGER 미국나스닥100 (133690) 구성 전체 (약 103종목)
  ~/sf_data/etf_pdf_foreign.json  ← fetch_kr_etf_holdings.py (토 10:00) 가 저장하는 전체 행
  ISIN → 티커: data/kr/etf/isin_map.json + yahoo_map.json  ← fetch_isin_map.py (토, 이어서 실행)

계산
  비중(타일 크기) = CU당 주식 수 × 전일 종가 ÷ 합계   (지수 비중 ≈ 유동 시가총액 비중과 거의 같음)
  등락률 = 종목별 마지막 종가 ÷ 그 전 종가 − 1  (yfinance, 10일치 받아서)
  ETF가 지수를 그대로 따라가므로 비중은 지수 비중과 거의 같다. 주식 수는 주 1회라 그 사이 지수 변경은 다음 토요일에 반영.

출력: data/us/index_map.json
  {date(미국 종가 날짜), updated, sp500: {etf, pdf_date, n, cover, items: [[티커, 이름, 비중%, 종가$, 등락%|null], ...]}, ndx: {...}}
  - 비중 큰 순. 등락이 null이면 그 종목만 마지막 날 종가가 없음(거래정지·신규 상장 등) → 화면 회색
  - 커버율(종가를 구한 종목 수 ÷ 구성 주식 수) 90% 미만이면 저장 안 하고 기존 파일 유지(헬스체크가 오래됨으로 잡음)

사용법
  python3 scripts/fetch_us_index_map.py --test   # 계산만, 저장 안 함 (상위 10·커버율 출력)
  python3 scripts/fetch_us_index_map.py          # 저장
"""
import os, sys, json, time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_isin_map import figi_symbol, isin_ok

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETF_DIR = os.path.join(ROOT, 'data', 'kr', 'etf')
RAW = os.path.expanduser('~/sf_data/etf_pdf_foreign.json')
OUT = os.path.join(ROOT, 'data', 'us', 'index_map.json')
INDEXES = [('sp500', '360750', 'TIGER 미국S&P500'), ('ndx', '133690', 'TIGER 미국나스닥100')]
MIN_COVER = 90
CHUNK = 200


def log(*a):
    print(datetime.now(KST).strftime('%H:%M:%S'), *a, flush=True)


def load(p, default=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default


def closes(syms):
    """yfinance 10일치 종가 → {티커: [(날짜, 종가), ...]} (값 있는 날만, 오래된 순)."""
    import yfinance as yf
    out = {}
    for i in range(0, len(syms), CHUNK):
        part = syms[i:i + CHUNK]
        for attempt in range(2):
            try:
                df = yf.download(part, period='10d', progress=False, auto_adjust=False, threads=True)['Close']
                if len(part) == 1 and not hasattr(df, 'columns'):
                    df = df.to_frame(part[0])
                for s in part:
                    if s not in df.columns:
                        continue
                    ser = df[s].dropna()
                    out[s] = [(d.strftime('%Y-%m-%d'), float(v)) for d, v in ser.items() if v > 0]
                break
            except Exception as e:
                log(f'  ⚠ yfinance {i}~ 실패 ({repr(e)[:80]}) — 20초 뒤 다시')
                time.sleep(20)
        time.sleep(1)
    return out


def build(raw, fm, ym, get_closes):
    """→ (결과 dict 또는 None, 로그용 문자열 목록). get_closes 는 테스트에서 가짜로 바꿀 수 있게 인자로 받음."""
    def sym_of(isin):
        v = fm.get(isin)
        # 미국 밖 ISIN이라도 미국에 상장돼 있으면 그 티커 (영국 CCEP, 캐나다 TRI 등 — 야후 검색은 본국 티커 CCEP.AS·TRI.TO를 줘서 빠졌음, 088)
        for ex, tk in (v[1] if v and v[1] else []):
            if ex == 'US':
                return tk.replace('/', '-')
        s = figi_symbol(isin, v[1]) if v else None
        if not s and isin in ym:
            s = ym[isin][0]
        return s

    rows_by = {}
    need = {}
    for key, etf, _ in INDEXES:
        rows = raw['e'].get(etf) or []
        eq = [(cd, nm, sh) for cd, nm, sh, amt in rows if len(cd) == 12 and not cd.startswith('KR') and isin_ok(cd) and sh > 0]
        rows_by[key] = eq
        for cd, nm, sh in eq:
            s = sym_of(cd)
            if s and '.' not in s:          # 미국 상장 티커만 (접미사 없는 것). 다른 거래소 티커면 달러가 아니라 뺌
                need[cd] = s
    syms = sorted(set(need.values()))
    px = get_closes(syms)
    last_dates = sorted({v[-1][0] for v in px.values() if v})
    if not last_dates:
        return None, ['❌ 종가를 하나도 못 받음']
    date = last_dates[-1]
    msgs = [f'티커 {len(syms)}개 / 종가 {sum(1 for s in syms if px.get(s))}개 / 미국 종가 날짜 {date}']

    res = {'date': date}
    ok = True
    for key, etf, ename in INDEXES:
        eq = rows_by[key]
        if not eq:
            msgs.append(f'❌ {ename}({etf}) 구성 행이 없음')
            ok = False
            continue
        items, seen = [], set()
        for cd, nm, sh in eq:
            s = need.get(cd)
            p = px.get(s) if s else None
            if not p or s in seen:
                continue
            seen.add(s)
            c = p[-1][1]
            chg = None
            if p[-1][0] == date and len(p) >= 2:
                chg = round((c / p[-2][1] - 1) * 100, 2)
            items.append([s, nm, sh * c, round(c, 2), chg])
        cover = round(len(items) / len(eq) * 100)
        tot = sum(x[2] for x in items) or 1
        for x in items:
            x[2] = round(x[2] / tot * 100, 4)
        items.sort(key=lambda x: -x[2])
        miss = [nm for cd, nm, sh in eq if not (need.get(cd) and px.get(need[cd]))][:8]
        msgs.append(f'{ename}: 구성 {len(eq)} / 종가 구함 {len(items)} (커버 {cover}%)'
                    + (f' / 못 구한 예: {", ".join(miss)}' if miss else ''))
        if cover < MIN_COVER:
            msgs.append(f'❌ {ename} 커버율 {cover}% < {MIN_COVER}%')
            ok = False
        res[key] = {'etf': f'{etf} {ename}', 'pdf_date': raw.get('date'), 'n': len(eq), 'cover': cover, 'items': items}
    return (res if ok else None), msgs


def main():
    test = '--test' in sys.argv
    raw = load(RAW)
    if not raw:
        log(f'❌ {RAW} 없음 (fetch_kr_etf_holdings.py 먼저)')
        sys.exit(1)
    fm = (load(os.path.join(ETF_DIR, 'isin_map.json'), {}) or {}).get('m', {})
    ym = (load(os.path.join(ETF_DIR, 'yahoo_map.json'), {}) or {}).get('m', {})
    t0 = time.time()
    res, msgs = build(raw, fm, ym, closes)
    for m in msgs:
        log(m)
    log(f'{time.time()-t0:.0f}초')
    if res is None:
        log('❌ 저장 안 함 — 기존 파일 유지')
        sys.exit(1)
    if test:
        for key, _, ename in INDEXES:
            print(f'   {ename} 상위 10')
            print('      ' + ' / '.join(f'{x[0]} {x[2]:.2f}% {x[4] if x[4] is not None else "-"}%' for x in res[key]['items'][:10]))
        log('🧪 테스트라 저장 안 함')
        return
    res['updated'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    log(f'✅ {OUT} ({os.path.getsize(OUT)//1024}KB)')


if __name__ == '__main__':
    main()
