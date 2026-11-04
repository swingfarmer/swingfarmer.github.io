import os, json, urllib.request, urllib.error

key = os.environ['KIS_APP_KEY']
sec = os.environ['KIS_APP_SECRET']

# 토큰 발급
body = json.dumps({'grant_type':'client_credentials','appkey':key,'appsecret':sec}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    'https://openapi.koreainvestment.com:9443/oauth2/tokenP',
    data=body, headers={'Content-Type':'application/json'}), timeout=10)
tok = json.loads(r.read())['access_token']
print('token OK\n')

# 테스트할 종목코드 목록 (근월물 후보)
codes = [
    '101SC000',   # C=12월
    '101SC260',   # 12월 26년
    '101S2612',   # 2026년 12월
    '101SB000',   # B=11월
    '101SB260',   # 11월 26년
    '101S2611',   # 2026년 11월
]

base_url = ('https://openapi.koreainvestment.com:9443'
            '/uapi/domestic-futureoption/v1/quotations/inquire-price')

for code in codes:
    url = f'{base_url}?FID_COND_MRKT_DIV_CODE=F&FID_INPUT_ISCD={code}'
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
        o1 = d.get('output1', {})
        rt = d.get('rt_cd', '')
        msg = d.get('msg1', '')
        if o1:
            name = o1.get('hts_kor_isnm', '?')
            price = o1.get('futs_prpr', o1.get('stck_prpr', '?'))
            print(f'  {code}: {name} = {price}  ← HIT!')
        else:
            print(f'  {code}: output1 비어있음 (rt={rt}, {msg})')
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f'  {code}: HTTP {e.code} — {body}')
    except Exception as e:
        print(f'  {code}: ERROR {e}')
