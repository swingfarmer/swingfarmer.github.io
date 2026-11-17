"""
(108) 증시 자금·밸류 지표 → data/dashboard/market_funds.json  (/today/ 시장 국면 점수용)
  - 고객예탁금·신용융자잔고·미수금: KIS 「국내 증시자금 종합」(FHKST649100C0, 원자료 금융투자협회)
      단위 억원 — 108 조회로 검산(11/10 예탁금 85조2,208억·신용 26조5,493억 기사와 같은 자릿수).
      같은 응답의 시가총액(hts_avls)은 백만원이라 안 씀. 한 번 부르면 입력 날짜부터 거꾸로 100영업일.
      금투협 집계라 하루 늦게 나옴(18시대에 부르면 전 영업일까지).
  - 코스피 PER·PBR·배당수익률: pykrx get_index_fundamental('1001') — KRX 로그인 세션(KRX_ID/KRX_PW)
  - 10년 백분위(per_pct·lev_pct)를 같이 저장 → 페이지는 점수만 매김
      lev = 신용융자잔고 ÷ 고객예탁금 (%)  — 대기자금 대비 빚투 비중
  - 0·빈 값은 휴장·결측으로 보고 저장 안 함(107 규칙). 새 결과가 기존 행 수의 80% 미만이면 저장 안 함.
사용: python3 scripts/fetch_market_funds.py              (최근분 — 크론)
      python3 scripts/fetch_market_funds.py --backfill   (2016년부터 다시 받기, 처음 한 번)
"""
import os, sys, json, time, argparse, urllib.request, urllib.parse
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'dashboard', 'market_funds.json')
START = '20160101'
YEARS_PCT = 10


def num(x):
    try:
        v = float(str(x).replace(',', ''))
    except Exception:
        return None
    return v if v > 0 else None


def kis_funds(token, L, end):
    q = urllib.parse.urlencode({'FID_INPUT_DATE_1': end})
    req = urllib.request.Request(f'{L.KIS_BASE}/uapi/domestic-stock/v1/quotations/mktfunds?{q}', headers={
        'Content-Type': 'application/json; charset=UTF-8', 'authorization': f'Bearer {token}',
        'appkey': L.KIS_APP_KEY, 'appsecret': L.KIS_APP_SECRET, 'tr_id': 'FHKST649100C0', 'custtype': 'P'})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read().decode('utf-8'))
    if res.get('rt_cd') != '0':
        raise RuntimeError(f"KIS 오류 {res.get('msg_cd')} {res.get('msg1')}")
    out = res.get('output') or []
    return out if isinstance(out, list) else [out]


def get_funds(backfill):
    import fetch_live_prices as L
    token = L.get_token()
    if not token:
        print('❌ KIS 토큰 없음 (70초 뒤 다시)'); return None
    rows, end = {}, ''
    while True:
        out = kis_funds(token, L, end)
        got = 0
        for o in out:
            d = o.get('bsop_date') or ''
            if len(d) != 8:
                continue
            dep, cr = num(o.get('cust_dpmn_amt')), num(o.get('crdt_loan_rmnd'))
            if dep is None or cr is None:
                continue
            rows[d] = {'dep': round(dep), 'credit': round(cr), 'unpaid': (round(num(o.get('uncl_amt'))) if num(o.get('uncl_amt')) else None)}
            got += 1
        oldest = min((o.get('bsop_date') for o in out if o.get('bsop_date')), default=None)
        if not backfill or not got or not oldest or oldest <= START:
            break
        end = (datetime.strptime(oldest, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
        print(f'  예탁금·신용 {oldest[:4]}-{oldest[4:6]} 까지 {len(rows)}일')
        time.sleep(0.5)
    return rows


def get_per(backfill):
    from pykrx import stock
    t = date.today()
    spans = []
    if backfill:
        y = int(START[:4])
        while y <= t.year:
            spans.append((f'{y}0101', f'{y}1231' if y < t.year else t.strftime('%Y%m%d'))); y += 1
    else:
        spans.append(((t - timedelta(days=30)).strftime('%Y%m%d'), t.strftime('%Y%m%d')))
    rows = {}
    for s, e in spans:
        df = stock.get_index_fundamental(s, e, '1001')
        for idx, r in df.iterrows():
            per, pbr = num(r.get('PER')), num(r.get('PBR'))
            if per is None:
                continue
            rows[idx.strftime('%Y%m%d')] = {'per': round(per, 2), 'pbr': (round(pbr, 2) if pbr else None),
                                           'dy': (round(float(r.get('배당수익률')), 2) if num(r.get('배당수익률')) else None)}
        if backfill:
            print(f'  PER {s[:4]}: {len(rows)}일'); time.sleep(1)
    return rows


def pct_rank(vals, v):
    """vals 안에서 v의 백분위(0~100, 같은 값은 가운데)."""
    if not vals or v is None:
        return None
    lt = sum(1 for x in vals if x < v); le = sum(1 for x in vals if x <= v)
    return round((lt + le) / 2 / len(vals) * 100, 1)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--backfill', action='store_true'); a = ap.parse_args()
    old = {}
    if os.path.exists(OUT):
        try:
            old = {r[0]: r for r in json.load(open(OUT, encoding='utf-8')).get('history', [])}
        except Exception:
            old = {}
    if not old and not a.backfill:
        print('ℹ️ 기존 파일 없음 → --backfill 로 처음부터 받음'); a.backfill = True

    funds, pers, errs = {}, {}, []
    try:
        funds = get_funds(a.backfill) or {}
    except Exception as e:
        errs.append(f'예탁금·신용: {e}')
    try:
        pers = get_per(a.backfill) or {}
    except Exception as e:
        errs.append(f'PER: {e}')
    print(f'받음: 예탁금·신용 {len(funds)}일 / PER {len(pers)}일')

    # history 행: [YYYY-MM-DD, 예탁금(억), 신용(억), 미수금(억), PER, PBR, 배당수익률]
    H = {k: list(v) for k, v in old.items()}
    for d8 in set(funds) | set(pers):
        k = f'{d8[:4]}-{d8[4:6]}-{d8[6:]}'
        row = H.get(k, [k, None, None, None, None, None, None])
        f, p = funds.get(d8), pers.get(d8)
        if f: row[1], row[2], row[3] = f['dep'], f['credit'], f['unpaid']
        if p: row[4], row[5], row[6] = p['per'], p['pbr'], p['dy']
        H[k] = row
    hist = [H[k] for k in sorted(H)]
    if old and len(hist) < len(old) * 0.8:
        print(f'❌ 저장 안 함: {len(hist)}행 < 기존 {len(old)}행의 80%'); sys.exit(1)
    if not funds and not pers:
        print('❌ 받은 값 없음: ' + ' / '.join(errs)); sys.exit(1)

    cut = (date.today() - timedelta(days=365 * YEARS_PCT)).isoformat()
    win = [r for r in hist if r[0] >= cut]
    last_f = next((r for r in reversed(hist) if r[1] and r[2]), None)
    last_p = next((r for r in reversed(hist) if r[4]), None)
    lev = lambda r: round(r[2] / r[1] * 100, 2)
    latest = {}
    if last_f:
        latest.update({'funds_date': last_f[0], 'dep': last_f[1], 'credit': last_f[2], 'unpaid': last_f[3], 'lev': lev(last_f),
                       'lev_pct': pct_rank([lev(r) for r in win if r[1] and r[2]], lev(last_f))})
        prev20 = [r for r in hist if r[1] and r[2] and r[0] < last_f[0]][-20:]
        if prev20:
            latest['dep_20d'] = round((last_f[1] / prev20[0][1] - 1) * 100, 1)
            latest['credit_20d'] = round((last_f[2] / prev20[0][2] - 1) * 100, 1)
    if last_p:
        latest.update({'per_date': last_p[0], 'per': last_p[4], 'pbr': last_p[5], 'dy': last_p[6],
                       'per_pct': pct_rank([r[4] for r in win if r[4]], last_p[4]),
                       'pbr_pct': pct_rank([r[5] for r in win if r[5]], last_p[5])})
    out = {'updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
           'source': '예탁금·신용·미수금: 금융투자협회(KIS 증시자금 종합) / PER·PBR: KRX',
           'unit': '억원', 'pct_window_years': YEARS_PCT, 'latest': latest,
           'cols': ['date', 'dep', 'credit', 'unpaid', 'per', 'pbr', 'dy'], 'history': hist}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fo:
        json.dump(out, fo, ensure_ascii=False, separators=(',', ':'))
    print(f'✅ 저장 {len(hist)}행 ({hist[0][0]} ~ {hist[-1][0]})')
    print('   최신:', json.dumps(latest, ensure_ascii=False))
    if errs:
        print('⚠️ 일부 실패: ' + ' / '.join(errs)); sys.exit(1)


if __name__ == '__main__':
    main()
