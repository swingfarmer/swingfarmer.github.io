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

2단계 (083) — 야후 티커 (data/kr/etf/yahoo_map.json, {updated, n, m: {ISIN: [야후티커 또는 null, 'YYYY-MM-DD']}})
  OpenFIGI 결과로 바로 yfinance 티커를 만들 수 있는 것: 미국(US)·일본(JP→.T)·중국 A주(CH→.SS/.SZ)
  나머지(영국·홍콩·대만·인도·유럽·케이맨 등)는 야후 검색(ISIN)으로 본국 티커를 받음 (예: 2330.TW, 0388.HK, BARC.L)
  야후에서 못 찾은 건 30일 뒤 재시도

사용법
  python3 scripts/fetch_isin_map.py --limit 30          # 테스트: OpenFIGI 새 ISIN 30개만, 저장 안 함
  python3 scripts/fetch_isin_map.py                     # OpenFIGI 새 ISIN 전부 → 저장 → 이어서 야후 단계
  python3 scripts/fetch_isin_map.py --yahoo --limit 40  # 테스트: 야후 단계만 40개, 저장 안 함
  python3 scripts/fetch_isin_map.py --yahoo             # 야후 단계만 (새로 필요한 것 전부) → 저장
"""
import os, sys, json, time, urllib.request, urllib.error, urllib.parse
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
YOUT = os.path.join(ROOT, 'data', 'kr', 'etf', 'yahoo_map.json')
YAHOO_URL = 'https://query2.finance.yahoo.com/v1/finance/search'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'}
YSLEEP = 0.5


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


def figi_symbol(isin, cands):
    """OpenFIGI 후보로 바로 만들 수 있는 yfinance 티커. 못 만들면 None (→ 야후 검색)."""
    c = isin[:2]
    for ex, tk in cands or []:
        if c == 'US' and ex == 'US':
            return tk.replace('/', '-')                      # BRK/B → BRK-B
        if c == 'JP' and ex == 'JP' and tk.isdigit():
            return tk + '.T'
        if c == 'CN' and ex == 'CH' and len(tk) == 6 and tk.isdigit():
            if tk[0] == '6':
                return tk + '.SS'                            # 상하이 (688 과창판 포함)
            if tk[0] in '03':
                return tk + '.SZ'                            # 선전 (300 창업판 포함)
    return None


def yahoo_search(isin):
    """→ (야후 티커 또는 None, 오류문자열). 주식(EQUITY)·ETF 중 첫 번째, 독일 슈투트가르트 ISIN 티커(.SG)는 제외."""
    url = YAHOO_URL + '?' + urllib.parse.urlencode({'q': isin, 'quotesCount': 5, 'newsCount': 0, 'listsCount': 0})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return None, f'HTTP {e.code}'
    except Exception as e:
        return None, repr(e)[:80]
    for q in d.get('quotes', []):
        sym = q.get('symbol') or ''
        if q.get('quoteType') in ('EQUITY', 'ETF') and sym and not sym.startswith(isin):
            return sym, ''
    return None, ''


def yahoo_stage(limit):
    m = json.load(open(OUT, encoding='utf-8')).get('m', {})
    try:
        ym = json.load(open(YOUT, encoding='utf-8')).get('m', {})
    except Exception:
        ym = {}
    today = datetime.now(KST).strftime('%Y-%m-%d')
    cutoff = (datetime.now(KST) - timedelta(days=RETRY_DAYS)).strftime('%Y-%m-%d')
    figi_ok = sum(1 for i, v in m.items() if figi_symbol(i, v[1]))
    need = [i for i, v in m.items() if not figi_symbol(i, v[1])]
    # OpenFIGI가 못 찾은 미국·XS 코드는 거의 다 채권(국채·회사채)이라 야후도 안 물어봄
    need = [i for i in need if not (m[i][1] is None and i[:2] in ('US', 'XS'))]
    todo = [i for i in need if i not in ym or (ym[i][0] is None and ym[i][1] < cutoff)]
    log(f'[야후] OpenFIGI로 바로 티커 {figi_ok}개 / 야후 필요 {len(need)}개 / 캐시 {len(ym)}개 / 새로 조회 {len(todo)}개')
    if limit:
        todo = todo[:limit]
    if not todo:
        log('✅ [야후] 새로 조회할 ISIN 없음')
        return
    t0, hit, fails, new = time.time(), 0, 0, {}
    for n, isin in enumerate(todo, 1):
        sym, err = yahoo_search(isin)
        if err:
            fails += 1
            if err.startswith('HTTP 429') or fails >= 5:
                log(f'  ⏳ [야후] {err} (연속 실패 {fails}) → 60초 쉼')
                time.sleep(60)
                if fails >= 8:
                    log('❌ [야후] 계속 실패 — 중단, 지금까지 찾은 것만 저장')
                    break
            continue
        fails = 0
        new[isin] = [sym, today]
        hit += 1 if sym else 0
        if n % 200 == 0:
            el = time.time() - t0
            log(f'  [야후] 진행 {n}/{len(todo)} (찾음 {hit}, {el/60:.1f}분, 남은 약 {el/n*(len(todo)-n)/60:.0f}분)')
        time.sleep(YSLEEP)
    el = time.time() - t0
    sfx = {}
    for v in new.values():
        if v[0]:
            k = '.' + v[0].rsplit('.', 1)[1] if '.' in v[0] else '(미국)'
            sfx[k] = sfx.get(k, 0) + 1
    log(f'[야후] 완료 {len(new)}개 조회 / 찾음 {hit} / 못 찾음 {len(new)-hit} / {el/60:.1f}분')
    log('[야후] 거래소 접미사별: ' + ', '.join(f'{k} {n}' for k, n in sorted(sfx.items(), key=lambda x: -x[1])[:25]))
    if limit:
        for isin in list(new)[:15]:
            print(f'   {isin} {m[isin][0][:28]:<28} → {new[isin][0]}')
        log(f'  → 전체 {len(need)-len(ym)}개 예상 약 {el/max(len(new),1)*(len(need)-len(ym))/60:.0f}분 (테스트라 저장 안 함)')
        return
    ym.update(new)
    tmp = YOUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'updated': datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'n': len(ym), 'm': ym},
                  f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, YOUT)
    log(f'💾 yahoo_map.json {len(ym)}개 ({os.path.getsize(YOUT)//1024}KB)')


def main():
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
    if '--yahoo' in sys.argv:
        return yahoo_stage(limit)
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
        if not limit:
            yahoo_stage(0)
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
    yahoo_stage(0)


if __name__ == '__main__':
    main()
