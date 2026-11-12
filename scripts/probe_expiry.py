#!/usr/bin/env python3
"""
(085) 만료일 조사용 1회성 스크립트 — 읽기만 함, 키·비번 값은 출력 안 함
 1) Oracle ADMIN 계정 비밀번호 만료일·상태 (user_users)
 2) ~/wallet 안 인증서(.pem)의 만료일
끝나면 git rm 예정. 결과를 보고 healthcheck.py에 만료 감시를 넣음.
"""
import os, re, glob, subprocess

WALLET_DIR = os.path.expanduser('~/wallet')

print('── 1) Oracle ADMIN 계정 ──')
try:
    import oracledb
    conn = oracledb.connect(
        user='ADMIN', password=os.environ.get('ORACLE_DB_PASSWORD', ''),
        dsn='db1007_medium', config_dir=WALLET_DIR, wallet_location=WALLET_DIR,
        wallet_password=os.environ.get('ORACLE_WALLET_PASSWORD', ''))
    cur = conn.cursor()
    cur.execute("SELECT username, account_status, expiry_date, profile FROM user_users")
    for r in cur.fetchall(): print('  계정', r[0], '| 상태', r[1], '| 비번 만료', r[2], '| 프로필', r[3])
    try:
        cur.execute("SELECT u.profile, p.limit FROM user_users u JOIN dba_profiles p ON p.profile=u.profile WHERE p.resource_name='PASSWORD_LIFE_TIME'")
        for r in cur.fetchall(): print('  비번 수명(PASSWORD_LIFE_TIME)', r[1], '(프로필', r[0]+')')
    except Exception as e:
        print('  비번 수명 조회 실패:', str(e)[:120])
    conn.close()
except Exception as e:
    print('  ❌ DB 조회 실패:', str(e)[:200])

print('── 2) 지갑 인증서 ──')
files = sorted(os.listdir(WALLET_DIR)) if os.path.isdir(WALLET_DIR) else []
print('  지갑 파일:', ', '.join(files) or '(없음)')
for f in sorted(glob.glob(os.path.join(WALLET_DIR, '*.pem'))):
    txt = open(f, encoding='utf-8', errors='ignore').read()
    certs = re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', txt, re.S)
    print(f'  {os.path.basename(f)}: 인증서 {len(certs)}개')
    for c in certs:
        try:
            out = subprocess.run(['openssl', 'x509', '-noout', '-subject', '-enddate'], input=c, capture_output=True, text=True, timeout=10).stdout
            subj = re.search(r'CN\s*=\s*([^,\n/]+)', out); end = re.search(r'notAfter=(.*)', out)
            print('    -', subj.group(1).strip() if subj else '?', '| 만료', end.group(1).strip() if end else '?')
        except Exception as e:
            print('    - openssl 실패:', str(e)[:100])
print('끝')
