#!/usr/bin/env python3
"""
국내 ETF 해외 구성종목 ISIN → 거래소 티커 변환 (083) — VM 전용
===============================================================
입력: ~/sf_data/etf_pdf_foreign.json   (fetch_kr_etf_holdings.py 가 주 1회 저장)
출력: data/kr/etf/isin_map.json        (레포, 캐시 — 한 번 바꾼 ISIN은 다시 안 물어봄)
  {updated, n, m: {ISIN: [이름, [[거래소코드, 티커], ...]] 또는 [이름, null, 'YYYY-MM-DD'(못 찾은 날)]}}
  - 후보는 OpenFIGI composite(국가 대표) 상장만. yfinance 티커로 바꾸는 건 비중 계산 단계에서 함
    (거래소→접미사 규칙을 고쳐도 다시 조회할 필요 없게)
  - 못 찾은 ISIN은 30일 뒤에 다시 시도

OpenFIGI (Bloomberg 무료 공개 API) https://api.openfigi.com/v3/mapping
  키 없음: 분당 25회, 1회 10건 (413이 오면 5건으로 줄임)
  키 있음(OPENFIGI_API_KEY): 6초당 25회, 1회 100건 — 무료 가입으로 받음, 없어도 동작
  ISIN 검사숫자가 틀린 코드(스왑·선물 등 KRX 내부 코드)는 조회 안 함

사용법
  python3 scripts/fetch_isin_map.py --limit 30   # 테스트: 새 ISIN 30개만 조회, 저장 안 함, 결과·속도 출력
  python3 scripts/fetch_isin_map.py              # 새 ISIN 전부 조회 후 저장
"""
import os, sys, json, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.expanduser('~/sf_data/etf_pdf_foreign.json')
OUT = os.path.join(ROOT, 'data', 'kr', 'etf', 'isin_map.json')
URL = 'https://api.openfigi.com/v3/mapping'
KEY = os.environ.get('OPENFIGI_API_KEY', '').strip()
JOBS = 100 if KEY else 10
SLEEP = 0.3 if KEY else 2.5          # 키 없음 분당 25회 → 2.4초 간격
RETRY_DAYS = 30


def log(*a):
    print(datetime.now(KST).strftime('%H:%M:%S'), *a, flush=True)


def isin_ok(s):
    """ISIN 형식 + 검사숫자(Luhn) 확인."""
    if len(s) != 12 or not s[:2].isalpha() or not s[:2].isupper() or not s[-1].isdigit() or not s.isalnum():
        return False
    digits = ''.join(str(int(c, 36)) for c in s[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(s[-1])


def post(jobs):
    """→ (응답 리스트, 상태코드)"""
    req = urllib.request.Request(URL, data=json.dumps(jobs).encode(), method='POST',
                                 headers={'Content-Type': 'application/json',
                                          **({'X-OPENFIGI-APIKEY': KEY} if KEY else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()), 200
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:
        return None, 0


def pick(data):
    """한 ISIN의 응답 → composite 상장 후보 [[거래소, 티커], ...] (중복 제거, 최대 4개)."""
    out = []
    for d in data or []:
        if d.get('marketSector') != 'Equity':
            continue
        if d.get('figi') and d.get('figi') != d.get('compositeFIGI'):
            continue                      # 개별 거래소 상장 말고 국가 대표(composite)만
        ex, tk = d.get('exchCode') or '', d.get('ticker') or ''
        if ex and tk and [ex, tk] not in out:
            out.append([ex, tk])
    return out[:4] or None


def main():
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
    global JOBS
    raw = json.load(open(RAW, encoding='utf-8'))
    names = {}
    for rows in raw['e'].values():
        for cd, nm, *_ in rows:
            if len(cd) == 12 and not cd.startswith('KR'):
                names[cd] = nm
    valid = {i: n for i, n in names.items() if isin_ok(i)}

    try:
        cache = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        cache = {'m': {}}
    m = cache.get('m', {})
    today = datetime.now(KST).strftime('%Y-%m-%d')
    cutoff = (datetime.now(KST) - timedelta(days=RETRY_DAYS)).strftime('%Y-%m-%d')
    todo = [i for i in valid if i not in m or (m[i][1] is None and (len(m[i]) < 3 or m[i][2] < cutoff))]
    log(f'해외 코드 {len(names)}개 / ISIN 정상 {len(valid)}개 (검사숫자 틀림 {len(names)-len(valid)}) / '
        f'캐시 {len(m)}개 / 새로 조회 {len(todo)}개 / 키 {"있음" if KEY else "없음"} (1회 {JOBS}건)')
    if limit:
        todo = todo[:limit]
    if not todo:
        log('✅ 새로 조회할 ISIN 없음')
        return

    t0, done, hit, i, calls, fails = time.time(), 0, 0, 0, 0, 0
    new = {}
    while i < len(todo):
        batch = todo[i:i + JOBS]
        jobs = [{'idType': 'ID_ISIN', 'idValue': x, 'marketSecDes': 'Equity'} for x in batch]
        res, code = post(jobs)
        calls += 1
        if code == 413 and JOBS > 5:
            JOBS = 5
            log('  ↪ 413(요청 건수 초과) → 1회 5건으로 줄임')
            continue
        if code == 429:
            log('  ⏳ 429(한도 초과) → 60초 쉬고 다시')
            time.sleep(60)
            continue
        if res is None:
            fails += 1
            if fails >= 5:
                log(f'❌ 연속 {fails}회 실패 (HTTP {code}) — 중단. 지금까지 찾은 {done}개는 저장')
                break
            log(f'  ❌ 응답 실패 (HTTP {code}) — 30초 뒤 다시')
            time.sleep(30)
            continue
        fails = 0
        for x, r in zip(batch, res):
            c = pick(r.get('data')) if isinstance(r, dict) else None
            new[x] = [valid[x], c] if c else [valid[x], None, today]
            hit += 1 if c else 0
        done += len(batch)
        i += len(batch)
        if done % 500 < len(batch):
            el = time.time() - t0
            log(f'  진행 {done}/{len(todo)} (찾음 {hit}, {el/60:.1f}분, 남은 약 {el/done*(len(todo)-done)/60:.0f}분)')
        time.sleep(SLEEP)

    el = time.time() - t0
    log(f'완료 {done}개 조회 / 찾음 {hit} / 못 찾음 {done-hit} / 호출 {calls}회 / {el/60:.1f}분')
    by_ex = {}
    for v in new.values():
        if v[1]:
            by_ex[v[1][0][0]] = by_ex.get(v[1][0][0], 0) + 1
    log('첫 후보 거래소별: ' + ', '.join(f'{k} {n}' for k, n in sorted(by_ex.items(), key=lambda x: -x[1])[:25]))

    if limit:
        for x in list(new)[:12]:
            print(f'   {x} {new[x][0][:28]:<28} → {new[x][1]}')
        log(f'  → 전체 {len(valid)-len(m)}개 예상 약 {el/max(done,1)*(len(valid)-len(m))/60:.0f}분 (테스트라 저장 안 함)')
        return

    m.update(new)
    out = {'updated': datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'n': len(m), 'm': m}
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    log(f'💾 isin_map.json {len(m)}개 ({os.path.getsize(OUT)//1024}KB)')


if __name__ == '__main__':
    main()
