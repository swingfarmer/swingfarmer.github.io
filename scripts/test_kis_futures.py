"""야간선물 데이터 소스 탐색 v4 — longnshort.kr + 네이버 야간"""
import json, urllib.request, re

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

def try_url(label, url, headers=None, show=800):
    h = {**UA, **(headers or {})}
    try:
        req = urllib.request.Request(url, headers=h)
        r = urllib.request.urlopen(req, timeout=10)
        data = r.read().decode('utf-8', errors='replace')
        print(f"  {label}: OK ({len(data)} bytes)")
        print(f"  {data[:show]}\n")
        return data
    except Exception as e:
        print(f"  {label}: {e}\n")
        return None

# ── 1. longnshort.kr ──
print("=== 1. longnshort.kr 메인 ===")
html = try_url('main', 'https://longnshort.kr/', show=1500)
if html:
    nums = re.findall(r'(?:야간|night|선물|futures|kospi\s*200)[^<]{0,300}', html, re.I | re.S)
    if nums:
        print("  패턴 발견:")
        for n in nums[:5]:
            print(f"    {n.strip()[:200]}")
    print()

print("=== 2. longnshort.kr API 탐색 ===")
try_url('api1', 'https://longnshort.kr/api/night-futures')
try_url('api2', 'https://longnshort.kr/api/market')
try_url('api3', 'https://longnshort.kr/api/futures')
try_url('api4', 'https://longnshort.kr/api/kospi200')

# ── 3. 네이버 야간선물 전용 ──
print("=== 3. 네이버 야간선물 ===")
try_url('night1', 'https://m.stock.naver.com/api/index/KOSPI200NIGHTFUT/basic')
try_url('night2', 'https://polling.finance.naver.com/api/realtime/domestic/index/NIGHTFUT')
try_url('night3', 'https://finance.naver.com/sise/sise_index_day.naver?code=KPI200N')

# ── 4. 한국거래소 야간선물 ──  
print("=== 4. KRX 야간 ===")
try_url('krx_night', 'http://global.krx.co.kr/contents/GLB/05/0509/0509010000/GLB0509010000.jsp')
