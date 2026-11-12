#!/usr/bin/env python3
"""
국내 ETF 해외 구성종목 추정 비중 (083) — VM 전용, 주 1회 (구성종목 수집 다음)
=========================================================================
KRX는 해외 종목에 비중·금액을 안 주고 CU당 계약수(주식 수)만 줌 → 직접 계산
  비중 ≈ 계약수 × 해외 주가 × 원화 환율 ÷ (값을 구한 종목들의 합)
  - 국내 종목은 KRX 금액(원) 그대로, 현금·선물·스왑 등 주식 아닌 것은 뺌 → "주식 부분 기준" 비중
  - 티커: OpenFIGI(미국·일본·중국A) + 야후 검색(나머지)  ← fetch_isin_map.py 가 만든 캐시
  - 주가·환율: yfinance 최근 종가 (영국 .L 은 펜스라 ÷100, 이스라엘·남아공도 ÷100)

입력: ~/sf_data/etf_pdf_foreign.json, data/kr/etf/isin_map.json, data/kr/etf/yahoo_map.json
출력: data/kr/etf/holdings.json 의 해당 ETF 항목을 [구성수, 상위10[[코드,이름,비중]], 'est', 커버율%] 로 바꿈
  - KRX가 비중을 준 ETF('w')는 안 건드림
  - 커버율(값을 구한 주식 수 ÷ 전체 주식 수)이 80% 미만이면 안 바꾸고 로그만 남김

사용법
  python3 scripts/fetch_kr_etf_weights.py --test   # 계산만, 저장 안 함 (대표 ETF 결과·커버율 출력)
  python3 scripts/fetch_kr_etf_weights.py          # 계산 후 holdings.json 갱신
"""
import os, sys, json, time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_isin_map import figi_symbol, isin_ok

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETF_DIR = os.path.join(ROOT, 'data', 'kr', 'etf')
RAW = os.path.expanduser('~/sf_data/etf_pdf_foreign.json')
HOLD = os.path.join(ETF_DIR, 'holdings.json')
MIN_COVER = 80
TOP_N = 10
CHUNK = 200

# 야후 접미사 → (통화, 나눌 값)
SFX = {'': ('USD', 1), 'T': ('JPY', 1), 'SS': ('CNY', 1), 'SZ': ('CNY', 1), 'HK': ('HKD', 1),
       'TW': ('TWD', 1), 'TWO': ('TWD', 1), 'NS': ('INR', 1), 'BO': ('INR', 1), 'L': ('GBP', 100),
       'IL': ('GBP', 100), 'PA': ('EUR', 1), 'AS': ('EUR', 1), 'DE': ('EUR', 1), 'F': ('EUR', 1),
       'MI': ('EUR', 1), 'MC': ('EUR', 1), 'BR': ('EUR', 1), 'HE': ('EUR', 1), 'LS': ('EUR', 1),
       'VI': ('EUR', 1), 'IR': ('EUR', 1), 'SW': ('CHF', 1), 'ST': ('SEK', 1), 'CO': ('DKK', 1),
       'OL': ('NOK', 1), 'TO': ('CAD', 1), 'V': ('CAD', 1), 'NE': ('CAD', 1), 'AX': ('AUD', 1),
       'SI': ('SGD', 1), 'TA': ('ILS', 100), 'SA': ('BRL', 1), 'NZ': ('NZD', 1), 'MX': ('MXN', 1),
       'JO': ('ZAR', 100), 'JK': ('IDR', 1), 'BK': ('THB', 1), 'KL': ('MYR', 1), 'VN': ('VND', 1),
       'WA': ('PLN', 1), 'IS': ('TRY', 1), 'SR': ('SAR', 1), 'QA': ('QAR', 1), 'KS': ('KRW', 1),
       'KQ': ('KRW', 1), 'PR': ('CZK', 1), 'BD': ('HUF', 1), 'AT': ('EUR', 1), 'CL': ('CLP', 1),
       'HA': ('EUR', 1), 'SG': ('EUR', 1), 'DU': ('EUR', 1), 'MU': ('EUR', 1), 'BE': ('EUR', 1), 'HM': ('EUR', 1)}


def log(*a):
    print(datetime.now(KST).strftime('%H:%M:%S'), *a, flush=True)


def load(p, default=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default


def sfx_of(sym):
    return sym.rsplit('.', 1)[1] if '.' in sym else ''


def last_close(syms):
    """yfinance 최근 종가 {티커: 값}. 200개씩 나눠 받음."""
    import yfinance as yf
    out = {}
    for i in range(0, len(syms), CHUNK):
        part = syms[i:i + CHUNK]
        for attempt in range(2):
            try:
                df = yf.download(part, period='10d', progress=False, auto_adjust=False, threads=True)['Close']
                if len(part) == 1:
                    df = df.to_frame(part[0]) if hasattr(df, 'to_frame') else df
                last = df.ffill().iloc[-1]
                for s in part:
                    try:
                        v = float(last[s])
                        if v == v and v > 0:
                            out[s] = v
                    except Exception:
                        pass
                break
            except Exception as e:
                log(f'  ⚠ yfinance {i}~ 실패 ({repr(e)[:80]}) — 20초 뒤 다시')
                time.sleep(20)
        time.sleep(1)
    return out


def main():
    test = '--test' in sys.argv
    raw = load(RAW)
    if not raw:
        log(f'❌ {RAW} 없음 (fetch_kr_etf_holdings.py 먼저)')
        sys.exit(1)
    fm = (load(os.path.join(ETF_DIR, 'isin_map.json'), {}) or {}).get('m', {})
    ym = (load(os.path.join(ETF_DIR, 'yahoo_map.json'), {}) or {}).get('m', {})
    hold = load(HOLD)
    if not hold:
        log('❌ holdings.json 없음')
        sys.exit(1)

    def sym_of(isin):
        v = fm.get(isin)
        s = figi_symbol(isin, v[1]) if v else None
        if not s and isin in ym:
            s = ym[isin][0]
        return s

    # 1) 필요한 티커 모으기
    need = {}
    for rows in raw['e'].values():
        for cd, nm, sh, amt in rows:
            if len(cd) == 12 and not cd.startswith('KR') and isin_ok(cd) and sh > 0:
                s = sym_of(cd)
                if s:
                    need[cd] = s
    syms = sorted(set(need.values()))
    unknown_sfx = sorted({sfx_of(s) for s in syms if sfx_of(s) not in SFX})
    if unknown_sfx:
        log(f'  ⚠ 통화 모르는 접미사 {unknown_sfx} → 해당 종목 제외')
    curs = sorted({SFX[sfx_of(s)][0] for s in syms if sfx_of(s) in SFX} - {'KRW'})
    log(f'티커 {len(syms)}개 / 통화 {len(curs)}개 ({", ".join(curs)})')

    # 2) 주가·환율
    t0 = time.time()
    px = last_close(syms)
    fxp = last_close([f'{c}KRW=X' for c in curs])
    fx = {c: fxp.get(f'{c}KRW=X') for c in curs}
    # 원화 직거래 시세가 없는 통화(칠레·이스라엘·멕시코·노르웨이·베트남 등)는 달러 교차: XXX/KRW = USD/KRW ÷ USD/XXX
    gap = [c for c in curs if not fx.get(c) and c != 'USD']
    if gap and fx.get('USD'):
        usdx = last_close([f'{c}=X' for c in gap])
        for c in gap:
            if usdx.get(f'{c}=X'):
                fx[c] = fx['USD'] / usdx[f'{c}=X']
        log(f'  ↪ 달러 교차환율 {sum(1 for c in gap if fx.get(c))}/{len(gap)}개 ({", ".join(gap)})')
    fx['KRW'] = 1.0
    miss_fx = [c for c in curs if not fx.get(c)]
    log(f'종가 {len(px)}/{len(syms)}개 · 환율 {len(curs)-len(miss_fx)}/{len(curs)}개'
        + (f' (못 받은 통화 {miss_fx})' if miss_fx else '') + f' · {time.time()-t0:.0f}초')
    if len(px) < len(syms) * 0.5:
        log('❌ 종가를 절반도 못 받음 — 저장 안 함')
        sys.exit(1)

    def krw(isin, sh):
        s = need.get(isin)
        if not s or s not in px:
            return None
        cur, div = SFX.get(sfx_of(s), (None, 1))
        if not cur or not fx.get(cur):
            return None
        return sh * px[s] / div * fx[cur]

    # 3) ETF별 비중
    res, low, kept_w, n_est = {}, [], 0, 0
    for etf, rows in raw['e'].items():
        cur = hold['h'].get(etf)
        has_w = bool(cur and len(cur) >= 2 and cur[1] and cur[1][0][2] is not None and (len(cur) < 3 or cur[2] != 'est'))
        if has_w:
            # KRX 비중이 이미 있는 ETF: 해외 종목이 금액 0(빠진 채)으로 계산된 국내+해외 혼합만 다시 계산
            f_zero = any(len(c) == 12 and not c.startswith('KR') and isin_ok(c) and a == 0 and sh > 0 for c, _, sh, a in rows)
            d_amt = any((c.startswith('KR7') or (len(c) == 6 and c[:5].isdigit())) and a > 0 for c, _, sh, a in rows)
            if not (f_zero and d_amt):
                kept_w += 1
                continue
        vals, total_eq = [], 0
        for cd, nm, sh, amt in rows:
            if len(cd) == 12 and not cd.startswith('KR') and isin_ok(cd):
                total_eq += 1
                v = krw(cd, sh)
                if v:
                    vals.append([cd, nm, v])
            elif cd.startswith('KR7') or (len(cd) == 6 and cd[:5].isdigit()):
                total_eq += 1
                if amt > 0:
                    vals.append([cd, nm, float(amt)])
        if not total_eq or not vals:
            continue
        cover = round(len(vals) / total_eq * 100)
        tot = sum(v[2] for v in vals)
        vals.sort(key=lambda x: -x[2])
        top = [[(c[3:9] if len(c) > 6 else c), nm, round(v / tot * 100, 2)] for c, nm, v in vals[:TOP_N]]
        if cover < MIN_COVER:
            low.append((etf, cover, total_eq))
            continue
        res[etf] = [total_eq if not cur else cur[0], top, 'est', cover]
        n_est += 1

    log(f'추정 비중 {n_est}개 ETF (커버율 {MIN_COVER}% 미만이라 제외 {len(low)}개 / KRX 비중 그대로 {kept_w}개)')
    if low:
        log('  제외 예: ' + ', '.join(f'{e}({c}%/{n}종목)' for e, c, n in sorted(low, key=lambda x: x[1])[:10]))

    if test:
        names = {}
        d = load(os.path.join(ETF_DIR, 'latest.json'), {})
        if d:
            ci, ni = d['cols'].index('code'), d['cols'].index('name')
            names = {r[ci]: r[ni] for r in d['rows']}
        for etf in ['360750', '133690', '0015K0', '0002C0', '381170', '453870', '0046A0']:
            if etf in res:
                e = res[etf]
                print(f'   {etf} {names.get(etf, "")[:22]} (구성 {e[0]}, 커버 {e[3]}%)')
                print('      ' + ' / '.join(f'{x[1][:16]} {x[2]:.1f}%' for x in e[1][:6]))
        log('🧪 테스트라 저장 안 함')
        return

    hold['h'].update(res)
    hold['est_updated'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M')
    tmp = HOLD + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(hold, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, HOLD)
    log(f'💾 holdings.json 갱신 — 추정 비중 {n_est}개 ETF ({os.path.getsize(HOLD)//1024}KB)')


if __name__ == '__main__':
    main()
