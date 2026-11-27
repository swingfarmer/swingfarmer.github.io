#!/usr/bin/env python3
"""
Firestore 매일 백업 (140)
=========================
- 맨 위 관리자 계정(common.js SF_ADMIN_UIDS 첫 번째)의 로그인 유지 토큰으로 접속해서
  저장 문서 calc_data/{첫 UID} 하나를 받아 VM 안에만 보관한다.
  (계산기 FAB 저장·내 메뉴 트리·/guide/ 수정분이 전부 이 문서에 있음 — 어느 관리자로 저장해도 여기로 감)
- 토큰 파일: ~/.fb_backup_token (사이트 /status/ 맨 아래 「VM 등록 명령 복사」 버튼으로 넣음, chmod 600)
- 보관: ~/backups/firestore/calc_data_YYYY-MM-DD.json
    최근 30일치 + 매달 1일치는 계속 (GitHub에는 안 올림 — 자산 기록이 들어 있음)
- 상태: ~/backups/firestore/last.json (헬스체크가 신선도 확인)
- 알림 [봇1]: 실패했을 때, 또는 문서가 갑자기 많이 줄었을 때(삭제·덮어쓰기 의심)만. 정상이면 안 보냄.

수동 실행:  python3 scripts/backup_firestore.py

되살리기 (141):
  python3 scripts/backup_firestore.py --list                      ← 백업 파일 목록(날짜·크기·항목 수)
  python3 scripts/backup_firestore.py --restore 2026-11-28        ← 그날 백업과 지금을 항목별로 비교 → y 치면 다른 항목만 되돌림
  python3 scripts/backup_firestore.py --restore 2026-11-28 --field margin-ratio,sf_tree   ← 고른 항목만
  - 항목 = 문서 안 칸 하나(페이지별 저장 칸: margin-ratio, guide_edits 등). 지금만 있는 항목은 건드리지 않음.
  - y 치기 전엔 아무것도 안 바뀜. y 치면 먼저 지금 상태를 ~/backups/firestore/before_restore_날짜_시각.json 으로 저장 → 되살리기가 잘못돼도 이 파일로 다시 되돌릴 수 있음
    (그 파일 되돌리기: --restore 파일경로 도 됨)
"""
import os, re, sys, json, glob, datetime, urllib.request, urllib.parse, urllib.error

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'scripts'))
try:
    from telegram_helper import send_dm
except Exception:
    def send_dm(msg): print(msg); return False

PROJECT = 'swingfarmer-board01'
TOKEN_FILE = os.path.expanduser('~/.fb_backup_token')
OUT_DIR = os.path.expanduser('~/backups/firestore')
KEEP_DAYS = 30
SHRINK_ALERT = 0.5      # 바로 전 백업보다 크기가 이 비율 아래로 줄면 알림
KST = datetime.timezone(datetime.timedelta(hours=9))


def read_common():
    src = open(os.path.join(ROOT_DIR, 'common.js'), encoding='utf-8').read()
    m = re.search(r"window\.SF_ADMIN_UIDS\s*=\s*Object\.freeze\(\s*\[([^\]]*)\]", src)
    uids = re.findall(r"'([^']+)'", m.group(1)) if m else []
    k = re.search(r"apiKey:'([^']+)'", src)
    return (uids[0] if uids else None), (k.group(1) if k else None)


def http_json(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def get_id_token(api_key, refresh_token):
    body = urllib.parse.urlencode({'grant_type': 'refresh_token', 'refresh_token': refresh_token}).encode()
    d = http_json(f'https://securetoken.googleapis.com/v1/token?key={api_key}', data=body,
                  headers={'Content-Type': 'application/x-www-form-urlencoded'})
    return d['id_token'], d.get('refresh_token'), d.get('user_id')


def count_fields(doc):
    return len((doc or {}).get('fields', {}))


def prune(today):
    files = sorted(glob.glob(os.path.join(OUT_DIR, 'calc_data_*.json')))
    removed = 0
    for f in files:
        m = re.search(r'calc_data_(\d{4})-(\d{2})-(\d{2})\.json$', f)
        if not m:
            continue
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d.day == 1:
            continue                      # 매달 1일치는 계속 보관
        if (today - d).days > KEEP_DAYS:
            os.remove(f); removed += 1
    return removed


def fail(msg):
    print('❌', msg, flush=True)
    json.dump({'ok': False, 'at': datetime.datetime.now(KST).isoformat(timespec='seconds'), 'error': msg},
              open(os.path.join(OUT_DIR, 'last.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    send_dm(f'🗄 <b>Firestore 백업 실패</b>\n{msg}')
    sys.exit(1)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.chmod(OUT_DIR, 0o700)
    now = datetime.datetime.now(KST)
    today = now.date()

    uid0, api_key = read_common()
    if not uid0 or not api_key:
        fail('common.js에서 첫 관리자 UID·API 키를 못 읽음')
    if not os.path.exists(TOKEN_FILE):
        fail('토큰 파일 없음(~/.fb_backup_token) — 사이트 /status/ 맨 아래 「VM 등록 명령 복사」로 넣기')
    refresh = open(TOKEN_FILE, encoding='utf-8').read().strip()

    try:
        id_token, new_refresh, user_id = get_id_token(api_key, refresh)
    except urllib.error.HTTPError as e:
        fail(f'백업 토큰 끊김(HTTP {e.code}) — 비밀번호 변경·전체 로그아웃 때 생김. 맨 위 계정으로 /status/ 맨 아래 버튼 → VM에 다시 붙여 넣기')
    except Exception as e:
        fail(f'토큰 교환 오류: {type(e).__name__}: {str(e)[:150]}')
    if user_id and user_id != uid0:
        fail('토큰이 맨 위 계정 것이 아님 — 맨 위 계정으로 로그인해서 다시 복사')
    if new_refresh and new_refresh != refresh:
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(new_refresh)
        os.chmod(TOKEN_FILE, 0o600)

    url = f'https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents/calc_data/{uid0}'
    try:
        doc = http_json(url, headers={'Authorization': f'Bearer {id_token}'})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            fail('저장 문서가 없음(404) — 지워졌을 수 있음! 지난 백업 파일은 그대로 있음')
        fail(f'문서 읽기 오류 HTTP {e.code}')
    except Exception as e:
        fail(f'문서 읽기 오류: {type(e).__name__}: {str(e)[:150]}')

    raw = json.dumps(doc, ensure_ascii=False)
    size, fields = len(raw.encode('utf-8')), count_fields(doc)

    # 바로 전 백업과 비교 (오늘 파일 덮어쓰기 전에)
    prev = [f for f in sorted(glob.glob(os.path.join(OUT_DIR, 'calc_data_*.json')))
            if not f.endswith(f'calc_data_{today}.json')]
    warn = None
    if prev:
        p = prev[-1]
        psize = os.path.getsize(p)
        try:
            pfields = count_fields(json.load(open(p, encoding='utf-8')))
        except Exception:
            pfields = 0
        if psize and size < psize * SHRINK_ALERT:
            warn = f'크기 {psize:,} → {size:,} 바이트로 크게 줄었음'
        elif pfields and fields < pfields:
            warn = f'항목 {pfields}개 → {fields}개로 줄었음'
        if warn:
            warn += f' (비교: {os.path.basename(p)}) — 삭제·덮어쓰기인지 확인. 지난 백업은 그대로 있음'

    out = os.path.join(OUT_DIR, f'calc_data_{today}.json')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(raw)
    os.chmod(out, 0o600)
    removed = prune(today)

    json.dump({'ok': True, 'at': now.isoformat(timespec='seconds'), 'file': os.path.basename(out),
               'bytes': size, 'fields': fields, 'warn': warn},
              open(os.path.join(OUT_DIR, 'last.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    total = len(glob.glob(os.path.join(OUT_DIR, 'calc_data_*.json')))
    print(f'✅ {now:%F %T} {os.path.basename(out)} {size:,}바이트 · 항목 {fields}개 · 보관 {total}개 · 정리 {removed}개', flush=True)
    if warn:
        send_dm(f'🗄 <b>Firestore 백업 — 문서가 줄었음</b>\n{warn}')


# ── 되살리기 (141) ─────────────────────────────────────────
def fmt_bytes(n):
    return f'{n:,}바이트' if n < 10000 else f'{n/1024:,.0f}KB'


def field_path(k):
    """Firestore REST updateMask 칸 이름 — 영문·숫자·_ 아니면 `…`로 감쌈 (margin-ratio 같은 이름)"""
    if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', k):
        return k
    return '`' + k.replace('\\', '\\\\').replace('`', '\\`') + '`'


def val_size(v):
    return len(json.dumps(v, ensure_ascii=False, sort_keys=True).encode('utf-8'))


def compare(cur_fields, bak_fields):
    """항목별 비교 → [(이름, 상태, 지금 크기, 백업 크기)] 상태: 같음/바뀜/지금 없음/지금만"""
    rows = []
    for k in sorted(set(cur_fields) | set(bak_fields)):
        c, b = cur_fields.get(k), bak_fields.get(k)
        if b is None:
            st = '지금만'
        elif c is None:
            st = '지금 없음'
        elif json.dumps(c, sort_keys=True) == json.dumps(b, sort_keys=True):
            st = '같음'
        else:
            st = '바뀜'
        rows.append((k, st, val_size(c) if c is not None else 0, val_size(b) if b is not None else 0))
    return rows


def connect():
    uid0, api_key = read_common()
    if not uid0 or not api_key:
        sys.exit('❌ common.js에서 첫 관리자 UID·API 키를 못 읽음')
    if not os.path.exists(TOKEN_FILE):
        sys.exit('❌ 토큰 파일 없음(~/.fb_backup_token)')
    refresh = open(TOKEN_FILE, encoding='utf-8').read().strip()
    try:
        id_token, new_refresh, user_id = get_id_token(api_key, refresh)
    except urllib.error.HTTPError as e:
        sys.exit(f'❌ 토큰 끊김(HTTP {e.code}) — /status/ 맨 아래 버튼으로 다시 넣기')
    if user_id and user_id != uid0:
        sys.exit('❌ 토큰이 맨 위 계정 것이 아님')
    if new_refresh and new_refresh != refresh:
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(new_refresh)
        os.chmod(TOKEN_FILE, 0o600)
    url = f'https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents/calc_data/{uid0}'
    return url, {'Authorization': f'Bearer {id_token}'}


def cmd_list():
    files = sorted(glob.glob(os.path.join(OUT_DIR, 'calc_data_*.json')) +
                   glob.glob(os.path.join(OUT_DIR, 'before_restore_*.json')))
    if not files:
        print('백업 파일 없음 —', OUT_DIR); return
    for f in files:
        try:
            n = count_fields(json.load(open(f, encoding='utf-8')))
        except Exception:
            n = '?'
        print(f'  {os.path.basename(f):48s} {fmt_bytes(os.path.getsize(f)):>10s} · 항목 {n}개')


def cmd_restore(which, only=None, answer=None):
    if os.path.exists(which):
        path = which
    else:
        path = os.path.join(OUT_DIR, f'calc_data_{which}.json')
    if not os.path.exists(path):
        sys.exit(f'❌ 백업 파일 없음: {path}\n   목록 보기: python3 scripts/backup_firestore.py --list')
    bak = json.load(open(path, encoding='utf-8'))
    bak_fields = bak.get('fields', {})

    url, auth = connect()
    try:
        cur = http_json(url, headers=auth)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            sys.exit(f'❌ 지금 문서 읽기 오류 HTTP {e.code}')
        cur = {}                                  # 문서가 통째로 지워진 경우
    cur_fields = cur.get('fields', {})

    rows = compare(cur_fields, bak_fields)
    if only:
        miss = [k for k in only if k not in bak_fields]
        if miss:
            sys.exit(f'❌ 백업에 없는 항목: {", ".join(miss)}')
        rows = [r for r in rows if r[0] in only]

    print(f'비교: 지금 ↔ {os.path.basename(path)}' + ('' if cur else '  (지금 문서 없음 — 통째로 되살림)'))
    for k, st, cs, bs in rows:
        mark = {'같음': '  ', '바뀜': '🔁', '지금 없음': '➕', '지금만': '··'}[st]
        print(f'  {mark} {k:28s} {st:6s}  지금 {fmt_bytes(cs):>10s} → 백업 {fmt_bytes(bs):>10s}')
    todo = [k for k, st, _, _ in rows if st in ('바뀜', '지금 없음')]
    print('  (🔁 바뀜 · ➕ 지금 없음 = 되돌릴 항목 / ·· 지금만 있는 항목은 그대로 둠)')
    if not todo:
        print('✅ 되돌릴 항목 없음 — 지금과 백업이 같음'); return

    print(f'\n되돌릴 항목 {len(todo)}개: {", ".join(todo)}')
    ans = answer if answer is not None else input('되살릴까요? y 입력 (다른 키 = 취소): ').strip().lower()
    if ans != 'y':
        print('취소 — 아무것도 안 바꿈'); return

    stamp = datetime.datetime.now(KST).strftime('%Y-%m-%d_%H%M%S')
    keep = os.path.join(OUT_DIR, f'before_restore_{stamp}.json')
    with open(keep, 'w', encoding='utf-8') as f:
        f.write(json.dumps(cur, ensure_ascii=False))
    os.chmod(keep, 0o600)
    print(f'  지금 상태 먼저 저장: {keep}')

    mask = '&'.join('updateMask.fieldPaths=' + urllib.parse.quote(field_path(k), safe='') for k in todo)
    body = json.dumps({'fields': {k: bak_fields[k] for k in todo}}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url + '?' + mask, data=body, method='PATCH',
                                 headers=dict(auth, **{'Content-Type': 'application/json'}))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f'❌ 쓰기 실패 HTTP {e.code}: {e.read().decode("utf-8", "replace")[:200]}\n   (지금 상태는 위 파일에 저장돼 있음)')

    after = http_json(url, headers=auth).get('fields', {})
    bad = [k for k in todo if json.dumps(after.get(k), sort_keys=True) != json.dumps(bak_fields[k], sort_keys=True)]
    if bad:
        sys.exit(f'⚠ 쓴 뒤 다시 읽었더니 다른 항목: {", ".join(bad)}')
    print(f'✅ 되살림 {len(todo)}개 — 다시 읽어서 백업과 같은지 확인함. 사이트 새로고침하면 보임')
    print(f'   잘못됐으면: python3 scripts/backup_firestore.py --restore {keep}')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['--list']:
        cmd_list()
    elif a[:1] == ['--restore'] and len(a) >= 2:
        fl = None
        if '--field' in a:
            i = a.index('--field')
            fl = [x.strip() for x in ','.join(a[i + 1:]).split(',') if x.strip()]
        cmd_restore(a[1], fl)
    elif a:
        sys.exit(__doc__)
    else:
        main()
