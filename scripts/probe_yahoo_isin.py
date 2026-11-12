#!/usr/bin/env python3
"""
야후 검색으로 ISIN → yfinance 티커 변환이 되는지 점검 (083, 1회성 — 결과 보고 나면 삭제)
==========================================================================================
OpenFIGI는 블룸버그 티커를 줌 → 미국·일본·중국A·호주·캐나다는 그대로 쓸 수 있지만
영국·홍콩·대만·인도 등은 본국 티커가 안 나오거나(인도는 블룸버그 전용 티커) 형식이 달라서 주가를 못 받음.
야후 검색(ISIN)이 BARC.L / 2330.TW / 0388.HK / APLAPOLLO.NS 같은 바로 쓸 수 있는 티커를 주는지 확인.
저장 없음. 화면 출력만.

사용: python3 scripts/probe_yahoo_isin.py
"""
import json, time, urllib.request, urllib.parse

SAMPLE = [["INE466L01038", "360 ONE WAM Ltd"], ["INE702C01027", "APL Apollo Tubes Ltd"],
          ["INE949L01017", "AU Small Finance Bank Ltd"], ["IE00B4BNMY34", "Accenture PLC"],
          ["NL0009434992", "LyondellBasell Industries NV"], ["GB0005359004", "RENEW HOLDINGS PLC"],
          ["KYG8068L1086", "SHARKNINJA"], ["KYG6683N1034", "NU Holdings Ltd/Cayman Islands"],
          ["TW0002345006", "ACCTON TECH"], ["TW0003711008", "ASE TECHNOLOGY HOLDING CO LT"],
          ["TW0002330008", "TAIWAN SEMICONDUCTOR MANUFAC"], ["HK0000218211", "HUA HONG SEMI"],
          ["HK0992009065", "Lenovo Group Ltd"], ["GB00B1YW4409", "3I GROUP PLC"],
          ["FR0000120404", "ACCOR SA"], ["SE0014781795", "AddTech AB"],
          ["HK0000069689", "AIA GROUP LTD"], ["KYG017191142", "ALIBABA (HK)"],
          ["CNE1000002H1", "CHINA CONSTRUCTION BANK-H"], ["CH0012005267", "NOVARTIS"]]

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'}


def search(isin):
    url = 'https://query2.finance.yahoo.com/v1/finance/search?' + urllib.parse.urlencode(
        {'q': isin, 'quotesCount': 5, 'newsCount': 0, 'listsCount': 0})
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
        return [(q.get('symbol'), q.get('exchange'), q.get('quoteType')) for q in d.get('quotes', [])], ''
    except Exception as e:
        return None, repr(e)[:120]


try:
    import yfinance as yf
    print('yfinance 버전:', yf.__version__)
except Exception as e:
    yf = None
    print('yfinance 없음:', e)

found, t0 = {}, time.time()
for isin, name in SAMPLE:
    qs, err = search(isin)
    if qs is None:
        print(f'  ❌ {isin} {name[:24]:<24} 실패 {err}')
    else:
        first = qs[0][0] if qs else None
        if first:
            found[isin] = first
        print(f'  {isin} {name[:24]:<24} → {qs[:3]}')
    time.sleep(0.5)
el = time.time() - t0
print(f'검색 {len(SAMPLE)}건 / 티커 나옴 {len(found)} / {el:.1f}초 (건당 {el/len(SAMPLE):.2f}초, 대기 0.5초 포함)')

if yf and found:
    syms = list(found.values())
    t1 = time.time()
    try:
        df = yf.download(syms, period='5d', progress=False, auto_adjust=False, threads=True)['Close']
        last = df.ffill().iloc[-1]
        ok = [s for s in syms if s in last and last[s] == last[s]]
        print(f'yfinance 종가 {len(ok)}/{len(syms)}개 받음 ({time.time()-t1:.1f}초)')
        for s in syms[:20]:
            v = last.get(s) if s in last else None
            print(f'   {s:<14} {v}')
    except Exception as e:
        print('yfinance 다운로드 실패:', repr(e)[:200])
