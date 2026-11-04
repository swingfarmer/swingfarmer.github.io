"""코스피200 선물(야간 포함) 데이터 소스 테스트"""
import json, urllib.request, urllib.error, os

UA = {'User-Agent': 'Mozilla/5.0'}

# ── 1. 네이버 모바일 API ──
print("=== 1. 네이버 모바일 API ===")
naver_urls = [
    ('시세 basic', 'https://m.stock.naver.com/api/index/KOSPI200FUT/basic'),
    ('시세 FUT근월', 'https://m.stock.naver.com/api/index/KPI200FUT_NM/basic'),
    ('polling', 'https://polling.finance.naver.com/api/realtime/domestic/futureOption/101SC000'),
    ('polling2', 'https://polling.finance.naver.com/api/realtime/domestic/stock/101SC000'),
]
for label, url in naver_urls:
    try:
        req = urllib.request.Request(url, headers=UA)
        r = urllib.request.urlopen(req, timeout=8)
        d = r.read().decode()[:800]
        print(f"  {label}: OK\n  {d}\n")
    except urllib.error.HTTPError as e:
        print(f"  {label}: HTTP {e.code}\n")
    except Exception as e:
        print(f"  {label}: {e}\n")

# ── 2. KRX API ──
print("=== 2. KRX open API ===")
try:
    url2 = 'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
    body2 = 'bld=dbms/MDC/STAT/standard/MDCSTAT12501&locale=ko_KR&prodId=KRDRVFUK2I&trdDd=20261104&share=1&money=1&csvxls_is498No=false'
    req2 = urllib.request.Request(url2, data=body2.encode(),
        headers={**UA, 'Content-Type':'application/x-www-form-urlencoded'})
    r2 = urllib.request.urlopen(req2, timeout=10)
    d2 = json.loads(r2.read())
    items = d2.get('output', d2.get('OutBlock_1', []))
    if isinstance(items, list):
        for it in items[:3]:
            print(f"  {json.dumps(it, ensure_ascii=False)[:300]}")
    else:
        print(f"  {json.dumps(d2, ensure_ascii=False)[:800]}")
    print()
except Exception as e:
    print(f"  KRX: {e}\n")

# ── 3. 한투 API — output 전체 덤프 (101S6000) ──
print("=== 3. 한투 API full dump ===")
try:
    k = os.environ.get('KIS_APP_KEY','')
    s = os.environ.get('KIS_APP_SECRET','')
    if k and s:
        body3 = json.dumps({'grant_type':'client_credentials','appkey':k,'appsecret':s}).encode()
        r3 = urllib.request.urlopen(urllib.request.Request(
            'https://openapi.koreainvestment.com:9443/oauth2/tokenP',
            data=body3, headers={'Content-Type':'application/json'}), timeout=10)
        tok = json.loads(r3.read())['access_token']
        # 종목 리스트 조회 시도
        for code in ['101S6000', '101SC626', '10106260']:
            url4 = (f'https://openapi.koreainvestment.com:9443'
                    f'/uapi/domestic-futureoption/v1/quotations/inquire-price'
                    f'?FID_COND_MRKT_DIV_CODE=F&FID_INPUT_ISCD={code}')
            h4 = {'Content-Type':'application/json; charset=utf-8',
                   'authorization':'Bearer '+tok,'appkey':k,'appsecret':s,
                   'tr_id':'FHMIF10000000','custtype':'P'}
            r4 = urllib.request.urlopen(urllib.request.Request(url4, headers=h4), timeout=10)
            d4 = json.loads(r4.read())
            o1 = d4.get('output1', {})
            if o1:
                print(f"  {code} output1: {json.dumps(o1, ensure_ascii=False)[:500]}")
            else:
                # output 키 전부 나열
                keys = [k for k in d4.keys()]
                print(f"  {code}: output1 empty, keys={keys}")
    else:
        print("  KIS 키 없음")
except Exception as e:
    print(f"  한투: {e}")
