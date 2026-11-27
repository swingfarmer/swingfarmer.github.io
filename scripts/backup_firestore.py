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
되살리기는 필요할 때 Claude에게 「백업 되살리기」 — 이 파일의 JSON(Firestore REST 형식)을 그대로 다시 쓸 수 있음.
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


if __name__ == '__main__':
    main()
