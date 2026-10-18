#!/usr/bin/env python3
"""업종지수 코드 테스트 — 한투 API"""
import urllib.request, json, os, time

APP_KEY = os.environ.get('KIS_APP_KEY','')
APP_SECRET = os.environ.get('KIS_APP_SECRET','')
BASE = os.environ.get('KIS_BASE_URL','https://openapi.koreainvestment.com:9443')

# 토큰
body = json.dumps({'grant_type':'client_credentials','appkey':APP_KEY,'appsecret':APP_SECRET}).encode()
req = urllib.request.Request(f'{BASE}/oauth2/tokenP', data=body, headers={'Content-Type':'application/json'})
token = json.loads(urllib.request.urlopen(req, timeout=10).read())['access_token']
print('토큰 OK')

headers = {
    'Content-Type': 'application/json; charset=utf-8',
    'authorization': f'Bearer {token}',
    'appkey': APP_KEY,
    'appsecret': APP_SECRET,
    'custtype': 'P',
    'tr_id': 'FHKUP03500100'
}

codes = [
    ('0001','종합'), ('0002','대형주'), ('0003','중형주'), ('0004','소형주'),
    ('0005','음식료품'), ('0006','섬유의복'), ('0007','종이목재'), ('0008','화학'),
    ('0009','의약품'), ('0010','비금속광물'), ('0011','철강금속'), ('0012','기계'),
    ('0013','전기전자'), ('0014','의료정밀'), ('0015','운수장비'), ('0016','유통업'),
    ('0017','전기가스업'), ('0018','건설업'), ('0019','운수창고업'), ('0020','통신업'),
    ('0021','금융업'), ('0022','은행'), ('0024','증권'), ('0025','보험'),
    ('0026','서비스업'), ('0027','제조업'), ('0028','코스피200'),
]

found = []
for code, name in codes:
    params = (
        f'FID_COND_MRKT_DIV_CODE=U&FID_INPUT_ISCD={code}'
        f'&FID_INPUT_DATE_1=20261016&FID_INPUT_DATE_2=20261016'
        f'&FID_PERIOD_DIV_CODE=D'
    )
    url = f'{BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice?{params}'
    try:
        req2 = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req2, timeout=10)
        data = json.loads(resp.read())
        out = data.get('output2', [])
        if out and out[0].get('bstp_nmix_prpr', '') not in ['', '0']:
            val = out[0]['bstp_nmix_prpr']
            print(f'  OK  {code} {name:10s} = {val}')
            found.append((code, name))
        else:
            print(f'  --  {code} {name:10s} = empty')
    except Exception as e:
        print(f'  ERR {code} {name:10s} = {e}')
    time.sleep(0.1)

print(f'\n총 {len(found)}개 업종지수 확인')
for c, n in found:
    print(f"    ('{c}', '{n}'),")
