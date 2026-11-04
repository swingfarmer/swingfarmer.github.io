import os, json, urllib.request, urllib.error

key = os.environ['KIS_APP_KEY']
sec = os.environ['KIS_APP_SECRET']

# 1. 토큰 발급
body = json.dumps({'grant_type':'client_credentials','appkey':key,'appsecret':sec}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    'https://openapi.koreainvestment.com:9443/oauth2/tokenP',
    data=body, headers={'Content-Type':'application/json'}), timeout=10)
tok = json.loads(r.read())['access_token']
print('token OK')

# 2. 코스피200 선물 현재가 조회
url = ('https://openapi.koreainvestment.com:9443'
       '/uapi/domestic-futureoption/v1/quotations/inquire-price'
       '?FID_COND_MRKT_DIV_CODE=F&FID_INPUT_ISCD=101S6000')
h = {
    'Content-Type': 'application/json; charset=utf-8',
    'authorization': 'Bearer ' + tok,
    'appkey': key,
    'appsecret': sec,
    'tr_id': 'FHMIF10000000',
    'custtype': 'P',
}
try:
    r2 = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=10)
    d = json.loads(r2.read())
    print(json.dumps(d, indent=2, ensure_ascii=False)[:3000])
except urllib.error.HTTPError as e:
    print(f'HTTP {e.code}')
    print(e.read().decode()[:1000])
