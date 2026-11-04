"""코스피200 선물 야간 데이터 소스 탐색 v3"""
import json, urllib.request, re

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def try_url(label, url, headers=None):
    h = {**UA, **(headers or {})}
    try:
        req = urllib.request.Request(url, headers=h)
        r = urllib.request.urlopen(req, timeout=10)
        data = r.read().decode('utf-8', errors='replace')
        print(f"  {label}: OK ({len(data)} bytes)")
        print(f"  {data[:600]}\n")
        return data
    except Exception as e:
        print(f"  {label}: {e}\n")
        return None

print("=== 1. 네이버 선물 시세 페이지 스크래핑 ===")
html = try_url('futures_sise', 'https://finance.naver.com/sise/futures_sise.naver')
if html:
    # 야간선물 가격 패턴 추출 시도
    m = re.findall(r'(?:야간|야선|night|KOSPI\s*200)[^<]{0,200}', html, re.I)
    if m:
        for match in m[:3]:
            print(f"  패턴: {match[:150]}")

print("=== 2. 네이버 fchart API ===")
try_url('fchart', 'https://fchart.stock.naver.com/siseJson.nhn?symbol=KPI200&requestType=1&startTime=20261103&endTime=20261104&timeframe=day')

print("=== 3. 네이버 API v2 ===")
try_url('naver_v2_fut', 'https://api.stock.naver.com/future/domestic/market/KOSPI200/index')
try_url('naver_v2_night', 'https://api.stock.naver.com/future/domestic/nightSession')
try_url('naver_world', 'https://api.stock.naver.com/index/worldIndexList')

print("=== 4. Daum 금융 API ===")
try_url('daum_fut', 'https://finance.daum.net/api/futures/KOSPI200',
        {'referer': 'https://finance.daum.net'})
try_url('daum_night', 'https://finance.daum.net/api/futures/nights',
        {'referer': 'https://finance.daum.net'})

print("=== 5. Investing.com ===")
try_url('investing', 'https://api.investing.com/api/financialdata/8839/historical/chart/?interval=P1D&pointscount=2',
        {'domain-id': 'www'})
