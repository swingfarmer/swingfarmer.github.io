#!/usr/bin/env python3
"""
국내 ETF 전종목 수집 (082) — VM 크론 전용, 평일 1회
=====================================================
소스
  1) 네이버 ETF 목록 API (1회 호출, 전종목)
     이름 · 분류코드(etfTabCode) · 현재가 · 등락률 · NAV · 3개월수익률 · 거래량
     amonut = 거래대금(백만원), marketSum = 시가총액(억원) ← 순자산 대용
  2) pykrx (KRX)
     get_etf_ohlcv_by_ticker(날짜)            종가·NAV·거래대금(원)
     get_etf_price_change_by_ticker(시작, 끝)  1주/1개월/3개월/6개월/연초/1년 등락률
       ※ 가격 등락률만. 분배금은 빠져 있음 (커버드콜·배당 ETF는 실제 수익보다 낮게 나옴)

자금 유입 추정 (설정·환매)
  flow = 오늘 시총 − 어제 시총 × (오늘 종가 / 어제 종가)   (억원)
  → 가격 변화로 늘어난 몫을 빼고 남은 것 = 좌수 증감 × 가격
  data/kr/etf/flow_hist.json 에 최근 20거래일 보관. 첫 실행 다음 날부터 쌓임.

출력
  data/kr/etf/latest.json     전종목 스냅샷 (페이지가 읽음)
  data/kr/etf/flow_hist.json  종목별 자금유입 20일 + 어제 값(다음 계산용)

사용법
  python3 scripts/fetch_kr_etf.py                # 최근 영업일
  python3 scripts/fetch_kr_etf.py --date 20261111

크론 (평일 18:40, fetch_prices.py 18:30 줄 아래)
40 18 * * 1-5 . ~/.env_secrets && cd ~/swingfarmer.github.io && python3 scripts/fetch_kr_etf.py >> ~/logs/fetch_kr_etf.log 2>&1
"""
import os, sys, json, time, urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'data', 'kr', 'etf')
os.makedirs(OUT_DIR, exist_ok=True)
LATEST = os.path.join(OUT_DIR, 'latest.json')
FLOW = os.path.join(OUT_DIR, 'flow_hist.json')
FLOW_DAYS = 20

NAVER_URL = 'https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0&targetColumn=market_sum&sortOrder=desc'
TAB_NAME = {1: '국내 시장지수', 2: '국내 업종·테마', 3: '국내 레버리지·인버스',
            4: '해외 주식', 5: '원자재', 6: '채권', 7: '기타'}


def log(*a):
    print(datetime.now(KST).strftime('%H:%M:%S'), *a, flush=True)


def num(v):
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:   # NaN
            return None
        return f
    except Exception:
        return None


def r2(v):
    v = num(v)
    return None if v is None else round(v, 2)


def fetch_naver():
    req = urllib.request.Request(NAVER_URL, headers={
        'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/sise/etf.naver'})
    raw = urllib.request.urlopen(req, timeout=20).read()
    for enc in ('utf-8', 'cp949'):
        try:
            txt = raw.decode(enc)
            break
        except Exception:
            txt = None
    items = json.loads(txt)['result']['etfItemList']
    return {it['itemcode']: it for it in items}


def nearest_bday(stock, ymd):
    """ymd(YYYYMMDD) 이전(포함) 가장 가까운 영업일. 실패하면 그대로."""
    try:
        return stock.get_nearest_business_day_in_a_day(ymd, prev=True)
    except Exception:
        return ymd


def main():
    date_arg = None
    if '--date' in sys.argv:
        date_arg = sys.argv[sys.argv.index('--date') + 1]

    log('네이버 ETF 목록...')
    naver = fetch_naver()
    log(f'  네이버 {len(naver)}개')

    from pykrx import stock

    # 기준일: 지정일 또는 오늘부터 거꾸로 데이터 있는 날
    day, ohlcv = None, None
    base = datetime.strptime(date_arg, '%Y%m%d') if date_arg else datetime.now(KST)
    for i in range(0, 10):
        ds = (base - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = stock.get_etf_ohlcv_by_ticker(ds)
            if df is not None and len(df) and df['거래량'].sum() > 0:
                day, ohlcv = ds, df
                break
        except Exception as e:
            log(f'  {ds} 시세 실패: {repr(e)[:120]}')
        if date_arg:
            break
    if day is None:
        log('❌ KRX 시세 없음 — 종료 (기존 파일 유지)')
        sys.exit(1)
    log(f'기준일 {day} / KRX 시세 {len(ohlcv)}개')

    # 기간 등락률
    d0 = datetime.strptime(day, '%Y%m%d')
    periods = {
        'w1': d0 - timedelta(days=7),
        'm1': d0 - timedelta(days=30),
        'm3': d0 - timedelta(days=91),
        'm6': d0 - timedelta(days=182),
        'ytd': datetime(d0.year - 1, 12, 31),
        'y1': d0 - timedelta(days=365),
    }
    chg = {}
    for key, sd in periods.items():
        start = nearest_bday(stock, sd.strftime('%Y%m%d'))
        try:
            df = stock.get_etf_price_change_by_ticker(start, day)
            chg[key] = {t: r2(row['등락률']) for t, row in df.iterrows()}
            log(f'  {key} ({start}~{day}) {len(chg[key])}개')
        except Exception as e:
            chg[key] = {}
            log(f'  {key} 실패: {repr(e)[:120]}')
        time.sleep(1)

    # 단위 확인 출력 (네이버 amonut 백만원 가정 검증)
    try:
        k = '069500'
        krx_val = num(ohlcv.loc[k, '거래대금'])
        nv = num(naver.get(k, {}).get('amonut'))
        if krx_val and nv:
            log(f'  단위 확인 069500: KRX 거래대금 {krx_val/1e8:,.0f}억원 / 네이버 amonut {nv/100:,.0f}억원(백만원÷100)')
    except Exception:
        pass

    # 자금유입: 어제 값 불러오기
    flow = {'dates': [], 'prev': {}, 'f': {}}
    if os.path.exists(FLOW):
        try:
            flow = json.load(open(FLOW, encoding='utf-8'))
        except Exception:
            pass
    prev_day = flow.get('prev_date')
    same_day = (prev_day == day)   # 같은 날 재실행이면 유입 다시 계산 안 함

    codes = sorted(set(naver) | set(ohlcv.index))
    rows, new_prev = [], {}
    for c in codes:
        nv = naver.get(c, {})
        try:
            kr = ohlcv.loc[c]
        except Exception:
            kr = None
        name = nv.get('itemname')
        if not name:
            try:
                name = stock.get_etf_ticker_name(c)
            except Exception:
                name = c
        close = num(kr['종가']) if kr is not None else num(nv.get('nowVal'))
        navv = num(kr['NAV']) if kr is not None else num(nv.get('nav'))
        val_eok = (num(kr['거래대금']) / 1e8) if kr is not None and num(kr['거래대금']) is not None \
            else ((num(nv.get('amonut')) or 0) / 100)
        close = round(close, 2) if close is not None else None
        aum = num(nv.get('marketSum'))          # 억원
        r1 = r2(nv.get('changeRate'))
        gap = r2((close / navv - 1) * 100) if close and navv else None

        # 자금유입 (억원)
        fl = None
        pv = flow.get('prev', {}).get(c)
        if not same_day and pv and aum is not None and close and pv[0] and pv[1]:
            fl = round(aum - pv[1] * (close / pv[0]), 1)
        if close and aum is not None:
            new_prev[c] = [close, aum]

        rows.append([c, name, nv.get('etfTabCode'), close, r1,
                     chg['w1'].get(c), chg['m1'].get(c), chg['m3'].get(c),
                     chg['m6'].get(c), chg['ytd'].get(c), chg['y1'].get(c),
                     round(val_eok, 1) if val_eok is not None else None,
                     aum, gap, int(num(nv.get('quant')) or 0)])
        if not same_day:
            arr = flow.get('f', {}).get(c, [])
            arr = (arr + [fl])[-FLOW_DAYS:]
            flow.setdefault('f', {})[c] = arr

    if not same_day:
        flow['dates'] = (flow.get('dates', []) + [day])[-FLOW_DAYS:]
        flow['prev'] = new_prev
        flow['prev_date'] = day
        # 상장폐지 등으로 사라진 종목 정리, 길이 맞추기
        n = len(flow['dates'])
        flow['f'] = {c: ([None] * n + v)[-n:] for c, v in flow['f'].items() if c in new_prev}
    else:
        log('  같은 날 재실행 — 자금유입은 그대로 둠')

    out = {
        'date': f'{day[:4]}-{day[4:6]}-{day[6:]}',
        'updated': datetime.now(KST).strftime('%Y-%m-%d %H:%M'),
        'count': len(rows),
        'tabs': TAB_NAME,
        'cols': ['code', 'name', 'tab', 'close', 'd1', 'w1', 'm1', 'm3', 'm6', 'ytd', 'y1',
                 'value_eok', 'aum_eok', 'gap', 'volume'],
        'units': {'value_eok': '억원', 'aum_eok': '억원(시가총액)', 'gap': '% (종가/NAV-1)',
                  'd1~y1': '% 가격 등락률(분배금 제외)'},
        'rows': rows,
    }
    with open(LATEST, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    with open(FLOW, 'w', encoding='utf-8') as f:
        json.dump(flow, f, ensure_ascii=False, separators=(',', ':'))
    log(f'✅ latest.json {len(rows)}개 ({os.path.getsize(LATEST)//1024}KB) / '
        f'flow_hist {len(flow["dates"])}일 ({os.path.getsize(FLOW)//1024}KB)')


if __name__ == '__main__':
    main()
