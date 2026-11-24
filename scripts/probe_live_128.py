#!/usr/bin/env python3
"""(128) 임시 — 1분 실시간으로 바꿀 칸들의 데이터 소스가 실제로 되는지 한 번 찔러 보는 스크립트. 확인 끝나면 지움.
KIS 토큰은 fetch_live_prices.py의 캐시를 그대로 씀(새로 발급 안 함).
  python3 scripts/probe_live_128.py
"""
import os, sys, json, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_live_prices as F

tok = F.get_token()
if not tok:
    print('❌ 토큰 없음'); sys.exit(1)


def show(label, path, tr, params):
    try:
        d = F.kis_get(path, tr, params, tok)
    except Exception as e:
        print(f'■ {label}: 예외 {e}'); return
    rc = d.get('rt_cd'); msg = (d.get('msg1') or '').strip()
    print(f'■ {label}: rt_cd={rc} {d.get("msg_cd","")} {msg}')
    for k in ('output', 'output1', 'output2'):
        o = d.get(k)
        if o is None:
            continue
        if isinstance(o, list):
            print(f'   {k}: list {len(o)}줄')
            for row in o[:2]:
                print('     ', json.dumps(row, ensure_ascii=False)[:700])
        else:
            print(f'   {k}:', json.dumps(o, ensure_ascii=False)[:700])
    time.sleep(0.2)


Q = '/uapi/domestic-stock/v1/quotations'
# 1. 업종 전체 지수 (업종 등락)
show('업종전체 코스피', f'{Q}/inquire-index-category-price', 'FHPUP02140000',
     {'FID_COND_MRKT_DIV_CODE': 'U', 'FID_INPUT_ISCD': '0001', 'FID_COND_SCR_DIV_CODE': '20214',
      'FID_MRKT_CLS_CODE': 'K', 'FID_BLNG_CLS_CODE': '0'})
# 2. 시장별 투자자 매매동향(시세) — 외국인·기관 순매수 금액
for a, b in (('0001', 'S001'), ('999', 'S001'), ('0001', '')):
    show(f'시장 투자자 {a}/{b}', f'{Q}/inquire-investor-time-by-market', 'FHPTJ04030000',
         {'FID_INPUT_ISCD': a, 'FID_INPUT_ISCD_2': b})
# 3. 프로그램매매 종합(시간)
show('프로그램 코스피', f'{Q}/comp-program-trade-today', 'FHPPG04600101',
     {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_MRKT_CLS_CODE': 'K', 'FID_SCTN_CLS_CODE': '',
      'FID_INPUT_ISCD': '', 'FID_COND_MRKT_DIV_CODE1': '', 'FID_INPUT_HOUR_1': ''})
# 4. 외국인·기관 순매수 종목 (장중 가집계)
for etc, nm in (('1', '외국인'), ('2', '기관')):
    show(f'가집계 {nm} 순매수', f'{Q}/foreign-institution-total', 'FHPTJ04400000',
         {'FID_COND_MRKT_DIV_CODE': 'V', 'FID_COND_SCR_DIV_CODE': '16449', 'FID_INPUT_ISCD': '0000',
          'FID_DIV_CLS_CODE': '1', 'FID_RANK_SORT_CLS_CODE': '0', 'FID_ETC_CLS_CODE': etc})
# 5. 거래대금 순위
show('거래대금 순위', f'{Q}/volume-rank', 'FHPST01710000',
     {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_COND_SCR_DIV_CODE': '20171', 'FID_INPUT_ISCD': '0000',
      'FID_DIV_CLS_CODE': '0', 'FID_BLNG_CLS_CODE': '3', 'FID_TRGT_CLS_CODE': '111111111',
      'FID_TRGT_EXLS_CLS_CODE': '0000000000', 'FID_INPUT_PRICE_1': '', 'FID_INPUT_PRICE_2': '',
      'FID_VOL_CNT': '', 'FID_INPUT_DATE_1': ''})
# 6. 신고가 근접
show('신고가 근접', '/uapi/domestic-stock/v1/ranking/near-new-highlow', 'FHPST01870000',
     {'FID_APLY_RANG_VOL': '0', 'FID_COND_MRKT_DIV_CODE': 'J', 'FID_COND_SCR_DIV_CODE': '20187',
      'FID_DIV_CLS_CODE': '0', 'FID_INPUT_CNT_1': '0', 'FID_INPUT_CNT_2': '0', 'FID_PRC_CLS_CODE': '0',
      'FID_INPUT_ISCD': '0000', 'FID_TRGT_CLS_CODE': '0', 'FID_TRGT_EXLS_CLS_CODE': '0',
      'FID_APLY_RANG_PRC_1': '', 'FID_APLY_RANG_PRC_2': ''})

# 7. 야후 — 해외 지수·환율·금리·유가 한 번에 (spark: 호출 1번에 여러 종목)
SY = '^GSPC,^IXIC,^VIX,^TNX,CL=F,KRW=X,JPYKRW=X,GC=F'
for host in ('query1', 'query2'):
    url = f'https://{host}.finance.yahoo.com/v7/finance/spark?symbols={SY}&range=1d&interval=5m'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
        res = (d.get('spark') or {}).get('result') or []
        print(f'■ 야후 spark {host}: {len(res)}종목')
        for x in res:
            m = ((x.get('response') or [{}])[0].get('meta') or {})
            print(f"   {x.get('symbol')}: {m.get('regularMarketPrice')} 전일 {m.get('chartPreviousClose')} / {m.get('previousClose')} 시각 {m.get('regularMarketTime')}")
        break
    except Exception as e:
        print(f'■ 야후 spark {host}: 실패 {str(e)[:120]}')
