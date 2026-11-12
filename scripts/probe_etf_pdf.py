#!/usr/bin/env python3
"""
KRX ETF 구성종목(PDF) 원본 점검 (083, 1회성 — 결과 보고 나면 삭제)
=================================================================
해외 종목 비중을 직접 계산할 수 있는지 판단용.
  - pykrx는 해외 종목 코드를 6자리로 줌 (예: 애플 378331 = ISIN US0378331005 의 일부)
  - KRX 원본 응답에 전체 ISIN(12자리)·계약수가 있는지 확인
    → ISIN이 있으면 OpenFIGI로 티커 변환 → yfinance 주가 × 계약수 × 환율로 비중 계산 가능
레포에 아무것도 저장하지 않음. 화면 출력만.

사용: python3 scripts/probe_etf_pdf.py
"""
import json, sys
import requests

ETFS = [('0015K0', '미국 테마형 30개'), ('360750', 'TIGER 미국S&P500'), ('0002C0', '인도 테마형')]

captured = []
_orig = requests.sessions.Session.request


def spy(self, method, url, *a, **kw):
    r = _orig(self, method, url, *a, **kw)
    if 'krx' in url:
        captured.append((url, kw.get('data') or kw.get('params'), r.text))
    return r


requests.sessions.Session.request = spy

from pykrx import stock
from datetime import datetime, timedelta

day = stock.get_nearest_business_day_in_a_week((datetime.now() - timedelta(days=1)).strftime('%Y%m%d'))
print('기준일', day)

for code, label in ETFS:
    print('=' * 20, code, label)
    captured.clear()
    try:
        df = stock.get_etf_portfolio_deposit_file(code, day)
        print('pykrx 칸:', list(df.columns), '/ 행', len(df))
        print(df.head(3).to_string()[:600])
    except Exception as e:
        print('pykrx 실패:', repr(e)[:200])
    for url, data, text in captured[-2:]:
        print('-- KRX 요청:', url.split('?')[0], '| bld =', (data or {}).get('bld') if isinstance(data, dict) else '?')
        try:
            j = json.loads(text)
            rows = None
            for k, v in j.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    rows = v
                    print('   목록 키:', k, '/ 행', len(v))
                    break
            if rows:
                print('   칸 이름:', list(rows[0].keys()))
                for r in rows[:3]:
                    print('  ', json.dumps(r, ensure_ascii=False)[:300])
        except Exception:
            print('   (JSON 아님)', text[:200])
