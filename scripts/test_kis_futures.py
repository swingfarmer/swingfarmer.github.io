"""KIS API 야간선물 — 마켓코드/종목코드 조합 테스트 v5"""
import os, json, urllib.request, urllib.error

key = os.environ['KIS_APP_KEY']
sec = os.environ['KIS_APP_SECRET']

body = json.dumps({'grant_type':'client_credentials','appkey':key,'appsecret':sec}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    'https://openapi.koreainvestment.com:9443/oauth2/tokenP',
    data=body, headers={'Content-Type':'application/json'}), timeout=10)
tok = json.loads(r.read())['access_token']
print('token OK\n')

base = 'https://openapi.koreainvestment.com:9443/uapi/domestic-futureoption/v1/quotations'
codes = ['101S6000', '101SC000', '101SC626', '101SC260']
mkts = ['F', 'N', 'NF', 'JF']
tr_ids = ['FHMIF10000000', 'FHMIF10010000']

for tr in tr_ids:
    for mkt in mkts:
        for code in codes:
            url = f'{base}/inquire-price?FID_COND_MRKT_DIV_CODE={mkt}&FID_INPUT_ISCD={code}'
            h = {'Content-Type':'application/json; charset=utf-8',
                 'authorization':'Bearer '+tok,'appkey':key,'appsecret':sec,
                 'tr_id':tr,'custtype':'P'}
            try:
                r2 = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=8)
                d = json.loads(r2.read())
                o1 = d.get('output1', {})
                rt = d.get('rt_cd', '')
                msg = d.get('msg1', '')[:60]
                if o1:
                    print(f'  HIT! tr={tr} mkt={mkt} code={code}')
                    print(f'        {json.dumps(o1, ensure_ascii=False)[:400]}')
                elif rt != '0':
                    pass  # 에러는 무시
            except:
                pass

print('\n=== 종목 리스트 조회 시도 ===')
# 종목 마스터 조회 (어떤 선물 종목이 있는지)
list_urls = [
    f'{base}/inquire-asking-price?FID_COND_MRKT_DIV_CODE=F&FID_INPUT_ISCD=101S6000',
]
for url in list_urls:
    h = {'Content-Type':'application/json; charset=utf-8',
         'authorization':'Bearer '+tok,'appkey':key,'appsecret':sec,
         'tr_id':'FHMIF10010000','custtype':'P'}
    try:
        r3 = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=8)
        d3 = json.loads(r3.read())
        print(f'  호가: {json.dumps(d3, ensure_ascii=False)[:600]}')
    except urllib.error.HTTPError as e:
        print(f'  호가: HTTP {e.code} — {e.read().decode()[:200]}')
    except Exception as e:
        print(f'  호가: {e}')
