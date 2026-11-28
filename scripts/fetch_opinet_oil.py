#!/usr/bin/env python3
"""
오피넷 국제유가(원유) + 국제석유제품(싱가포르) 일간 가격 → Oracle OIL_INTL_PRICES (107)
==========================================================================
- 원유:     https://www.opinet.co.kr/glopcoilSelect.do  (Dubai · Brent · WTI)
- 석유제품: https://www.opinet.co.kr/glopopdSelect.do   (싱가포르 휘발유·등유·경유·중유·나프타)
  · 등유(Jet/Kero) = 항공유. 유류할증료 산정 기준(MOPS)과 같은 제품 → /kal/ 기준값
  · 오피넷 오픈 API(8종)는 국내 주유소 가격뿐이라 국제가격은 웹 화면을 읽는다
- 오피넷 약관: 승낙 없는 복제·유통·제3자 이용 금지 → 레포(공개)에 JSON으로 두지 않고
  Oracle에만 저장, 사이트는 로그인 API(/api/oil-intl, 관리자)로만 읽는다. (129) 올라오자마자 받으려고 --watch가
  15분마다 보지만, 그날 값이 들어오면 오피넷을 더 부르지 않는다(1회 = 2요청).
- 갱신: 화~토, 하루 늦게(T+1). 싱가포르 휴장일은 값이 없음('-') — (141) --watch는 SG_HOLIDAYS 날짜를 건너뜀
- (141) 게시 시각: 11/25·26 08:46~09:00 사이, 11/27·28 08:49 → --watch 1분 감시 08:45~09:10

사용법 (레포 루트에서, . ~/.env_secrets 먼저)
  python3 scripts/fetch_opinet_oil.py --probe              # 최근 며칠 읽어서 화면에만 출력 (저장 안 함)
  python3 scripts/fetch_opinet_oil.py                      # 최근 며칠 → DB 저장 (크론)
  python3 scripts/fetch_opinet_oil.py --backfill 2025-01 --probe   # 과거 조회 출력만
  python3 scripts/fetch_opinet_oil.py --backfill 2025-01   # 2025-01부터 이번 달까지 한 달씩 → DB (요청 사이 3초)
  python3 scripts/fetch_opinet_oil.py --watch              # (129) 크론 화~토 08:00~18:45 15분마다: 전 평일 값(항공유·두바이)이
                                                           #   DB에 이미 있으면 오피넷을 안 부르고 끝, 없으면 읽어서 저장 → 항공유가 새로 생기면 봇1 DM
  python3 scripts/fetch_opinet_oil.py --status             # (116) DB에 언제부터 몇 일 쌓였는지 월별로 화면에만 (오피넷 호출 안 함)
"""
import os, sys, re, time, html, argparse
import urllib.request, urllib.parse, http.cookiejar
from datetime import date, datetime, timedelta, timezone

BASE = 'https://www.opinet.co.kr'
PAGES = {'crude': '/glopcoilSelect.do', 'prod': '/glopopdSelect.do'}
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
WALLET_DIR = os.path.expanduser('~/wallet')

# 화면 머리글 → DB 칸 (머리글 글자에서 공백·괄호 뺀 것으로 찾음)
COLS = [
    ('dubai', 'Dubai'), ('brent', 'Brent'), ('wti', 'WTI'),
    ('gas95', '휘발유95RON'), ('gas92', '휘발유92RON'), ('kero', '등유'),
    ('diesel001', '경유0.001%'), ('diesel005', '경유0.05%'),
    ('hsfo', '고유황중유180cst/3.5%'), ('naphtha', '나프타'),
]
DB_COLS = [c for c, _ in COLS]


def load_env():
    f = os.path.expanduser('~/.env_secrets')
    if os.path.exists(f):
        for line in open(f):
            line = line.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('export '): line = line[7:]
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def http_get(path):
    req = urllib.request.Request(BASE + path, headers={'User-Agent': UA})
    with _opener.open(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def http_post(path, fields):
    body = urllib.parse.urlencode([tuple(f) for f in fields]).encode()   # [이름, 값] 목록 → 튜플 (같은 이름 여러 개 그대로)
    req = urllib.request.Request(BASE + path, data=body, headers={
        'User-Agent': UA, 'Referer': BASE + path,
        'Content-Type': 'application/x-www-form-urlencoded'})
    with _opener.open(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def strip_tags(s):
    return html.unescape(re.sub(r'<[^>]+>', ' ', s)).strip()


def norm(s):
    return re.sub(r'[\s()]', '', s)


def parse_table(page):
    """결과 표 → {날짜(date): {칸: 값}}. 머리글로 칸 위치를 찾는다."""
    out = {}
    for tb in re.findall(r'<table[^>]*>(.*?)</table>', page, re.S | re.I):
        heads = [norm(strip_tags(h)) for h in re.findall(r'<th[^>]*>(.*?)</th>', tb, re.S | re.I)]
        if not heads or heads[0] != '기간':
            continue
        idx = {}
        for col, label in COLS:
            if label in heads:
                idx[col] = heads.index(label)
        if not idx:
            continue
        # 표 안에 tbody가 둘: tbody1(숨김) = 원화 환산, tbody2 = $/bbl. 달러 쪽만 읽는다
        m2 = re.search(r'<tbody[^>]*id=["\']?tbody2["\']?[^>]*>(.*?)</tbody>', tb, re.S | re.I)
        body = m2.group(1) if m2 else tb
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S | re.I):
            cells = [strip_tags(c) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S | re.I)]
            if not cells:
                continue
            m = re.match(r'(\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일', cells[0])
            if not m:
                continue
            d = date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
            row = {}
            for col, i in idx.items():
                v = cells[i].replace(',', '') if i < len(cells) else ''
                try:
                    f = float(v)
                    if f > 0: row[col] = f    # 0 = 그 시장 휴장(예: 미국 공휴일 WTI 0) → 값 없음으로
                except ValueError:
                    pass                      # '-' = 휴장
            if row:
                out.setdefault(d, {}).update(row)
    return out


def form_fields(page):
    """조회 form(form1)의 입력값 — 라디오는 선택된 것만, select는 선택된 옵션."""
    m = re.search(r'<form[^>]*name=["\']?form1["\']?[^>]*>(.*?)</form>', page, re.S | re.I)
    if not m:
        raise RuntimeError('조회 form을 못 찾음 (화면 구조 바뀜?)')
    f = m.group(1)
    fields = []
    for tag in re.findall(r'<input[^>]*>', f, re.I):
        name = re.search(r'name=["\']?([^"\'\s>]+)', tag)
        if not name: continue
        typ = (re.search(r'type=["\']?([^"\'\s>]+)', tag, re.I) or [None, 'text'])[1].lower()
        val = (re.search(r'value="([^"]*)"', tag) or re.search(r"value='([^']*)'", tag) or re.search(r'value=([^\s>]+)', tag) or [None, ''])[1]
        if typ in ('radio', 'checkbox') and not re.search(r'\bchecked\b', tag, re.I):
            continue
        if typ in ('button', 'submit', 'image'): continue
        fields.append([name.group(1), html.unescape(val)])
    for name, body in re.findall(r'<select[^>]*name=["\']?([^"\'\s>]+)[^>]*>(.*?)</select>', f, re.S | re.I):
        opts = []
        for o in re.findall(r'<option[^>]*>', body, re.I):
            v = re.search(r'value=["\']?([^"\'\s>]*)', o)
            if v: opts.append((o, v.group(1)))
        sel = [v for o, v in opts if re.search(r'\bselected\b', o, re.I)]
        if opts:
            fields.append([name, sel[0] if sel else opts[0][1]])
    return fields


def set_field(fields, name, value):
    hit = False
    for f in fields:
        if f[0] == name:
            f[1] = value; hit = True
    if not hit:
        fields.append([name, value])


def fetch_recent():
    rows = {}
    for kind, path in PAGES.items():
        got = parse_table(http_get(path))
        print(f'  {kind}: {len(got)}일')
        for d, r in got.items():
            rows.setdefault(d, {}).update(r)
        time.sleep(2)
    return rows


def fetch_month(y, m):
    """y년 m월 1일 ~ 말일 (휴장일 제외) — 화면의 「조회」와 같은 요청."""
    import calendar
    last = calendar.monthrange(y, m)[1]
    rows = {}
    for kind, path in PAGES.items():
        fields = form_fields(http_get(path))
        for k, v in (('TERM', 'D'), ('HOLIDAY_YN', 'N'),
                     ('STA_Y', str(y)), ('STA_M', f'{m:02d}'), ('STA_D', '01'),
                     ('END_Y', str(y)), ('END_M', f'{m:02d}'), ('END_D', f'{last:02d}'),
                     ('STDDATE', f'{y}{m:02d}01'), ('ENDDATE', f'{y}{m:02d}{last:02d}')):
            set_field(fields, k, v)
        got = parse_table(http_post(path, fields))
        for d, r in got.items():
            rows.setdefault(d, {}).update(r)
        time.sleep(3)
    return rows


def ensure_table(conn):
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM oil_intl_prices WHERE ROWNUM=1")
    except Exception:
        conn.rollback()
        cols = ',\n'.join(f'            {c} NUMBER(10,2)' for c in DB_COLS)
        cur.execute(f"""CREATE TABLE oil_intl_prices (
            price_date DATE NOT NULL,
{cols},
            updated_at TIMESTAMP DEFAULT SYSTIMESTAMP,
            CONSTRAINT pk_oil_intl_prices PRIMARY KEY (price_date)
        )""")
        conn.commit()
        print('✅ OIL_INTL_PRICES 테이블 생성')
    cur.close()


def save(conn, rows):
    cur = conn.cursor()
    sets = ', '.join(f't.{c}=NVL(:{c}, t.{c})' for c in DB_COLS)
    ins_c = ', '.join(DB_COLS)
    ins_v = ', '.join(f':i_{c}' for c in DB_COLS)      # 같은 이름 bind를 두 번 쓰지 않음 (sector_prices와 같은 방식)
    n = 0
    for d, r in sorted(rows.items()):
        p = {c: r.get(c) for c in DB_COLS}
        p.update({'i_' + c: r.get(c) for c in DB_COLS})
        p['dt'] = d; p['dt2'] = d
        cur.execute(f"""MERGE INTO oil_intl_prices t
            USING (SELECT :dt AS price_date FROM dual) s ON (t.price_date = s.price_date)
            WHEN MATCHED THEN UPDATE SET {sets}, t.updated_at=SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT (price_date, {ins_c}) VALUES (:dt2, {ins_v})""", p)
        n += 1
    # (107) 처음 받은 과거치에 휴장일 0이 들어가 있던 것 정리 (0 → NULL). 다음부터는 parse에서 걸러짐
    for c in DB_COLS:
        cur.execute(f'UPDATE oil_intl_prices SET {c}=NULL WHERE {c}<=0')
    conn.commit(); cur.close()
    return n


def db_connect():
    import oracledb
    return oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_tp', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))


def status():
    """(116) DB 범위만 화면에 — 값 자체는 출력하지 않음(약관: 복제·유통 금지)"""
    conn = db_connect(); cur = conn.cursor()
    cur.execute("SELECT MIN(price_date), MAX(price_date), COUNT(*), COUNT(kero), COUNT(dubai) FROM oil_intl_prices")
    mn, mx, n, nk, nd = cur.fetchone()
    print(f'전체: {mn:%Y-%m-%d} ~ {mx:%Y-%m-%d} / {n}일 (항공유 {nk}일 · 두바이 {nd}일)' if n else '❌ 비어 있음')
    cur.execute("""SELECT TO_CHAR(price_date,'YYYY-MM'), COUNT(*), COUNT(kero), COUNT(dubai)
                   FROM oil_intl_prices GROUP BY TO_CHAR(price_date,'YYYY-MM') ORDER BY 1""")
    for ym, c, k, d in cur.fetchall():
        print(f'  {ym}: {c:2d}일 (항공유 {k:2d} · 두바이 {d:2d})')
    cur.close(); conn.close()


def show(rows, limit=8):
    keys = sorted(rows)
    for d in keys[-limit:]:
        r = rows[d]
        print('  ' + d.isoformat() + '  ' + '  '.join(f'{c}={r[c]}' for c in DB_COLS if c in r))
    if len(keys) > limit:
        print(f'  … 총 {len(keys)}일 ({keys[0]} ~ {keys[-1]})')


# (130) 텔레그램 DM에 사이트 링크를 넣지 않음(사용자 요청)


def prev_weekday(today):
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# (141) 싱가포르 공휴일(평일만) — Platts 싱가포르가 쉬어서 항공유(MOPS 등유)·두바이 값이 안 나옴('-').
#   그날 값을 기다리는 --watch는 오피넷을 안 부르고 조용히 끝(브렌트·WTI는 21:20 정기 실행이 그대로 받음).
#   출처: 싱가포르 인력부(MOM) 공휴일 목록 — 일요일이면 다음 월요일. 매년 12월 다음 해 것 추가(정기 갱신 opinet-sg-holidays).
#   설 연휴는 Platts가 이틀 쉬는 해가 있음(2026: 2/17·18) — 그해 공지 보고 하루 더 넣기.
SG_HOLIDAYS = {
    '2026-12-25',                                   # 크리스마스(금)
    '2027-01-01',                                   # 새해(금)
    '2027-02-08',                                   # 설(2/6 토·2/7 일 → 2/8 월 대체) — Platts 공지로 2/9 쉬는지 확인
}


def watch():
    """(129) 전 평일 값이 올라왔는지 확인 — 이미 DB에 있으면 조용히 끝(오피넷 호출 없음)."""
    now = datetime.now(timezone(timedelta(hours=9)))
    target = prev_weekday(now.date())
    if target.isoformat() in SG_HOLIDAYS:
        return                                      # (141) 싱가포르 공휴일 — 값이 안 나오는 날
    conn = db_connect(); cur = conn.cursor()
    cur.execute("SELECT kero, dubai FROM oil_intl_prices WHERE price_date = :d", {'d': target})
    had = cur.fetchone()
    had_kero = bool(had and had[0])
    if had and had[0] and had[1]:
        cur.close(); conn.close(); return          # 둘 다 있음 — 할 일 없음 (로그도 안 씀)
    rows = fetch_recent()
    got = rows.get(target) or {}
    if not got.get('kero') and not got.get('dubai'):
        print(f'[{now:%m/%d %H:%M}] 아직 없음 — {target:%m/%d} 값 (최신 {max(rows):%m/%d})' if rows else f'[{now:%m/%d %H:%M}] ❌ 읽은 값 없음')
        cur.close(); conn.close(); return
    save(conn, rows)
    print(f'[{now:%m/%d %H:%M}] ✅ {target:%m/%d} 값 저장 (항공유 {"있음" if got.get("kero") else "없음"} · 두바이 {"있음" if got.get("dubai") else "없음"})')
    if got.get('kero') and not had_kero:
        cur.execute("""SELECT kero FROM (SELECT kero FROM oil_intl_prices WHERE price_date < :d AND kero > 0
                       ORDER BY price_date DESC) WHERE ROWNUM = 1""", {'d': target})
        pr = cur.fetchone()
        k, du = float(got['kero']), (float(got['dubai']) if got.get('dubai') else None)
        t = f"<b>✈️ 오피넷 {target.month}/{target.day} 값 올라옴</b> ({now:%H:%M} 확인)\n항공유 ${k:.2f}"
        if pr and pr[0]:
            t += f" ({k - float(pr[0]):+.2f})"
        if du:
            t += f" · 두바이 ${du:.2f} · 스프레드 ${k - du:.2f}"
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from telegram_helper import send_dm
            send_dm(t)
        except Exception as e:
            print(f'  ⚠ 텔레그램 실패: {e}')
    cur.close(); conn.close()


def main():
    ap = argparse.ArgumentParser(description='오피넷 국제유가·석유제품 → Oracle')
    ap.add_argument('--probe', action='store_true', help='출력만, 저장 안 함')
    ap.add_argument('--backfill', metavar='YYYY-MM', help='이 달부터 이번 달까지 한 달씩')
    ap.add_argument('--status', action='store_true', help='(116) DB 범위만 월별로 출력')
    ap.add_argument('--watch', action='store_true', help='(129) 전 평일 값이 올라왔는지 — 있으면 오피넷 안 부름, 새로 받으면 봇1 DM')
    a = ap.parse_args()
    load_env()
    if a.status:
        status()
        return
    if a.watch:
        watch()
        return

    print(f'=== 오피넷 국제유가 {"과거 " + a.backfill + "~" if a.backfill else "최근"} ({"출력만" if a.probe else "DB 저장"}) ===')
    rows = {}
    if a.backfill:
        y, m = map(int, a.backfill.split('-'))
        t = date.today()
        while (y, m) <= (t.year, t.month):          # 이번 달까지 (이번 달은 오늘까지 나온 날만)
            got = fetch_month(y, m)
            print(f'  {y}-{m:02d}: {len(got)}일')
            rows.update(got)
            m += 1
            if m > 12: y, m = y + 1, 1
    else:
        rows = fetch_recent()

    if not rows:
        print('❌ 읽은 값 없음 — 화면 구조가 바뀌었거나 접속 실패')
        sys.exit(1)
    if not any('kero' in r for r in rows.values()):
        print('❌ 등유(항공유) 값 없음 — 석유제품 화면 확인 필요')
        sys.exit(1)
    show(rows)
    if a.probe:
        print('(출력만 — 저장 안 함)')
        return

    conn = db_connect()
    ensure_table(conn)
    n = save(conn, rows)
    conn.close()
    print(f'✅ 저장 {n}일')


if __name__ == '__main__':
    main()
