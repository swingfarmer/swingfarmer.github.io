#!/usr/bin/env python3
"""
관심 부동산 새 실거래 알림 (082) — VM 크론 전용
================================================
관심 목록: Oracle USER_SETTINGS 're_watch' (실거래 트래커 ⭐관심 탭에서 편집)
  {"v":1, "items":[{"id","label","prop":"APT|OFT|COM","region","dong","name",
                    "area_min","area_max","types":["S","J","W"],"price_min","price_max","notify":true}]}
  name 은 건물명 일부(쉼표로 여러 개 OR), 금액은 만원, 면적은 전용㎡.

동작
  1) 항목마다 DB에서 조건에 맞고 계약일이 최근 WINDOW_DAYS 일 안인 거래를 읽음
  2) 지난번에 본 거래 목록(~/sf_live/re_watch_seen.json)에 없는 것 = 새 거래
     (국토부 신고는 계약 후 30일 이내라, 계약일이 지난 거래도 늦게 새로 뜰 수 있음)
  3) 새 거래 → 텔레그램 봇2. 처음 등록된 항목은 기존 거래를 '본 것'으로만 저장(알림 폭탄 방지)
  4) 알림 이력 → USER_SETTINGS 're_watch_log' (웹 ⭐관심 탭이 읽음, 최근 LOG_KEEP 건)

사용법
  python3 scripts/re_watch.py           # 정상 실행
  python3 scripts/re_watch.py --dry     # 새 거래만 화면 출력, 텔레그램·저장 안 함
  python3 scripts/re_watch.py --test    # 텔레그램 봇2 연결 테스트 메시지 1건

크론: 실거래 수집 두 개 뒤에 이어서 (같은 줄, ; 로 연결 — 수집이 일부 실패해도 알림은 돔)
"""
import os, sys, json, hashlib
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

KST = timezone(timedelta(hours=9))
WINDOW_DAYS = 100        # 계약일 기준 이만큼 안의 거래만 비교 (신고 지연 30일 + 여유)
LOG_KEEP = 300
MAX_PER_ITEM = 15        # 한 항목에서 한 번에 보내는 최대 건수 (나머지는 개수만)
SEEN_FILE = os.path.expanduser('~/sf_live/re_watch_seen.json')
WALLET_DIR = os.path.expanduser('~/wallet')
PROP_LABEL = {'APT': '아파트', 'OFT': '오피스텔', 'COM': '상업용'}
DEAL_LABEL = {'S': '매매', 'J': '전세', 'W': '월세'}


def log(*a):
    print(datetime.now(KST).strftime('%H:%M:%S'), *a, flush=True)


def get_conn():
    import oracledb
    return oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))


def read_setting(cur, key):
    cur.execute("SELECT setting_value FROM user_settings WHERE setting_key=:k", {'k': key})
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    v = row[0]
    return v.read() if hasattr(v, 'read') else v


def write_setting(cur, key, value):
    cur.setinputsizes(v=__import__('oracledb').DB_TYPE_CLOB)
    cur.execute("""MERGE INTO user_settings t
        USING (SELECT :k AS setting_key FROM dual) s
        ON (t.setting_key = s.setting_key)
        WHEN MATCHED THEN UPDATE SET setting_value = :v, updated_at = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT (setting_key, setting_value) VALUES (:k, :v)""",
        {'k': key, 'v': value})


def num(v):
    try:
        if v in (None, ''):
            return None
        return float(v)
    except Exception:
        return None


def build_query(it, since):
    """항목 조건 → (WHERE, params). 계약일 since(YYYYMMDD 정수) 이후만."""
    where = ['prop_type=:prop']
    p = {'prop': it.get('prop') or 'APT'}
    if it.get('region'):
        where.append('region=:rg'); p['rg'] = it['region']
    if it.get('dong'):
        where.append('dong=:dg'); p['dg'] = it['dong']
    names = [n.strip() for n in (it.get('name') or '').split(',') if n.strip()]
    if names:
        ors = []
        for i, n in enumerate(names):
            ors.append(f"UPPER(name) LIKE '%'||UPPER(:nm{i})||'%'"); p[f'nm{i}'] = n
        where.append('(' + ' OR '.join(ors) + ')')
    types = [t for t in (it.get('types') or []) if t in ('S', 'J', 'W')]
    if types and len(types) < 3:
        where.append('deal_type IN (' + ','.join(f':dt{i}' for i in range(len(types))) + ')')
        p.update({f'dt{i}': t for i, t in enumerate(types)})
    if num(it.get('area_min')) is not None:
        where.append('area_m2>=:amin'); p['amin'] = num(it['area_min'])
    if num(it.get('area_max')) is not None:
        where.append('area_m2<=:amax'); p['amax'] = num(it['area_max'])
    amt = "(CASE WHEN deal_type='S' THEN price ELSE NVL(deposit,0) END)"
    if num(it.get('price_min')) is not None:
        where.append(f'{amt}>=:pmin'); p['pmin'] = num(it['price_min'])
    if num(it.get('price_max')) is not None:
        where.append(f'{amt}<=:pmax'); p['pmax'] = num(it['price_max'])
    where.append("TO_NUMBER(deal_year)*10000+TO_NUMBER(deal_month)*100+TO_NUMBER(deal_day)>=:since")
    p['since'] = since
    return ' AND '.join(where), p


COLS = 'region, name, dong, area_m2, floor_no, deal_type, price, deposit, monthly_rent, deal_year, deal_month, deal_day, build_year'


def row_to_deal(r):
    d = dict(zip(['region', 'name', 'dong', 'area', 'floor', 'type', 'price', 'deposit', 'rent',
                  'y', 'm', 'd', 'build'], r))
    d['area'] = float(d['area'] or 0)
    for k in ('price', 'deposit', 'rent'):
        d[k] = int(d[k]) if d[k] is not None else None
    d['ymd'] = int(d['y']) * 10000 + int(d['m']) * 100 + int(d['d'])
    return d


def deal_key(d):
    s = '|'.join(str(d[k]) for k in ('region', 'name', 'dong', 'area', 'floor', 'type',
                                      'price', 'deposit', 'rent', 'y', 'm', 'd'))
    return hashlib.md5(s.encode('utf-8')).hexdigest()[:16]


def eok(man):
    """만원 → '7.0억' / '9,500만'"""
    if man is None:
        return '-'
    if man >= 10000:
        e = man / 10000
        t = f'{e:.2f}' if e < 10 else f'{e:.1f}'
        return t.rstrip('0').rstrip('.') + '억'
    return f'{man:,}만'


def amount_text(d):
    if d['type'] == 'S':
        return f"매매 {eok(d['price'])}"
    if d['type'] == 'J':
        return f"전세 {eok(d['deposit'])}"
    return f"월세 {eok(d['deposit'])}/{d['rent'] or 0}"


def prev_same(cur, it, d):
    """같은 건물·같은 거래유형·전용 ±3㎡에서 이 거래 직전 거래 (비교용)"""
    q = f"""SELECT * FROM (SELECT {COLS} FROM real_estate
        WHERE prop_type=:prop AND region=:rg AND name=:nm AND deal_type=:dt
          AND area_m2 BETWEEN :a1 AND :a2
          AND TO_NUMBER(deal_year)*10000+TO_NUMBER(deal_month)*100+TO_NUMBER(deal_day) < :ymd
        ORDER BY TO_NUMBER(deal_year) DESC, TO_NUMBER(deal_month) DESC, TO_NUMBER(deal_day) DESC)
        WHERE ROWNUM=1"""
    cur.execute(q, {'prop': it.get('prop') or 'APT', 'rg': d['region'], 'nm': d['name'], 'dt': d['type'],
                    'a1': d['area'] - 3, 'a2': d['area'] + 3, 'ymd': d['ymd']})
    r = cur.fetchone()
    return row_to_deal(r) if r else None


def deal_value(d):
    return d['price'] if d['type'] == 'S' else d['deposit']


def fmt_deal(d, prev):
    py = d['area'] / 3.3058
    lines = [f"<b>{d['name']}</b> · {d['dong']} · {d['area']:g}㎡({py:.1f}평) {d['floor']}층",
             f"{amount_text(d)}" + (f" (평당 {d['price']/py:,.0f}만)" if d['type'] == 'S' and d['price'] else '') +
             f" · 계약 {d['y']}.{int(d['m']):02d}.{int(d['d']):02d}"]
    if prev and deal_value(prev) and deal_value(d):
        ch = (deal_value(d) / deal_value(prev) - 1) * 100
        lines.append(f"  직전 {eok(deal_value(prev))}({prev['y']}.{int(prev['m']):02d}) 대비 {ch:+.1f}%")
    return '\n'.join(lines)


def main():
    dry = '--dry' in sys.argv
    from telegram_helper import send_dm_bot2
    if '--test' in sys.argv:
        ok = send_dm_bot2('🏠 관심 부동산 알림 테스트 — 봇2 연결 정상')
        log('테스트 메시지', '전송' if ok else '실패'); return

    conn = get_conn(); cur = conn.cursor()
    raw = read_setting(cur, 're_watch')
    items = (json.loads(raw).get('items') if raw else []) or []
    log(f'관심 항목 {len(items)}개' + (' (dry)' if dry else ''))

    seen = {}
    if os.path.exists(SEEN_FILE):
        try:
            seen = json.load(open(SEEN_FILE, encoding='utf-8'))
        except Exception:
            seen = {}
    since_d = date.today() - timedelta(days=WINDOW_DAYS)
    since = since_d.year * 10000 + since_d.month * 100 + since_d.day

    log_raw = read_setting(cur, 're_watch_log')
    wlog = json.loads(log_raw) if log_raw else {'entries': []}
    run_at = datetime.now(KST).strftime('%Y-%m-%d %H:%M')
    new_seen, total_new = {}, 0

    for it in items:
        iid = it.get('id')
        if not iid:
            continue
        if not (it.get('region') or it.get('name')):
            log(f'  건너뜀 {it.get("label")}: 지역이나 건물명 중 하나는 있어야 함'); continue
        w, p = build_query(it, since)
        cur.execute(f"SELECT DISTINCT {COLS} FROM real_estate WHERE {w}", p)
        deals = [row_to_deal(r) for r in cur.fetchall()]
        keys = {deal_key(d): d for d in deals}
        first = iid not in seen
        old = set(seen.get(iid, []))
        new_seen[iid] = sorted(keys)
        if first:
            log(f'  {it.get("label")}: 처음 등록 — 기존 {len(keys)}건 기준으로 저장 (알림 없음)')
            continue
        fresh = sorted((keys[k] for k in keys if k not in old), key=lambda d: -d['ymd'])
        if not fresh:
            log(f'  {it.get("label")}: 새 거래 없음 ({len(keys)}건)'); continue
        total_new += len(fresh)
        log(f'  {it.get("label")}: 새 거래 {len(fresh)}건')
        if not it.get('notify', True):
            log('    (알림 꺼짐 — 이력만 저장)')
        parts = []
        for d in fresh[:MAX_PER_ITEM]:
            prev = prev_same(cur, it, d)
            parts.append(fmt_deal(d, prev))
            wlog['entries'].append({'t': run_at, 'id': iid, 'label': it.get('label'),
                                    'prop': it.get('prop'), 'd': {k: d[k] for k in (
                                        'name', 'dong', 'area', 'floor', 'type', 'price', 'deposit', 'rent', 'y', 'm', 'd')},
                                    'prev': deal_value(prev) if prev else None})
        head = f"🏠 <b>[관심] {it.get('label')}</b> — {PROP_LABEL.get(it.get('prop'), '')} 새 실거래 {len(fresh)}건"
        msg = head + '\n\n' + '\n\n'.join(parts)
        if len(fresh) > MAX_PER_ITEM:
            msg += f'\n\n…외 {len(fresh) - MAX_PER_ITEM}건 (웹 ⭐관심 탭)'
        if dry:
            print(msg.replace('<b>', '').replace('</b>', '')); print()
        elif it.get('notify', True):
            for i in range(0, len(msg), 3800):          # 텔레그램 4096자 제한
                send_dm_bot2(msg[i:i+3800])

    if dry:
        log(f'dry 끝 — 새 거래 {total_new}건 (저장 안 함)'); return

    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(new_seen, f)
    wlog['entries'] = wlog['entries'][-LOG_KEEP:]
    wlog['updated'] = run_at
    wlog['last_run'] = {'at': run_at, 'items': len(items), 'new': total_new}
    write_setting(cur, 're_watch_log', json.dumps(wlog, ensure_ascii=False, separators=(',', ':')))
    conn.commit()
    cur.close(); conn.close()
    log(f'✅ 끝 — 새 거래 {total_new}건')


if __name__ == '__main__':
    main()
