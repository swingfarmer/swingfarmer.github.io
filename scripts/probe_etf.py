#!/usr/bin/env python3
"""
국내 ETF 데이터 소스 점검 (082, 1회성 — 결과 보고 나면 삭제)
  1) 네이버 ETF 전체 목록 API
  2) pykrx ETF 함수 (목록·시세·기간등락률·구성종목)
레포에 아무것도 저장하지 않음. 화면 출력만.
사용: python3 scripts/probe_etf.py
"""
import json, urllib.request, traceback
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

def line(t): print('-' * 10, t)

# ---------- 1. 네이버 ----------
line('1. 네이버 etfItemList')
try:
    url = 'https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0&targetColumn=market_sum&sortOrder=desc'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/sise/etf.naver'})
    raw = urllib.request.urlopen(req, timeout=15).read()
    txt = None
    for enc in ('utf-8', 'cp949'):
        try:
            txt = raw.decode(enc); print('인코딩:', enc); break
        except Exception:
            pass
    d = json.loads(txt)
    items = d.get('result', {}).get('etfItemList', [])
    print('개수:', len(items))
    if items:
        print('키:', ','.join(items[0].keys()))
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False))
        tabs = {}
        for it in items:
            tabs[it.get('etfTabCode')] = tabs.get(it.get('etfTabCode'), 0) + 1
        print('분류코드별 개수:', dict(sorted(tabs.items(), key=lambda x: str(x[0]))))
        for code in sorted(tabs, key=str):
            ex = [it.get('itemname') for it in items if it.get('etfTabCode') == code][:4]
            print(' ', code, '예:', ' / '.join(ex))
except Exception as e:
    print('실패:', repr(e)[:300])

# ---------- 2. pykrx ----------
line('2. pykrx')
try:
    from pykrx import stock
    import pykrx
    print('pykrx 버전:', getattr(pykrx, '__version__', '?'))
except Exception as e:
    print('pykrx import 실패:', repr(e)[:200]); stock = None

if stock:
    day = None
    tickers = []
    now = datetime.now(KST)
    for i in range(1, 10):   # 어제부터 거꾸로 영업일 찾기
        ds = (now - timedelta(days=i)).strftime('%Y%m%d')
        try:
            tickers = stock.get_etf_ticker_list(ds)
            if tickers:
                day = ds; break
        except Exception as e:
            print(ds, '목록 실패:', repr(e)[:200])
    print('기준일:', day, '/ ETF 목록 개수:', len(tickers))

    def tryit(name, fn):
        line(name)
        try:
            df = fn()
            print('행:', len(df), '/ 열:', ','.join(map(str, df.columns)))
            print(df.head(3).to_string()[:600])
        except Exception as e:
            print('실패:', repr(e)[:300])

    if day:
        tryit('2-1 get_etf_ohlcv_by_ticker (하루 전종목 시세)',
              lambda: stock.get_etf_ohlcv_by_ticker(day))
        start = (datetime.strptime(day, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d')
        tryit('2-2 get_etf_price_change_by_ticker (30일 등락률)',
              lambda: stock.get_etf_price_change_by_ticker(start, day))
        tryit('2-3 get_etf_portfolio_deposit_file 069500 (구성종목)',
              lambda: stock.get_etf_portfolio_deposit_file('069500', day))
        try:
            print('이름 확인 069500:', stock.get_etf_ticker_name('069500'))
        except Exception as e:
            print('이름 실패:', repr(e)[:200])

line('끝')
