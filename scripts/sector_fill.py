"""
(106) 종목 리스트 업종 「기타」 채우기 — KIS 현재가(FHKST01010100) bstp_kor_isnm(KRX 업종)
  - kospi200_list.csv / kosdaq_list.csv 에서 업종이 '기타'·빈 칸인 종목만 KIS 업종으로 바꿈
  - 직접 붙여 둔 세부 업종(반도체·조선·지주 …)은 건드리지 않음 (KIS 업종은 더 거침: 지주→금융, 반도체→전기·전자)
  - KIS가 빈 값을 주면 '기타' 그대로
  - update_stock_list.py 끝에서 자동 호출 (새로 들어온 종목) + 수동 실행 가능
  - 토큰은 fetch_live_prices.py 캐시 재사용
  - 받은 결과가 대상의 절반 미만이면 파일을 안 바꿈 (API 장애 때 보호)
사용: python3 scripts/sector_fill.py        (실제 저장)
      python3 scripts/sector_fill.py --dry  (화면에만)
"""
import os, sys, json, time, urllib.request, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_live_prices as L

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FILES = [os.path.join(SCRIPT_DIR, 'kospi200_list.csv'),
         os.path.join(SCRIPT_DIR, 'kosdaq_list.csv')]
EMPTY = ('', '기타')


def kis_sector(token, code):
    url = (f'{L.KIS_BASE}/uapi/domestic-stock/v1/quotations/inquire-price'
           f'?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD={code}')
    req = urllib.request.Request(url, headers={
        'Content-Type': 'application/json; charset=UTF-8',
        'authorization': f'Bearer {token}',
        'appkey': L.KIS_APP_KEY, 'appsecret': L.KIS_APP_SECRET,
        'tr_id': 'FHKST01010100'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode('utf-8'))
    except Exception:
        return None
    if d.get('rt_cd') != '0':
        return None
    return ((d.get('output') or {}).get('bstp_kor_isnm') or '').strip().replace(',', ' ')


def fill(dry=False):
    token = L.get_token()
    if not token:
        print('❌ 업종 채우기: 토큰 없음 — 건너뜀 (70초 뒤 다시 실행)')
        return 0
    total = 0
    for path in FILES:
        if not os.path.exists(path):
            continue
        lines = open(path, encoding='utf-8').read().split('\n')
        targets = []
        for i, line in enumerate(lines):
            if not line.strip() or line.startswith('#'):
                continue
            p = line.split(',')
            if len(p) >= 3 and p[2].strip() in EMPTY:
                targets.append((i, p))
        got, changed, cnt = 0, 0, collections.Counter()
        for i, p in targets:
            sec = kis_sector(token, p[0].strip())
            time.sleep(0.08)
            if sec is None:
                continue
            got += 1
            if sec:
                p[2] = sec
                lines[i] = ','.join(p)
                changed += 1
                cnt[sec] += 1
        name = os.path.basename(path)
        print(f'   {name}: 기타 {len(targets)}종목 → 응답 {got} · 채움 {changed}  {cnt.most_common(8)}')
        if targets and got < len(targets) / 2:
            print(f'   ❌ {name}: 응답이 절반 미만 — 저장 안 함')
            continue
        if changed and not dry:
            tmp = path + '.tmp'
            open(tmp, 'w', encoding='utf-8').write('\n'.join(lines))
            os.replace(tmp, path)
        total += changed
    print(f'✅ 업종 채우기 {"(dry) " if dry else ""}{total}종목')
    return total


if __name__ == '__main__':
    fill(dry='--dry' in sys.argv)
